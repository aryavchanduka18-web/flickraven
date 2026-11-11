"""Monthly new releases: find recent films the catalog does not have yet.

    python -m pipeline.new_releases        (then rerun step 5, step 12 and extend_serving; see docs/deploy.md)

For English and every part B language, TMDB discover lists films released in the last
new_releases.lookback_months (catalog_config.yaml) with enough votes, most-voted first. Films not already in
the catalog and at least min_runtime_min long become candidates; their details are fetched like step 3.

Candidates are ADDED to data/processed/new_release_candidates.csv, never replaced, so a film found in an
earlier month stays in the catalog after it leaves the look-back window. Step 5 then adds the ones that pass
the metadata gate as part C. They have no MovieLens ratings, so ratings, splits, models and evaluation
results do not change (the same reason the franchise rule is safe).
"""
from datetime import date
from importlib import import_module
from pathlib import Path

import pandas as pd
import yaml

from pipeline.common import PROCESSED, TMDB_DIR, get_logger, read_json, write_json
from pipeline.tmdb import TMDB

log = get_logger("new_releases")
_HERE = Path(__file__).parent
CFG = yaml.safe_load((_HERE / "catalog_config.yaml").read_text(encoding="utf-8"))["new_releases"]
PART_B = yaml.safe_load((_HERE / "curated" / "language_quotas.yaml").read_text(encoding="utf-8"))["part_b"]
CANDIDATES = PROCESSED / "new_release_candidates.csv"
COLUMNS = ["tmdb_id", "tmdb_vote_count", "discover_language", "found_on", "part"]


def months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m + 1, min(d.day, 28))


def min_votes(lang: str) -> int:
    low = set(PART_B["low_volume_languages"]) | set(PART_B.get("boost_languages", []))
    return CFG["min_votes_low_volume"] if lang in low else CFG["min_votes"]


def find(today: date) -> pd.DataFrame:
    discover = import_module("pipeline.02_select_catalog").discover
    tmdb, start = TMDB(), months_back(today, CFG["lookback_months"])
    rows = []
    for lang in ["en", *PART_B["languages"]]:
        found = discover(
            tmdb, f"newrel_{lang}_{start}_{today}_v{min_votes(lang)}", CFG["max_per_language"],
            with_original_language=lang, sort_by="vote_count.desc", include_adult="false",
            **{"primary_release_date.gte": start.isoformat(), "primary_release_date.lte": today.isoformat(),
               "vote_count.gte": min_votes(lang), "with_runtime.gte": CFG["min_runtime_min"]},
        )
        log.info("%s: %d releases since %s with >= %d votes", lang, len(found), start, min_votes(lang))
        rows += [{"tmdb_id": m["id"], "tmdb_vote_count": m["vote_count"], "discover_language": lang} for m in found]
    return pd.DataFrame(rows, columns=["tmdb_id", "tmdb_vote_count", "discover_language"]).drop_duplicates("tmdb_id")


def merge(old: pd.DataFrame, found: pd.DataFrame, in_catalog: set[int], today: date) -> pd.DataFrame:
    """Earlier candidates stay as they were; films already in the catalog for another reason are skipped."""
    new = found[~found["tmdb_id"].isin(in_catalog) & ~found["tmdb_id"].isin(old["tmdb_id"])]
    new = new.assign(found_on=today.isoformat(), part="C")
    return pd.concat([old, new[COLUMNS]], ignore_index=True)


def main(today: date | None = None) -> None:
    today = today or date.today()
    old = pd.read_csv(CANDIDATES) if CANDIDATES.exists() else pd.DataFrame(columns=COLUMNS)
    catalog = set(pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id"])["tmdb_id"])
    catalog -= set(old["tmdb_id"])          # films this step added earlier are still "ours"
    cand = merge(old, find(today), catalog, today)
    added = cand[cand["found_on"] == today.isoformat()]
    import_module("pipeline.03_fetch_tmdb").fetch_all(sorted(added["tmdb_id"].astype(int).tolist()))
    cand.to_csv(CANDIDATES, index=False)
    titles = {t: (read_json(TMDB_DIR / f"{t}.json").get("title") if (TMDB_DIR / f"{t}.json").exists() else None)
              for t in added["tmdb_id"]}
    log.info("new candidates this run: %d (all time: %d)", len(added), len(cand))
    write_json(PROCESSED / "new_releases_report.json", {
        "run_on": today.isoformat(), "lookback_months": CFG["lookback_months"],
        "new_this_run": int(len(added)), "all_time": int(len(cand)),
        "by_language": added["discover_language"].value_counts().to_dict(),
        "new_list": [{"tmdb_id": int(t), "title": titles[t]} for t in added["tmdb_id"]],
    })


if __name__ == "__main__":
    main()
