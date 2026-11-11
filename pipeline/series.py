"""TV series and anime: find well-known ones on TMDB and cache their details in the shape of a film.

    python -m pipeline.series        (then rerun step 5, step 12 and extend_serving; monthly_refresh.ps1 does)

MovieLens has no TV or anime ratings, so series carry no ratings: like the widened films they sit outside the
evaluation universe (models and results do not change) and are recommended through content similarity and
TMDB popularity only. The site says so on their pages.

TMDB numbers TV ids separately from film ids (the same number can be a film and a series), so a series is stored
with tmdb_id = TV_OFFSET + its TV id. normalize() reshapes a /tv/{id} response into the film shape the rest of
the pipeline reads (title, release_date, credits, certification, genres...), so the metadata gate, features,
loading and the model bundle treat it like any other film. Anime = Japanese-language animation.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm

from pipeline.common import DISCOVER_DIR, PROCESSED, TMDB_DIR, get_logger, write_json
from pipeline.tmdb import TMDB

log = get_logger("series")
CFG = yaml.safe_load((Path(__file__).parent / "catalog_config.yaml").read_text(encoding="utf-8"))["series"]
CANDIDATES = PROCESSED / "series_candidates.csv"
COLUMNS = ["tmdb_id", "tmdb_vote_count", "group", "found_on", "part"]
TV_OFFSET = 10_000_000
APPEND = "credits,keywords,content_ratings,external_ids,images"
ANIMATION = 16

# TV genres -> the site's film genres. Reality, Talk and News have no film equivalent and are dropped.
GENRES = {
    "Action & Adventure": ["Action", "Adventure"], "Animation": ["Animation"], "Comedy": ["Comedy"],
    "Crime": ["Crime"], "Documentary": ["Documentary"], "Drama": ["Drama"], "Family": ["Family"],
    "Kids": ["Family"], "Mystery": ["Mystery"], "Sci-Fi & Fantasy": ["Science Fiction", "Fantasy"],
    "Soap": ["Drama"], "War & Politics": ["War"], "Western": ["Western"],
}


def tv_id(tmdb_id: int) -> int:
    """The TV id TMDB knows a stored series by."""
    return int(tmdb_id) - TV_OFFSET


def is_anime(detail: dict) -> bool:
    kinds = {g["id"] for g in detail.get("genres", [])}
    return (detail.get("original_language") or "").lower() == "ja" and ANIMATION in kinds


def normalize(detail: dict) -> dict:
    """A /tv/{id} response in the shape of a film's detail response, plus the series fields."""
    genres = []
    for g in detail.get("genres", []):
        for name in GENRES.get(g["name"], []):
            if name not in [x["name"] for x in genres]:
                genres.append({"id": g["id"], "name": name})
    runs = detail.get("episode_run_time") or []
    last = (detail.get("last_episode_to_air") or {}).get("runtime")
    credits = detail.get("credits") or {}
    creators = [{"id": c["id"], "name": c["name"], "job": "Screenplay", "department": "Writing",
                 "profile_path": c.get("profile_path")} for c in detail.get("created_by", [])]
    ratings = [{"iso_3166_1": r["iso_3166_1"], "release_dates": [{"type": 3, "certification": r.get("rating", ""),
                                                                  "release_date": detail.get("first_air_date") or ""}]}
               for r in (detail.get("content_ratings") or {}).get("results", [])]
    companies = [*detail.get("networks", []), *detail.get("production_companies", [])]
    return {
        "id": TV_OFFSET + int(detail["id"]), "_media": "tv", "tv_id": int(detail["id"]),
        "imdb_id": (detail.get("external_ids") or {}).get("imdb_id") or None,
        "title": detail.get("name"), "original_title": detail.get("original_name"),
        "overview": detail.get("overview"), "tagline": detail.get("tagline"),
        "release_date": detail.get("first_air_date") or None,
        "runtime": (runs[0] if runs else last) or None,
        "original_language": detail.get("original_language"),
        "spoken_languages": detail.get("spoken_languages", []),
        "production_countries": [{"iso_3166_1": c} for c in detail.get("origin_country", [])],
        "poster_path": detail.get("poster_path"), "backdrop_path": detail.get("backdrop_path"),
        "production_companies": [{"name": c["name"]} for c in companies],
        "vote_count": detail.get("vote_count"), "vote_average": detail.get("vote_average"), "adult": detail.get("adult"),
        # A series that is still running or has ended has been released; one that is only planned has not.
        "status": "Released" if detail.get("status") in ("Returning Series", "Ended", "Canceled") else detail.get("status"),
        "series_status": detail.get("status"),
        "genres": genres,
        "keywords": {"keywords": (detail.get("keywords") or {}).get("results", [])},
        "credits": {"cast": credits.get("cast", []), "crew": creators},
        "release_dates": {"results": ratings}, "images": detail.get("images", {}),
        "title_type": "anime" if is_anime(detail) else "series",
        "number_of_seasons": detail.get("number_of_seasons"), "number_of_episodes": detail.get("number_of_episodes"),
    }


def _discover_tv(tmdb: TMDB, key: str, max_results: int, **params) -> list[dict]:
    out, page = [], 1
    while len(out) < max_results:
        data = tmdb.cached(DISCOVER_DIR / f"{key}_p{page}.json", "/discover/tv", page=page, **params)
        if not data or not data.get("results"):
            break
        out.extend(data["results"])
        if page >= data.get("total_pages", 1) or page >= 500:
            break
        page += 1
    return out[:max_results]


def find() -> pd.DataFrame:
    tmdb, rows = TMDB(), []

    def run(group, key, votes, **filters):
        found = _discover_tv(tmdb, key, CFG["max"], sort_by="vote_count.desc", include_adult="false",
                             **{"vote_count.gte": votes}, **filters)
        log.info("%s %s: %d series with >= %d votes", group, filters, len(found), votes)
        rows.extend({"tmdb_id": TV_OFFSET + m["id"], "tmdb_vote_count": m["vote_count"], "group": group} for m in found)

    run("anime", f"tv_anime_v{CFG['anime_min_votes']}", CFG["anime_min_votes"],
        with_genres=ANIMATION, with_original_language="ja")
    for lang, votes in CFG["languages"].items():
        run("series", f"tv_{lang}_v{votes}", votes, with_original_language=lang)
    run("series", f"tv_all_v{CFG['min_votes']}", CFG["min_votes"])
    return pd.DataFrame(rows, columns=["tmdb_id", "tmdb_vote_count", "group"]).drop_duplicates("tmdb_id")


def fetch_all(ids: list[int], workers: int = 24) -> int:
    """Cache the film-shaped detail of every series (ids are stored ids = TV_OFFSET + TV id)."""
    tmdb = TMDB(rate=18)
    todo = [i for i in ids if not (TMDB_DIR / f"{i}.json").exists()]
    log.info("%d series, %d already cached, %d to fetch", len(ids), len(ids) - len(todo), len(todo))

    def one(stored_id: int):
        d = tmdb.get(f"/tv/{tv_id(stored_id)}", language="en-US", append_to_response=APPEND,
                     include_image_language="en,null")
        write_json(TMDB_DIR / f"{stored_id}.json", normalize(d) if d else {"_status": 404})
        return d

    missing = 0
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(one, i) for i in todo]
        for f in tqdm(as_completed(futures), total=len(futures), mininterval=10):
            if f.result() is None:
                missing += 1
    return missing


def main(today: date | None = None) -> None:
    today = today or date.today()
    old = pd.read_csv(CANDIDATES) if CANDIDATES.exists() else pd.DataFrame(columns=COLUMNS)
    found = find()
    new = found[~found["tmdb_id"].isin(old["tmdb_id"])].assign(found_on=today.isoformat(), part="D")
    fetch_all(sorted(new["tmdb_id"].astype(int).tolist()))
    cand = pd.concat([old, new[COLUMNS]], ignore_index=True)
    cand.to_csv(CANDIDATES, index=False)
    log.info("new series candidates this run: %d (all time: %d)", len(new), len(cand))
    write_json(PROCESSED / "series_report.json", {
        "run_on": today.isoformat(), "new_this_run": int(len(new)), "all_time": int(len(cand)),
        "by_group": new["group"].value_counts().to_dict()})


if __name__ == "__main__":
    main()
