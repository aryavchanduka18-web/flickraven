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

log = get_logger("anime_model")
SRC = RAW / "anime"
OUT = MODELS / "anime_model.json"
ALT_TV = RAW / "tmdb_alt_titles"
ALT_MOVIE = RAW / "tmdb_alt_titles_movie"
SERIES_TYPES = ("TV", "ONA")
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


def mapping(movies: pd.DataFrame, film_ids: set[int], fetch: bool = False) -> pd.DataFrame:
    """tmdb_id, sid, format ('series' or 'film') for every catalog anime series and anime film that matches."""
    anime = pd.read_csv(SRC / "anime.csv")
    series = movies[movies["title_type"] == "anime"]
    films = movies[movies["tmdb_id"].isin(film_ids)]
    s = match(anime, series, SERIES_TYPES, alt_titles(series["tmdb_id"], "series"))
    f = match(anime, films, ("Movie",), alt_titles(films["tmdb_id"], "movie", fetch))
    m = pd.DataFrame([{**x, "format": "series"} for x in s] + [{**x, "format": "film"} for x in f],
                     columns=["tmdb_id", "sid", "format"])
    m = m.drop_duplicates("sid").drop_duplicates("tmdb_id").reset_index(drop=True)
    log.info("matched %d of %d anime series and %d of %d anime films", int((m.format == "series").sum()), len(series),
             int((m.format == "film").sum()), len(films))
    return m


def matrix(pairs: pd.DataFrame, items: list[int], drop_uids=(), min_items: int = 3) -> sp.csr_matrix:
    """Users x items entry weights (7+ = 0.6..1, completed without a score = 0.5), without the `drop_uids` users."""
    col = {a: i for i, a in enumerate(items)}
    r = pairs[pairs["sid"].isin(col) & ~pairs["uid"].isin(set(drop_uids))].copy()
    r["w"] = weights(r)
    r = r[r["w"] > 0]
    r = r[r.groupby("uid")["sid"].transform("size") >= min_items]
    users = {u: i for i, u in enumerate(np.sort(r["uid"].unique()))}
    return sp.csr_matrix((r["w"].to_numpy(), (r["uid"].map(users).to_numpy(), r["sid"].map(col).to_numpy())),
                         shape=(len(users), len(items)))


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
    items = m["sid"].tolist()
    x = matrix(pairs, items)
    s = sparsify(ease(x))
    tm = m["tmdb_id"].tolist()
    votes = {str(tm[i]): [[tm[j], round(float(v), 5)] for j, v in sorted(zip(s[i].indices, s[i].data), key=lambda t: -t[1])]
             for i in range(s.shape[0]) if s[i].nnz}
    write_json(OUT, {"settings": {"method": "ease", "lam": LAM, "top": TOP}, "series": int((m.format == "series").sum()),
                     "films": int((m.format == "film").sum()), "users": int(x.shape[0]), "votes": votes})
    log.info("wrote anime model: %d anime, %d votes, %d list users (no users kept)", len(votes), s.nnz, x.shape[0])


if __name__ == "__main__":
    main()
