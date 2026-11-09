"""Anime-to-anime similarities learned from real user lists (collaborative signal for the anime rows).

    python -m pipeline.anime_cf

Data: the Kaggle "Anime Recommendations Database" (data/raw/anime/anime.csv and rating.csv, 73k users; CC0 tag by the
uploader; the lists originate from MyAnimeList, a leftover licence risk the site owner has accepted, see
docs/decisions-log.md and the Terms page credit). Nothing from it is stored on the site: only the learned
anime-to-anime similarities (top 30 neighbours per anime) are written, to artifacts/models/anime_neighbors.json, and
the offline check to artifacts/metrics/anime_cf_eval.json.

Same method as pipeline/drama_cf.py (entries rated 7+ are liked, watched-without-a-rating counts less, item-item
cosine with shrinkage, hit@10 check against popularity and content similarity); this module only reads the anime
files into that format and matches the anime to TMDB. anime.csv has no year, so TMDB anime are matched by normalized
title: the English title, the original title or any TMDB alternative title (romanizations). The dataset ends around
2017: about 80% of anime up to 2014 match, almost none from 2018 on, which keep using content similarity and popularity.
"""
import json

import pandas as pd

from pipeline.common import ARTIFACTS, PROCESSED, RAW, get_logger, write_json
from pipeline.drama_cf import K, content_rows, evaluate, norm, similarities, top_k, user_item_matrix
from pipeline.models_io import MODELS

log = get_logger("anime_cf")
SRC = RAW / "anime"
NEIGHBORS = MODELS / "anime_neighbors.json"
EVAL = ARTIFACTS / "metrics" / "anime_cf_eval.json"


def as_pairs(ratings: pd.DataFrame) -> pd.DataFrame:
    """rating.csv (user_id, anime_id, rating; -1 = watched without a rating) in the drama_cf format
    (uid, sid, score, completed): a rating of -1 becomes an unscored completed entry."""
    return pd.DataFrame({"uid": ratings["user_id"], "sid": ratings["anime_id"],
                         "score": ratings["rating"].where(ratings["rating"] >= 0, 0.0).astype(float),
                         "completed": ratings["rating"] == -1})


def match_anime(anime: pd.DataFrame, catalog: pd.DataFrame, alts: dict[int, list[str]]) -> pd.DataFrame:
    """TMDB anime -> MyAnimeList id by exact normalized title (English, original or any alternative title);
    only TV entries of the dataset, and the best-known one when several share a title."""
    tv = anime[anime["type"] == "TV"].copy()
    tv["n"] = tv["name"].map(norm)
    tv = tv.sort_values("members", ascending=False).drop_duplicates("n")
    mal = dict(zip(tv["n"], tv["anime_id"]))
    rows = []
    for r in catalog[catalog["title_type"] == "anime"].itertuples():
        hits = [mal[norm(x)] for x in [r.title, r.original_title, *alts.get(int(r.tmdb_id), [])] if norm(x) in mal]
        if hits:
            rows.append({"tmdb_id": int(r.tmdb_id), "sid": int(hits[0])})
    return pd.DataFrame(rows, columns=["tmdb_id", "sid"]).drop_duplicates("sid")


def main() -> None:
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id", "title", "original_title", "title_type"])
    alts = {}
    for tid in movies[movies["title_type"] == "anime"]["tmdb_id"]:
        f = RAW / "tmdb_alt_titles" / f"{tid}.json"
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        alts[int(tid)] = [x["title"] for x in (d or {}).get("results", [])]
    mapping = match_anime(pd.read_csv(SRC / "anime.csv"), movies, alts)
    mapping.to_csv(PROCESSED / "anime_mal_map.csv", index=False)
    log.info("matched %d of %d anime to the dataset", len(mapping), int((movies["title_type"] == "anime").sum()))
    pairs = as_pairs(pd.read_csv(SRC / "rating.csv"))
    items = mapping["sid"].tolist()
    result = evaluate(pairs, items, content=content_rows(mapping["tmdb_id"].tolist()))
    log.info("offline check: %s", result)
    x, users = user_item_matrix(pairs, items)
    tmdb_of = dict(zip(mapping["sid"], mapping["tmdb_id"]))
    neighbors = {str(tmdb_of[items[i]]): [[tmdb_of[items[j]], round(v, 4)] for j, v in nb]
                 for i, nb in enumerate(top_k(similarities(x), K))}
    MODELS.mkdir(parents=True, exist_ok=True)
    write_json(NEIGHBORS, {"settings": {"k": K}, "anime": len(neighbors), "neighbors": neighbors})
    write_json(EVAL, {**result, "matched_anime": len(mapping), "users_used": int(len(users))})
    log.info("wrote similarities for %d anime (no users kept)", len(neighbors))


if __name__ == "__main__":
    main()
