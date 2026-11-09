"""Where to watch: which streaming services carry each film (TMDB watch/providers, data by JustWatch).

    python -m pipeline.watch_providers            fetch for every catalog film, then load the local database
    python -m pipeline.watch_providers --load     only load the last fetch into the local database

TMDB answers /movie/{id}/watch/providers with every country at once. For each film we keep the services in
watch_providers.region (India); only when TMDB lists none there do we keep the fallback region (US), and the
page says which country it shows. Nothing is guessed: a film with no services in either region has no rows.

Responses are cached per month (data/raw/tmdb_providers/<YYYY-MM>/<id>.json), so a monthly refresh fetches
fresh data once and a rerun in the same month costs nothing. TMDB asks that JustWatch is credited wherever
this data is shown; the movie page does that.
"""
import argparse
from datetime import date
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import Engine, create_engine, text

from pipeline.common import PROCESSED, RAW, env, get_logger
from pipeline.tmdb import TMDB

log = get_logger("watch_providers")
CFG = yaml.safe_load((Path(__file__).parent / "catalog_config.yaml").read_text())["watch_providers"]
CACHE = RAW / "tmdb_providers"
OUT = PROCESSED / "watch_providers.parquet"
KINDS = ("flatrate", "free", "ads", "rent", "buy")
COLUMNS = ["tmdb_id", "region", "kind", "provider_id", "provider_name", "logo_path", "display_priority", "link"]


def pick(tmdb_id: int, response: dict | None, region: str = CFG["region"],
         fallback: str = CFG["fallback_region"]) -> list[dict]:
    """Rows for one film: every service in `region`, or in `fallback` when `region` has none."""
    results = (response or {}).get("results") or {}
    for r in (region, fallback):
        country = results.get(r) or {}
        rows = [{"tmdb_id": tmdb_id, "region": r, "kind": kind, "provider_id": p["provider_id"],
                 "provider_name": p["provider_name"], "logo_path": p.get("logo_path"),
                 "display_priority": p.get("display_priority"), "link": country.get("link")}
                for kind in KINDS for p in country.get(kind) or []]
        if rows:
            # A service listed twice under one kind (TMDB does this now and then) is kept once.
            return list({(x["kind"], x["provider_id"]): x for x in rows}.values())
    return []


def fetch(today: date) -> pd.DataFrame:
    ids = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id"])["tmdb_id"].astype(int)
    tmdb, folder = TMDB(), CACHE / today.strftime("%Y-%m")
    rows = []
    for n, tmdb_id in enumerate(ids, 1):
        rows += pick(tmdb_id, tmdb.cached(folder / f"{tmdb_id}.json", f"/movie/{tmdb_id}/watch/providers"))
        if n % 1000 == 0:
            log.info("%d / %d films", n, len(ids))
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["fetched_on"] = today
    df.to_parquet(OUT, index=False)
    films = df.groupby("region")["tmdb_id"].nunique().to_dict()
    log.info("services found for %s films (by region: %s) out of %d", df["tmdb_id"].nunique(), films, len(ids))
    return df


def load(engine: Engine, df: pd.DataFrame) -> int:
    """Replace all stored services with this fetch. Films are matched by TMDB id, so this works on the
    laptop and on the hosted database alike."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TEMP TABLE wp_in (tmdb_id int, region char(2), kind text, provider_id int, "
                          "provider_name text, logo_path text, display_priority int, link text, fetched_on date) "
                          "ON COMMIT DROP"))
        records = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in df.to_dict("records")]
        for i in range(0, len(records), 5000):
            conn.execute(text("INSERT INTO wp_in VALUES (:tmdb_id, :region, :kind, :provider_id, :provider_name, "
                              ":logo_path, :display_priority, :link, :fetched_on)"), records[i:i + 5000])
        # Every film is replaced, so a film that left all services loses its old rows.
        conn.execute(text("DELETE FROM movie_watch_providers"))
        n = conn.execute(text("""
            INSERT INTO movie_watch_providers (movie_id, kind, provider_id, region, provider_name, logo_path,
                                               display_priority, link, fetched_on)
            SELECT m.id, w.kind, w.provider_id, w.region, w.provider_name, w.logo_path, w.display_priority,
                   w.link, w.fetched_on
            FROM wp_in w JOIN movies m ON m.tmdb_id = w.tmdb_id""")).rowcount
    log.info("stored %d where-to-watch rows", n)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="load the last fetch without calling TMDB")
    a = ap.parse_args()
    df = pd.read_parquet(OUT) if a.load else fetch(date.today())
    engine = create_engine(env("DATABASE_URL"))
    load(engine, df)
    engine.dispose()


if __name__ == "__main__":
    main()
