"""Franchise completion: find the missing parts of every TMDB collection already in the catalog.

    python -m pipeline.franchises          (after step 5 has built a catalog; then rerun 5, 12, extend_serving)

For each catalog film that belongs to a TMDB collection (belongs_to_collection in its cached detail),
the collection is fetched once (cached as data/raw/tmdb_collections/<id>.json). A part that is not in
the catalog becomes a franchise candidate when it is released by the build date and has at least
franchise.min_vote_count TMDB votes (catalog_config.yaml). Candidates go to
data/processed/franchise_candidates.csv; their details are fetched like step 3. Step 5 then adds the
ones that pass the (relaxed) metadata gate as part D with franchise_rule=True: outside the evaluation
universe, so ratings, splits, models and results do not change (pipeline/eval_fingerprint.py checks it).
"""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path

import pandas as pd
import yaml

from pipeline.common import PROCESSED, RAW, TMDB_DIR, build_date, get_logger, read_json, write_json
from pipeline.tmdb import TMDB

log = get_logger("franchises")
COLLECTIONS_DIR = RAW / "tmdb_collections"
CFG = yaml.safe_load((Path(__file__).parent / "catalog_config.yaml").read_text(encoding="utf-8"))["franchise"]


def collection_of(tmdb_id: int) -> dict | None:
    path = TMDB_DIR / f"{tmdb_id}.json"
    return (read_json(path).get("belongs_to_collection") or None) if path.exists() else None


def fetch_collections(ids: list[int]) -> dict[int, dict]:
    tmdb = TMDB(rate=18)

    def one(cid: int):
        return cid, tmdb.cached(COLLECTIONS_DIR / f"{cid}.json", f"/collection/{cid}", language="en-US")

    with ThreadPoolExecutor(12) as pool:
        return {cid: data for cid, data in pool.map(one, ids) if data}


def missing_parts(collections: dict[int, dict], in_catalog: set[int], cutoff: str, min_votes: int) -> pd.DataFrame:
    """Every collection part not in the catalog, with the reason it is skipped (None = candidate)."""
    rows = []
    for cid, col in collections.items():
        for p in col.get("parts", []):
            if p["id"] in in_catalog:
                continue
            released = bool(p.get("release_date")) and p["release_date"] <= cutoff
            votes = p.get("vote_count") or 0
            reason = ("adult" if p.get("adult") else "not released" if not released
                      else f"fewer than {min_votes} votes" if votes < min_votes else None)
            rows.append({"tmdb_id": p["id"], "title": p.get("title"), "release_date": p.get("release_date") or None,
                         "tmdb_vote_count": votes, "collection_id": cid, "collection_name": col.get("name"),
                         "skip_reason": reason})
    return pd.DataFrame(rows, columns=["tmdb_id", "title", "release_date", "tmdb_vote_count", "collection_id",
                                       "collection_name", "skip_reason"])


def main() -> None:
    catalog = set(pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id"])["tmdb_id"])
    # Collections come from the catalog without earlier franchise additions, so a rerun finds the same set.
    old = PROCESSED / "franchise_candidates.csv"
    base = catalog - (set(pd.read_csv(old)["tmdb_id"]) if old.exists() else set())
    cols = sorted({c["id"] for t in base if (c := collection_of(t))})
    log.info("catalog films belong to %d collections", len(cols))
    collections = fetch_collections(cols)
    miss = missing_parts(collections, base, build_date().isoformat(), CFG["min_vote_count"]).drop_duplicates("tmdb_id")
    import_module("pipeline.03_fetch_tmdb").fetch_all(sorted(miss.loc[miss["skip_reason"].isna(), "tmdb_id"].tolist()))
    # Shorts (mockumentaries, tie-in clips) are collection parts too; the runtime comes from the detail.
    runtime = miss["tmdb_id"].map(lambda t: (read_json(TMDB_DIR / f"{t}.json").get("runtime") or 0)
                                  if (TMDB_DIR / f"{t}.json").exists() else 0)
    short = miss["skip_reason"].isna() & (runtime < CFG["min_runtime_min"])
    miss.loc[short, "skip_reason"] = f"shorter than {CFG['min_runtime_min']} minutes"
    cand = miss[miss["skip_reason"].isna()]
    cand[["tmdb_id", "tmdb_vote_count", "collection_id"]].assign(part="D", franchise=True).to_csv(old, index=False)
    log.info("missing parts: %d; candidates: %d; skipped: %s", len(miss), len(cand),
             miss["skip_reason"].dropna().str.replace(r"\d+", "N", regex=True).value_counts().to_dict())
    write_json(PROCESSED / "franchise_report.json", {
        "build_date": build_date().isoformat(), "min_vote_count": CFG["min_vote_count"],
        "collections": len(collections), "missing_parts": int(len(miss)), "candidates": int(len(cand)),
        "candidate_list": cand[["tmdb_id", "title", "release_date", "tmdb_vote_count", "collection_name"]]
        .to_dict("records"),
        "skipped": miss[miss["skip_reason"].notna()][["tmdb_id", "title", "collection_name", "skip_reason"]]
        .to_dict("records"),
    })


if __name__ == "__main__":
    main()
