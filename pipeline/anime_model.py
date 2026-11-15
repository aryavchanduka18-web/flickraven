"""One anime model for anime series AND anime films, learned from real anime lists (Kaggle "Anime Recommendations
Database", data/raw/anime; CC0 tag by the uploader, lists from MyAnimeList, a licence risk the site owner accepted,
credited on the Terms page).

    python -m pipeline.anime_model --ratings data/raw/anime2023/rating.csv --out artifacts/models/anime_model.npz

Method: EASE (Steck 2019), a linear item-to-item model with a closed-form fit: B = I - P / diag(P), P = (X'X + lam I)^-1,
over the anime that can be matched to the catalog (TV/ONA entries to anime series, Movie entries to anime films). A
person's score for anime j is sum_i w_i * B[i, j] over the anime i they rated 7+, liked or picked. Unlike the older
cosine neighbours (pipeline/anime_cf.py) the weights are learned jointly, so a title that is only "popular among
everyone" does not get a vote from every list it appears in. Only the top votes per anime are kept (no users).

Offline test: pipeline/anime_rank_eval.py (held-out list users, today's ranking vs this model).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import scipy.sparse as sp

from pipeline.common import PROCESSED, RAW, get_logger, write_json
from pipeline.drama_cf import norm, weights
from pipeline.models_io import MODELS
from pipeline.series import TV_OFFSET

log = get_logger("anime_model")
SRC = RAW / "anime"
OUT = MODELS / "anime_model.npz"
ALT_TV = RAW / "tmdb_alt_titles"
ALT_MOVIE = RAW / "tmdb_alt_titles_movie"
SERIES_TYPES = ("TV", "ONA")
MAP = PROCESSED / "anime_model_map.csv"
FRIBB = SRC / "anime-list-full.json"
FRIBB_URL = "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json"
# Chosen on validation users in pipeline/anime_rank_eval.py (2026-11-15, 2017 and 2023 lists): the low-regularised EASE
# model is best for long lists, the high-regularised one for about 15 liked anime, and for about 5 that one half and
# half with cosine neighbours. The engine picks by the number of liked anime it knows (ANIME_SHORT_MAX, ANIME_MID_MAX).
LAM = 300.0          # "long"
LAM_MID = 30000.0    # "mid" (and half of "short")
SHRINK = 25.0        # cosine co-count shrinkage ("short"), as pipeline/drama_cf.py
TOP = 200            # votes kept per anime and model


def as_pairs(ratings: pd.DataFrame) -> pd.DataFrame:
    """rating.csv (user_id, anime_id, rating; -1 = watched without a rating) as (uid, sid, score, completed)."""
    return pd.DataFrame({"uid": ratings["user_id"], "sid": ratings["anime_id"],
                         "score": ratings["rating"].where(ratings["rating"] >= 0, 0.0).astype(float),
                         "completed": ratings["rating"] == -1})


def alt_titles(tmdb_ids, kind: str, fetch: bool = False) -> dict[int, list[str]]:
    """TMDB alternative titles (romanizations matter: the dataset uses romaji names). Series files are cached in
    data/raw/tmdb_alt_titles; film files in data/raw/tmdb_alt_titles_movie, fetched from TMDB when `fetch`."""
    folder = ALT_TV if kind == "series" else ALT_MOVIE
    client = None
    out = {}
    for tid in tmdb_ids:
        f = folder / f"{int(tid)}.json"
        if not f.exists() and fetch and kind == "movie":
            if client is None:
                from pipeline.tmdb import TMDB
                client = TMDB()
            d = client.cached(f, f"/movie/{int(tid)}/alternative_titles")
        else:
            d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        d = d or {}
        out[int(tid)] = [x["title"] for x in d.get("results", d.get("titles", []))]
    return out


def match(anime: pd.DataFrame, cands: pd.DataFrame, types, alts: dict[int, list[str]]) -> list[dict]:
    """Catalog titles (tmdb_id, title, original_title) -> dataset id by exact normalized title; only dataset entries
    of `types`; the best-known one when several share a title."""
    a = anime[anime["type"].isin(types)].copy()
    a["n"] = a["name"].map(norm)
    a = a.sort_values("members", ascending=False).drop_duplicates("n")
    by = dict(zip(a["n"], a["anime_id"]))
    out = []
    for r in cands.itertuples():
        for t in [r.title, r.original_title, *alts.get(int(r.tmdb_id), [])]:
            if norm(t) in by:
                out.append({"tmdb_id": int(r.tmdb_id), "sid": int(by[norm(t)])})
                break
    return out


def fribb() -> list[dict]:
    """The Fribb anime-lists id map (github.com/Fribb/anime-lists, ODbL): MyAnimeList id -> TMDB tv / movie id.
    Downloaded once to data/raw/anime/anime-list-full.json (git-ignored); an empty list when it cannot be had."""
    if not FRIBB.exists():
        try:
            import httpx
            r = httpx.get(FRIBB_URL, timeout=120, follow_redirects=True)
            r.raise_for_status()
            FRIBB.write_bytes(r.content)
        except Exception as e:                                   # offline: title matching only
            log.warning("id map not available (%s); matching by title only", e)
            return []
    return json.loads(FRIBB.read_text(encoding="utf-8"))


def id_matches(entries: list[dict], series_ids: set[int], film_ids: set[int]) -> list[dict]:
    """Dataset id -> catalog title from the id map. Several dataset entries (seasons) can point at one series."""
    out = []
    for e in entries:
        t, sid = e.get("themoviedb_id"), e.get("mal_id")
        if not isinstance(t, dict) or sid is None:
            continue
        tv = t.get("tv")
        if e.get("type") in SERIES_TYPES and isinstance(tv, int) and TV_OFFSET + tv in series_ids:      # catalog series ids are offset
            out.append({"tmdb_id": TV_OFFSET + tv, "sid": int(sid), "format": "series"})
        mv = t.get("movie") or []
        mv = [mv] if isinstance(mv, int) else mv
        hit = [x for x in mv if x in film_ids]
        if e.get("type") == "MOVIE" and len(hit) == 1:
            out.append({"tmdb_id": int(hit[0]), "sid": int(sid), "format": "film"})
    return out


def mapping(movies: pd.DataFrame, film_ids: set[int], fetch: bool = False, use_ids: bool = True, sids=None) -> pd.DataFrame:
    """sid, tmdb_id, format ('series' or 'film'): dataset entries of the catalog's anime series and anime films. First
    the id map (exact ids; seasons of one series all point at it), then exact normalized titles for catalog titles the
    id map did not reach. One dataset entry maps to one title; one title can have several entries."""
    series = movies[movies["title_type"] == "anime"]
    films = movies[movies["tmdb_id"].isin(film_ids)]
    if use_ids and MAP.exists() and sids is not None:      # another ratings file in the same format: only the id map applies
        anime, known = None, set(sids)
    else:
        anime = pd.read_csv(SRC / "anime.csv")
        known = set(anime["anime_id"])
    if use_ids and MAP.exists():
        # The reviewed id map (built by the anime-data kit: TMDB and IMDb ids, seasons/OVAs/specials merged into their
        # series) is the one matching path when it is there; the code below is only the fallback without it.
        m = pd.read_csv(MAP)[["tmdb_id", "sid", "format"]]
        ok = set(series["tmdb_id"]) | set(films["tmdb_id"])
        m = m[m["sid"].isin(known) & m["tmdb_id"].isin(ok)].drop_duplicates("sid").reset_index(drop=True)
        t = m.drop_duplicates("tmdb_id")
        log.info("id map file: matched %d of %d anime series and %d of %d anime films in this dataset (%d dataset entries)",
                 int((t.format == "series").sum()), len(series), int((t.format == "film").sum()), len(films), len(m))
        return m
    ids = [x for x in id_matches(fribb() if use_ids else [], set(series["tmdb_id"]), set(films["tmdb_id"])) if x["sid"] in known]
    done = {(x["format"], x["tmdb_id"]) for x in ids}
    s = match(anime, series[[("series", int(t)) not in done for t in series["tmdb_id"]]], SERIES_TYPES,
              alt_titles(series["tmdb_id"], "series"))
    f = match(anime, films[[("film", int(t)) not in done for t in films["tmdb_id"]]], ("Movie",),
              alt_titles(films["tmdb_id"], "movie", fetch))
    m = pd.DataFrame(ids + [{**x, "format": "series"} for x in s] + [{**x, "format": "film"} for x in f],
                     columns=["tmdb_id", "sid", "format"])
    m = m.drop_duplicates("sid").reset_index(drop=True)
    t = m.drop_duplicates(["format", "tmdb_id"])
    log.info("matched %d of %d anime series and %d of %d anime films (%d by id map, %d dataset entries)",
             int((t.format == "series").sum()), len(series), int((t.format == "film").sum()), len(films),
             len({(x["format"], x["tmdb_id"]) for x in ids}), len(m))
    return m


def matrix(pairs: pd.DataFrame, col_of_sid: dict[int, int], n: int, drop_uids=(), min_items: int = 3) -> sp.csr_matrix:
    """Users x titles entry weights (7+ = 0.6..1, completed without a score = 0.5; the strongest entry when several
    seasons point at one title), without the `drop_uids` users."""
    r = pairs[pairs["sid"].isin(col_of_sid) & ~pairs["uid"].isin(set(drop_uids))].copy()
    r["w"] = weights(r)
    r = r[r["w"] > 0]
    r["col"] = r["sid"].map(col_of_sid)
    r = r.groupby(["uid", "col"], as_index=False)["w"].max()
    r = r[r.groupby("uid")["col"].transform("size") >= min_items]
    users = {u: i for i, u in enumerate(np.sort(r["uid"].unique()))}
    return sp.csr_matrix((r["w"].to_numpy(), (r["uid"].map(users).to_numpy(), r["col"].to_numpy())), shape=(len(users), n))


def ease(x: sp.csr_matrix, lam: float = LAM) -> np.ndarray:
    """EASE item-item weights (items x items, zero diagonal)."""
    g = (x.T @ x).toarray().astype(np.float64)
    g[np.diag_indices_from(g)] += lam
    p = np.linalg.inv(g)
    b = -p / np.diag(p)
    np.fill_diagonal(b, 0.0)
    return b


def sparsify(b: np.ndarray, k: int = TOP) -> sp.csr_matrix:
    """Keep the k largest positive votes of each anime (row i = the anime that i votes for)."""
    rows, cols, vals = [], [], []
    for i in range(b.shape[0]):
        top = np.argpartition(-b[i], min(k, b.shape[1] - 1))[:k]
        top = top[b[i, top] > 0]
        rows += [i] * len(top); cols += top.tolist(); vals += b[i, top].tolist()
    return sp.csr_matrix((vals, (rows, cols)), shape=b.shape, dtype=np.float32)


def cosine(x: sp.csr_matrix, shrink: float = SHRINK) -> np.ndarray:
    """Item-item cosine of the entry weights, shrunk by how many users have both titles, zero diagonal."""
    present = (x > 0).astype(np.float64)
    xn = x @ sp.diags(1 / np.sqrt(np.maximum(np.asarray(x.multiply(x).sum(axis=0)).ravel(), 1e-9)))
    cos = (xn.T @ xn).toarray()
    both = (present.T @ present).toarray()
    cos = cos * both / (both + shrink)
    np.fill_diagonal(cos, 0)
    return cos


def fit(x: sp.csr_matrix) -> dict[str, sp.csr_matrix]:
    """The three served models over the columns of x, each with the top TOP votes per title."""
    return {"long": sparsify(ease(x, LAM)), "mid": sparsify(ease(x, LAM_MID)), "short": sparsify(cosine(x))}


RATINGS_2023 = RAW / "anime2023" / "rating.csv"      # the served model's lists (2023 MyAnimeList dump, no usernames)


def sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    """Build the served model (documented in docs/anime-model-eval.md, "Building the model file"):

        python -m pipeline.anime_model --ratings data/raw/anime2023/rating.csv --out artifacts/models/anime_model.npz

    --ratings defaults to the 2023 lists, so a plain run never builds a 2017 model by accident. The file records the
    ratings file, the id map and their SHA-256, and the log prints the model file's SHA-256."""
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default=str(RATINGS_2023),
                    help="ratings file (user_id, anime_id, rating); default the 2023 lists, data/raw/anime2023/rating.csv")
    ap.add_argument("--out", help="where to write the model (default artifacts/models/anime_model.npz, which the site loads)")
    a = ap.parse_args()
    ratings = Path(a.ratings)
    legacy = ratings.resolve() == (SRC / "rating.csv").resolve()        # the 2017 lists: also allows title matching
    out = Path(a.out) if a.out else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
    from cinematch_engine import taxonomy
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
    films = {int(r.tmdb_id) for r in movies.itertuples()
             if taxonomy.lane(str(r.title_type), list(r.genres), r.original_language, None) == "anime_film"}
    pairs = as_pairs(pd.read_csv(ratings))
    m = mapping(movies, films, fetch=legacy, sids=None if legacy else set(pairs["sid"].unique()))
    titles = m.drop_duplicates(["format", "tmdb_id"]).reset_index(drop=True)
    col = {(f, t): i for i, (f, t) in enumerate(zip(titles["format"], titles["tmdb_id"]))}
    x = matrix(pairs, {int(sid): col[(f, t)] for sid, f, t in zip(m["sid"], m["format"], m["tmdb_id"])}, len(titles))
    tm = np.asarray(titles["tmdb_id"], dtype=np.int64)
    arrays = {}
    for name, s in fit(x).items():
        c = s.tocoo()
        arrays[f"{name}_src"], arrays[f"{name}_dst"], arrays[f"{name}_w"] = tm[c.row], tm[c.col], c.data.astype(np.float32)
    root = Path(__file__).resolve().parents[1]
    rel = lambda p: Path(p).relative_to(root).as_posix() if Path(p).is_absolute() and Path(p).is_relative_to(root) else Path(p).as_posix()
    meta = {"lam_long": LAM, "lam_mid": LAM_MID, "cosine_shrink": SHRINK, "top": TOP,
            "ratings": rel(ratings), "ratings_sha256": sha256(ratings),
            "id_map": rel(MAP) if MAP.exists() else None, "id_map_sha256": sha256(MAP) if MAP.exists() else None,
            "series": int((titles.format == "series").sum()), "films": int((titles.format == "film").sum()),
            "users": int(x.shape[0])}
    with open(out, "wb") as f:                       # a file object: np.savez must not add its own ".npz"
        np.savez_compressed(f, settings=np.array(json.dumps(meta)), **arrays)
    log.info("wrote anime model %s: %d series, %d films, %d list users (no users kept); sha256 %s",
             out, int((titles.format == "series").sum()), int((titles.format == "film").sum()), x.shape[0], sha256(out))


if __name__ == "__main__":
    main()
