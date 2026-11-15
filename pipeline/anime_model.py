"""One anime model for anime series AND anime films, learned from real anime lists (Kaggle "Anime Recommendations
Database", data/raw/anime; CC0 tag by the uploader, lists from MyAnimeList, a licence risk the site owner accepted,
credited on the Terms page).

    python -m pipeline.anime_model            # fit on all list users, write artifacts/models/anime_model.json

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

from pipeline.common import ARTIFACTS, PROCESSED, RAW, get_logger, write_json
from pipeline.drama_cf import norm, weights
from pipeline.models_io import MODELS
from pipeline.series import TV_OFFSET

log = get_logger("anime_model")
SRC = RAW / "anime"
OUT = MODELS / "anime_model.json"
ALT_TV = RAW / "tmdb_alt_titles"
ALT_MOVIE = RAW / "tmdb_alt_titles_movie"
SERIES_TYPES = ("TV", "ONA")
FRIBB = SRC / "anime-list-full.json"
FRIBB_URL = "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json"
LAM = 300.0          # chosen on validation users in pipeline/anime_rank_eval.py
TOP = 60             # votes kept per anime


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


def mapping(movies: pd.DataFrame, film_ids: set[int], fetch: bool = False, use_ids: bool = True) -> pd.DataFrame:
    """sid, tmdb_id, format ('series' or 'film'): dataset entries of the catalog's anime series and anime films. First
    the id map (exact ids; seasons of one series all point at it), then exact normalized titles for catalog titles the
    id map did not reach. One dataset entry maps to one title; one title can have several entries."""
    anime = pd.read_csv(SRC / "anime.csv")
    series = movies[movies["title_type"] == "anime"]
    films = movies[movies["tmdb_id"].isin(film_ids)]
    known = set(anime["anime_id"])
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


def main() -> None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
    from cinematch_engine import taxonomy
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
    films = {int(r.tmdb_id) for r in movies.itertuples()
             if taxonomy.lane(str(r.title_type), list(r.genres), r.original_language, None) == "anime_film"}
    m = mapping(movies, films, fetch=True)
    m.to_csv(PROCESSED / "anime_model_map.csv", index=False)
    pairs = as_pairs(pd.read_csv(SRC / "rating.csv"))
    titles = m.drop_duplicates(["format", "tmdb_id"]).reset_index(drop=True)
    col = {(f, t): i for i, (f, t) in enumerate(zip(titles["format"], titles["tmdb_id"]))}
    x = matrix(pairs, {int(sid): col[(f, t)] for sid, f, t in zip(m["sid"], m["format"], m["tmdb_id"])}, len(titles))
    s = sparsify(ease(x))
    tm = titles["tmdb_id"].tolist()
    votes = {str(tm[i]): [[tm[j], round(float(v), 5)] for j, v in sorted(zip(s[i].indices, s[i].data), key=lambda t: -t[1])]
             for i in range(s.shape[0]) if s[i].nnz}
    write_json(OUT, {"settings": {"method": "ease", "lam": LAM, "top": TOP}, "series": int((titles.format == "series").sum()),
                     "films": int((titles.format == "film").sum()), "users": int(x.shape[0]), "votes": votes})
    log.info("wrote anime model: %d anime, %d votes, %d list users (no users kept)", len(votes), s.nnz, x.shape[0])


if __name__ == "__main__":
    main()
