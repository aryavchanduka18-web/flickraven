"""Step 5: metadata gate, final catalog cut, cleaning, dominant colors, per-language report.

Outputs (data/processed/): catalog_ids.csv, movies_clean.parquet, credits_clean.parquet,
metadata_report.json.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import yaml
from tqdm import tqdm

from pipeline.catalog import gate_failures, original_gate_failures, overview_words, parse_credits, parse_movie
from pipeline.colors import dominant_color
from pipeline.audit import write_catalog_audit
from pipeline.common import IMAGES_DIR, PROCESSED, TMDB_DIR, get_logger, read_json, write_json
from pipeline.selection import hollywood_rule, relaxed_additions, select
from pipeline.tmdb import TMDB

log = get_logger("05_clean")
_HERE = __import__("pathlib").Path(__file__).parent
CFG = yaml.safe_load((_HERE / "curated" / "language_quotas.yaml").read_text(encoding="utf-8"))
CFG["hollywood"] = yaml.safe_load((_HERE / "catalog_config.yaml").read_text(encoding="utf-8"))["hollywood"]
MIN_LANGUAGE_FILMS = 150


def load_candidates() -> tuple[pd.DataFrame, dict]:
    """One gated row per (candidate, part).

    Parts A, B and C keep their original rule: a film found by several of those routes keeps only
    its highest-priority part (A, then B, then C). Part D rows are kept separately, so a famous US
    film that did not make A/B/C (for example too few MovieLens ratings) can still enter as D.
    """
    cand = pd.read_csv(PROCESSED / "catalog_candidates.csv")
    abc = cand[cand["part"] != "D"].copy()
    abc["prio"] = abc["part"].map({"A": 0, "B": 1, "C": 2})
    abc = abc.sort_values("prio").drop_duplicates("tmdb_id").drop(columns="prio")
    cand = pd.concat([abc, cand[cand["part"] == "D"].drop_duplicates("tmdb_id")], ignore_index=True)
    return gate(cand)


def load_franchise_candidates() -> tuple[pd.DataFrame, dict]:
    """Missing parts of catalog franchises (pipeline/franchises.py), gated like the other candidates.
    Kept apart from the main pool so the original selection cannot change."""
    path = PROCESSED / "franchise_candidates.csv"
    if not path.exists():
        return pd.DataFrame(columns=["tmdb_id", "passed", "status", "release_date", "part", "found_on"]), {}
    return gate(pd.read_csv(path).drop(columns=["franchise"], errors="ignore"))


def load_widen_candidates() -> tuple[pd.DataFrame, dict]:
    """Well-known films found by pipeline/widen_catalog.py, gated like the other candidates and kept apart
    from the main pool, so the original selection cannot change."""
    path = PROCESSED / "widen_candidates.csv"
    if not path.exists():
        return pd.DataFrame(columns=["tmdb_id", "passed", "status", "release_date", "part", "found_on"]), {}
    return gate(pd.read_csv(path)[["tmdb_id", "tmdb_vote_count", "part", "found_on"]])


def load_series_candidates() -> tuple[pd.DataFrame, dict]:
    """TV series and anime found by pipeline/series.py (stored with tmdb_id = 10,000,000 + TV id), gated like
    the other candidates and kept apart from the main pool, so the original selection cannot change."""
    path = PROCESSED / "series_candidates.csv"
    if not path.exists():
        return pd.DataFrame(columns=["tmdb_id", "passed", "status", "release_date", "part", "found_on"]), {}
    return gate(pd.read_csv(path)[["tmdb_id", "tmdb_vote_count", "part", "found_on"]])


def load_new_release_candidates() -> tuple[pd.DataFrame, dict]:
    """Recent films found by pipeline/new_releases.py, gated like the other candidates. Kept apart from
    the main pool, like the franchise candidates, so the original selection cannot change."""
    path = PROCESSED / "new_release_candidates.csv"
    if not path.exists():
        return pd.DataFrame(columns=["tmdb_id", "passed", "status", "release_date", "part", "found_on"]), {}
    return gate(pd.read_csv(path)[["tmdb_id", "tmdb_vote_count", "part", "found_on"]])


def gate(cand: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if cand.empty:          # e.g. a monthly run that found no new releases: nothing to gate, nothing to add
        return cand.assign(passed=pd.Series(dtype=bool), status=pd.Series(dtype=object),
                           release_date=pd.Series(dtype=object)), {}
    details, rows = {}, []
    for tmdb_id in cand["tmdb_id"].unique():
        path = TMDB_DIR / f"{tmdb_id}.json"
        detail = read_json(path) if path.exists() else {"_status": "missing"}
        if "_status" in detail:
            rows.append({"tmdb_id": tmdb_id, "reasons": ["not_found_on_tmdb"], "original_reasons": ["not_found_on_tmdb"],
                         "us_production": False, "in_collection": False})
            continue
        details[tmdb_id] = detail
        reasons, original = gate_failures(detail), original_gate_failures(detail)
        if detail.get("adult"):
            reasons.append("adult")
            original.append("adult")
        release = detail.get("release_date") or None
        rows.append({"tmdb_id": tmdb_id, "reasons": reasons, "original_reasons": original, "title": detail.get("title"),
                     "release_date": release, "year": int(release[:4]) if release else None,
                     "status": detail.get("status"),
                     "original_language": (detail.get("original_language") or "").lower(),
                     "vote_count_detail": detail.get("vote_count"),
                     "us_production": any(c.get("iso_3166_1") == "US" for c in detail.get("production_countries", [])),
                     "in_collection": bool(detail.get("belongs_to_collection"))})
    gated = cand.merge(pd.DataFrame(rows), on="tmdb_id", how="left")
    gated["passed"] = gated["reasons"].map(len) == 0
    gated["original_passed"] = gated["original_reasons"].map(len) == 0
    # Detail vote counts are fresher than the discover listings.
    gated["tmdb_vote_count"] = gated["vote_count_detail"].fillna(gated["tmdb_vote_count"])
    gated["year"] = gated["year"].astype("Float64")
    return gated, details

def compute_colors(movies: pd.DataFrame) -> list[str | None]:
    tmdb = TMDB(rate=40)

    def one(row) -> str | None:
        if isinstance(row.backdrop_path, str) and row.backdrop_path:  # missing = NaN
            size, path = "w300", row.backdrop_path
        else:
            size, path = "w342", row.poster_path
        dest = IMAGES_DIR / size / path.lstrip("/")
        local = tmdb.download_image(size, path, dest)
        try:
            return dominant_color(local) if local else None
        except OSError:
            return None

    with ThreadPoolExecutor(8) as pool:
        return list(tqdm(pool.map(one, movies.itertuples(index=False)), total=len(movies), mininterval=10))


def language_report(gated: pd.DataFrame, movies: pd.DataFrame) -> dict:
    report = {}
    for lang, grp in movies.groupby("original_language"):
        n = len(grp)
        report[lang] = {
            "films": n,
            "by_part": grp["catalog_part"].value_counts().to_dict(),
            "pct_backdrop": round(100 * grp["backdrop_path"].notna().mean(), 1),
            "pct_logo": round(100 * grp["logo_path"].notna().mean(), 1),
            "pct_tagline": round(100 * grp["tagline"].notna().mean(), 1),
            "pct_keywords": round(100 * (grp["keywords"].map(len) > 0).mean(), 1),
            "pct_certification": round(100 * grp["certification"].notna().mean(), 1),
            "pct_runtime": round(100 * grp["runtime_min"].notna().mean(), 1),
            "median_overview_words": int(grp["overview"].map(overview_words).median()),
            "thin_text_films": int(grp["thin_text"].sum()),
            "onboarding_eligible": n >= MIN_LANGUAGE_FILMS,
        }
    dropped = relevant_drops(gated)
    for lang, grp in dropped.groupby(dropped["original_language"].fillna("unknown")):
        entry = report.setdefault(lang, {"films": 0, "onboarding_eligible": False})
        entry["dropped_by_gate"] = int(len(grp))
        entry["drop_reasons"] = dict(Counter(r for rs in grp["reasons"] for r in rs).most_common())
    return dict(sorted(report.items(), key=lambda kv: -kv[1]["films"]))


def relevant_drops(gated: pd.DataFrame) -> pd.DataFrame:
    """Films that failed the gate and would otherwise have been eligible: every A/B/C candidate,
    plus the part-D pool films that are US productions meeting the Hollywood rule."""
    is_d = gated["part"] == "D"
    d_relevant = is_d & gated["us_production"].fillna(False).astype(bool) & hollywood_rule(gated, CFG["hollywood"])
    return gated[~gated["passed"] & (~is_d | d_relevant)].drop_duplicates("tmdb_id")


def main() -> None:
    summary = read_json(PROCESSED / "catalog_candidates_summary.json")
    window = summary["part_c_window"]
    gated, details = load_candidates()
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    # First the cut with the original gate (unchanged from the first build: same evaluation backbone),
    # then the films that only the relaxed gate lets in, with that cut's thresholds.
    base, chosen = select(gated.assign(passed=gated["original_passed"]), CFG, start, end)
    extra = relaxed_additions(gated, base, chosen, CFG, start, end)
    catalog = pd.concat([base.assign(relaxed_gate=False), extra.assign(relaxed_gate=True)], ignore_index=True)
    # Then the franchise rule: missing parts of catalog collections that pass the relaxed gate, as part D.
    fr_gated, fr_details = load_franchise_candidates()
    details |= fr_details
    fr = fr_gated[fr_gated["passed"].fillna(False).astype(bool) & (fr_gated["status"] == "Released")
                  & (pd.to_datetime(fr_gated["release_date"]).dt.date <= end)
                  & ~fr_gated["tmdb_id"].isin(catalog["tmdb_id"])].drop_duplicates("tmdb_id")
    catalog = pd.concat([catalog.assign(franchise_rule=False, added_on=None),
                         fr.assign(part="D", ml_movie_id=pd.NA, relaxed_gate=False, franchise_rule=True, added_on=None)],
                        ignore_index=True)
    # Then the wider catalog (pipeline/widen_catalog.py), as part D.
    wd_gated, wd_details = load_widen_candidates()
    details |= wd_details
    wd = wd_gated[wd_gated["passed"].fillna(False).astype(bool) & (wd_gated["status"] == "Released")
                  & (pd.to_datetime(wd_gated["release_date"]).dt.date <= date.today())
                  & ~wd_gated["tmdb_id"].isin(catalog["tmdb_id"])].drop_duplicates("tmdb_id")
    catalog = pd.concat([catalog, wd.assign(part="D", ml_movie_id=pd.NA, relaxed_gate=False, franchise_rule=False, added_on=wd["found_on"])],
                        ignore_index=True)
    log.info("wider catalog added %d", len(wd))
    # Then TV series and anime (pipeline/series.py), as part D. "~series" sorts after the widened films of the same
    # run date, so they get a content stage of their own (see catalog_stage).
    sr_gated, sr_details = load_series_candidates()
    details |= sr_details
    sr = sr_gated[sr_gated["passed"].fillna(False).astype(bool) & (sr_gated["status"] == "Released")
                  & ~sr_gated["tmdb_id"].isin(catalog["tmdb_id"])].drop_duplicates("tmdb_id")
    catalog = pd.concat([catalog, sr.assign(part="D", ml_movie_id=pd.NA, relaxed_gate=False, franchise_rule=False,
                                            added_on=sr["found_on"] + "~series")], ignore_index=True)
    log.info("series and anime added %d", len(sr))
    # Then the monthly new releases (pipeline/new_releases.py), as part C, after the build date. "~~new" sorts after
    # the widened films ("<date>") and the series ("<date>~series") of the same run date, so they get a stage of their
    # own and never move the content columns of films added earlier (see catalog_stage).
    nr_gated, nr_details = load_new_release_candidates()
    details |= nr_details
    nr = nr_gated[nr_gated["passed"].fillna(False).astype(bool) & (nr_gated["status"] == "Released")
                  & (pd.to_datetime(nr_gated["release_date"]).dt.date <= date.today())
                  & ~nr_gated["tmdb_id"].isin(catalog["tmdb_id"])].drop_duplicates("tmdb_id")
    catalog = pd.concat([catalog, nr.assign(part="C", ml_movie_id=pd.NA, relaxed_gate=False, franchise_rule=False, added_on=nr["found_on"] + "~~new")],
                        ignore_index=True)
    log.info("new releases added %d", len(nr))
    log.info("selected %s with %s; relaxed gate added %s; franchise rule added %d", base["part"].value_counts().to_dict(),
             chosen, extra["part"].value_counts().to_dict(), len(fr))

    movies = pd.DataFrame([parse_movie(details[t]) for t in catalog["tmdb_id"]])
    movies = movies.merge(catalog[["tmdb_id", "part", "ml_movie_id", "relaxed_gate", "franchise_rule", "added_on"]]
                          .rename(columns={"part": "catalog_part"}), on="tmdb_id")
    movies["ml_movie_id"] = movies["ml_movie_id"].astype("Int64")
    # Same IMDb id under two TMDB ids is a duplicate: keep the first (highest-priority part).
    has_imdb = movies["imdb_id"].notna()
    movies = pd.concat([movies[has_imdb].drop_duplicates("imdb_id"), movies[~has_imdb]], ignore_index=True)
    movies["thin_text"] = (movies["overview"].map(overview_words) < 40) | (movies["keywords"].map(len) == 0)

    log.info("computing dominant colors for %d films", len(movies))
    movies["dominant_color"] = compute_colors(movies)

    credits = pd.DataFrame([row for t in movies["tmdb_id"] for row in parse_credits(details[t])])
    movies.to_parquet(PROCESSED / "movies_clean.parquet", index=False)
    credits.to_parquet(PROCESSED / "credits_clean.parquet", index=False)
    movies[["tmdb_id", "catalog_part", "ml_movie_id", "imdb_id", "relaxed_gate", "franchise_rule", "added_on"]].to_csv(PROCESSED / "catalog_ids.csv", index=False)

    dropped = relevant_drops(gated)
    write_json(PROCESSED / "metadata_report.json", {
        "build_date": summary["build_date"],
        "part_c_window": window,
        "chosen_thresholds": chosen,
        "catalog_size": len(movies),
        "by_part": movies["catalog_part"].value_counts().to_dict(),
        "added_by_relaxed_gate": movies.loc[movies["relaxed_gate"], "catalog_part"].value_counts().to_dict(),
        "added_by_franchise_rule": int(movies["franchise_rule"].sum()),
        "added_as_new_releases": int(len(nr)),
        "part_b_by_language": movies[movies["catalog_part"] == "B"]["original_language"].value_counts().to_dict(),
        "candidates": int(gated["tmdb_id"].nunique()),
        "part_notes": {"A": "MovieLens films", "B": "curated international", "C": "new & notable",
                       "D": "Hollywood enrichment: famous US productions missing from A/B/C"},
        "part_a_gate_pass_at_thresholds": {
            str(t): int(((gated["part"] == "A") & gated["original_passed"] & (gated["ml_rating_count"] >= t)).sum())
            for t in (50, 100, 154)},
        "dropped_by_gate": int(len(dropped)),
        "drop_reasons": dict(Counter(r for rs in dropped["reasons"] for r in rs).most_common()),
        "onboarding_languages": sorted(movies["original_language"].value_counts().loc[lambda s: s >= MIN_LANGUAGE_FILMS].index),
        "per_language": language_report(gated, movies),
    })
    write_catalog_audit(gated, movies, CFG["hollywood"], date.fromisoformat(window["end"]))
    log.info("catalog: %d films; dropped by gate: %d", len(movies), len(dropped))


if __name__ == "__main__":
    main()