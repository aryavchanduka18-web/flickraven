"""Wider catalog: well-known films the catalog does not have yet (Indian languages, Hollywood, Korean and
Japanese), found through TMDB discover with the floors in catalog_config.yaml (widen).

    python -m pipeline.widen_catalog        (then rerun step 5, step 12 and extend_serving; monthly_refresh.ps1 does)

Candidates are ADDED to data/processed/widen_candidates.csv, never replaced, and their details are fetched
like step 3. Step 5 adds the ones that pass the metadata gate as part D. They have no MovieLens ratings, so
ratings, splits, models and evaluation results do not change (the same reason the franchise rule is safe).
"""
from datetime import date
from importlib import import_module
from pathlib import Path

import pandas as pd
import yaml

from pipeline.common import PROCESSED, get_logger, write_json
from pipeline.tmdb import TMDB

log = get_logger("widen_catalog")
CFG = yaml.safe_load((Path(__file__).parent / "catalog_config.yaml").read_text())["widen"]
CANDIDATES = PROCESSED / "widen_candidates.csv"
COLUMNS = ["tmdb_id", "tmdb_vote_count", "group", "found_on", "part"]


def queries() -> list[tuple[str, str, int, int, dict]]:
    """(group, cache key, max results, min votes, discover filters) for every discover call."""
    out = []
    for group, g in CFG["groups"].items():
        if "periods" in g:
            for lo, hi in g["periods"]:
                out.append((group, f"widen_all_{lo}_{hi}_v{g['min_votes']}", g["max_per_period"], g["min_votes"],
                            {"primary_release_date.gte": f"{lo}-01-01", "primary_release_date.lte": f"{hi}-12-31"}))
        elif "languages" in g:
            for lang, votes in g["languages"].items():
                out.append((group, f"widen_{lang}_v{votes}", g["max_per_language"], votes,
                            {"with_original_language": lang}))
        else:
            c = g["origin_country"]
            out.append((group, f"widen_{c}_v{g['min_votes']}", g["max"], g["min_votes"], {"with_origin_country": c}))
    return out


def find() -> pd.DataFrame:
    discover = import_module("pipeline.02_select_catalog").discover
    tmdb, rows = TMDB(), []
    for group, key, limit, votes, filters in queries():
        found = discover(tmdb, key, limit, sort_by="vote_count.desc", include_adult="false",
                         **{"vote_count.gte": votes, "with_runtime.gte": CFG["min_runtime_min"]}, **filters)
        log.info("%s %s: %d films with >= %d votes", group, filters, len(found), votes)
        rows += [{"tmdb_id": m["id"], "tmdb_vote_count": m["vote_count"], "group": group} for m in found]
    return pd.DataFrame(rows, columns=["tmdb_id", "tmdb_vote_count", "group"]).drop_duplicates("tmdb_id")


def main(today: date | None = None) -> None:
    today = today or date.today()
    old = pd.read_csv(CANDIDATES) if CANDIDATES.exists() else pd.DataFrame(columns=COLUMNS)
    catalog = set(pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id"])["tmdb_id"])
    catalog -= set(old["tmdb_id"])          # films this step added earlier are still "ours"
    found = find()
    new = found[~found["tmdb_id"].isin(catalog) & ~found["tmdb_id"].isin(old["tmdb_id"])]
    new = new.assign(found_on=today.isoformat(), part="D")
    cand = pd.concat([old, new[COLUMNS]], ignore_index=True)
    import_module("pipeline.03_fetch_tmdb").fetch_all(sorted(new["tmdb_id"].astype(int).tolist()))
    cand.to_csv(CANDIDATES, index=False)
    log.info("new candidates this run: %d (all time: %d)", len(new), len(cand))
    write_json(PROCESSED / "widen_report.json", {
        "run_on": today.isoformat(), "new_this_run": int(len(new)), "all_time": int(len(cand)),
        "by_group": new["group"].value_counts().to_dict()})


if __name__ == "__main__":
    main()
