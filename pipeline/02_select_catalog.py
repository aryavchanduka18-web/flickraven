"""Step 2: collect catalog candidates for parts A, B and C.

A: MovieLens films with >= 50 ratings, mapped to TMDB through links.csv.
B: TMDB discover per original language, sorted by vote count.
C: TMDB discover for releases in the 18 months before the build date.

The final cut (A threshold tuned near 10,000, B capped per language, C tuned to 300-500)
needs the metadata gate, so it is made in step 5. This step writes the candidate pool
(catalog_candidates.csv) plus the MovieLens per-film aggregates used later.
"""
from datetime import date

import numpy as np
import pandas as pd
import yaml

from pipeline.common import DISCOVER_DIR, ML_DIR, PROCESSED, build_date, get_logger, write_json
from pipeline.tmdb import TMDB

log = get_logger("02_select")
QUOTAS = yaml.safe_load((__import__("pathlib").Path(__file__).parent / "curated" / "language_quotas.yaml").read_text(encoding="utf-8"))
HOLLYWOOD = yaml.safe_load((__import__("pathlib").Path(__file__).parent / "catalog_config.yaml").read_text(encoding="utf-8"))["hollywood"]


def months_before(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m + 1, min(d.day, 28))


def ml_aggregates() -> pd.DataFrame:
    """Per-film count, mean and 10-bucket histogram over ALL MovieLens ratings, on the 1-10 scale."""
    ratings = pd.read_csv(
        ML_DIR / "ratings.csv", usecols=["movieId", "rating"],
        dtype={"movieId": "int32", "rating": "float32"}, engine="pyarrow",
    )
    r10 = (ratings["rating"] * 2).round().astype("int8")
    hist = (
        pd.crosstab(ratings["movieId"], r10).reindex(columns=range(1, 11), fill_value=0).astype("int32")
    )
    agg = pd.DataFrame({
        "ml_rating_count": hist.sum(axis=1).astype("int32"),
        "ml_rating_mean": (hist.values * np.arange(1, 11)).sum(axis=1) / hist.sum(axis=1),
    }, index=hist.index)
    agg["rating_hist"] = hist.values.tolist()
    agg.index.name = "ml_movie_id"
    return agg.reset_index()


def part_a(agg: pd.DataFrame) -> pd.DataFrame:
    links = pd.read_csv(ML_DIR / "links.csv", dtype={"movieId": "int32", "imdbId": "str", "tmdbId": "Int64"})
    links = links.dropna(subset=["tmdbId"]).rename(columns={"movieId": "ml_movie_id", "tmdbId": "tmdb_id", "imdbId": "imdb_id"})
    a = links.merge(agg[["ml_movie_id", "ml_rating_count"]], on="ml_movie_id")
    a = a[a["ml_rating_count"] >= QUOTAS["part_a"]["min_ratings"]]
    # Several MovieLens ids can map to one TMDB film: keep the one with most ratings.
    a = a.sort_values("ml_rating_count", ascending=False).drop_duplicates("tmdb_id")
    a["part"] = "A"
    return a[["tmdb_id", "ml_movie_id", "imdb_id", "ml_rating_count", "part"]]


def discover(tmdb: TMDB, key: str, max_results: int, **params) -> list[dict]:
    results: list[dict] = []
    page = 1
    while len(results) < max_results:
        data = tmdb.cached(DISCOVER_DIR / f"{key}_p{page}.json", "/discover/movie", page=page, **params)
        if not data or not data.get("results"):
            break
        results.extend(data["results"])
        if page >= data.get("total_pages", 1) or page >= 500:
            break
        page += 1
    return results[:max_results]


def part_b(tmdb: TMDB) -> pd.DataFrame:
    cfg = QUOTAS["part_b"]
    rows = []
    for lang in cfg["languages"]:
        min_votes = cfg["min_votes_low_volume"] if lang in cfg["low_volume_languages"] else cfg["min_votes"]
        limit = cfg["candidates_per_language"]
        if lang in cfg.get("boost_languages", []):
            min_votes, limit = cfg["boost_floor"], cfg["boost_candidates"]
        found = discover(
            tmdb, f"lang_{lang}_v{min_votes}", limit,
            with_original_language=lang, sort_by="vote_count.desc", include_adult="false",
            **{"vote_count.gte": min_votes, "primary_release_date.lte": build_date().isoformat()},
        )
        log.info("part B %s: %d candidates (vote_count >= %d)", lang, len(found), min_votes)
        rows += [{"tmdb_id": m["id"], "tmdb_vote_count": m["vote_count"], "discover_language": lang} for m in found]
    b = pd.DataFrame(rows).drop_duplicates("tmdb_id")
    b["part"] = "B"
    return b


def part_c(tmdb: TMDB) -> tuple[pd.DataFrame, dict]:
    cfg = QUOTAS["part_c"]
    end = build_date()
    start = months_before(end, cfg["months"])
    found = discover(
        tmdb, f"new_{start}_{end}_v{cfg['pool_min_votes']}", 10_000,
        sort_by="vote_count.desc", include_adult="false",
        **{"primary_release_date.gte": start.isoformat(), "primary_release_date.lte": end.isoformat(),
           "vote_count.gte": cfg["pool_min_votes"]},
    )
    log.info("part C pool: %d releases %s..%s with vote_count >= %d", len(found), start, end, cfg["pool_min_votes"])
    c = pd.DataFrame([{"tmdb_id": m["id"], "tmdb_vote_count": m["vote_count"]} for m in found]).drop_duplicates("tmdb_id")
    c["part"] = "C"
    return c, {"start": start.isoformat(), "end": end.isoformat()}


def part_d(tmdb: TMDB) -> pd.DataFrame:
    """Well-known films of any language with >= pool_min_vote_count votes. Whether 'US' is a
    production country (and which rule applies) is decided from the detail JSON in step 5."""
    floor = HOLLYWOOD["pool_min_vote_count"]
    found = discover(
        tmdb, f"famous_v{floor}_{build_date()}", 10_000, sort_by="vote_count.desc", include_adult="false",
        **{"vote_count.gte": floor, "primary_release_date.lte": build_date().isoformat()},
    )
    log.info("part D pool: %d films with vote_count >= %d", len(found), floor)
    d = pd.DataFrame([{"tmdb_id": m["id"], "tmdb_vote_count": m["vote_count"]} for m in found]).drop_duplicates("tmdb_id")
    d["part"] = "D"
    return d


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    agg = ml_aggregates()
    agg.to_parquet(PROCESSED / "ml_aggregates.parquet", index=False)
    a = part_a(agg)
    log.info("part A candidates: %d films with >= %d ratings", len(a), QUOTAS["part_a"]["min_ratings"])
    tmdb = TMDB()
    b = part_b(tmdb)
    c, window = part_c(tmdb)
    d = part_d(tmdb)
    cand = pd.concat([a, b, c, d], ignore_index=True)
    cand["tmdb_id"] = cand["tmdb_id"].astype("int64")
    cand.to_csv(PROCESSED / "catalog_candidates.csv", index=False)
    write_json(PROCESSED / "catalog_candidates_summary.json", {
        "build_date": build_date().isoformat(), "part_c_window": window,
        "candidates": cand.groupby("part").size().to_dict(),
        "part_b_per_language": b.groupby("discover_language").size().to_dict(),
    })
    log.info("candidates: %s", cand.groupby("part").size().to_dict())


if __name__ == "__main__":
    main()