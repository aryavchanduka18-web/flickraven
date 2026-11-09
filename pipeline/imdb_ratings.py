"""IMDb ratings for display: IMDb's own score and vote count for every catalog film that has an IMDb id.

    python -m pipeline.imdb_ratings            download this month's file, then load the local database
    python -m pipeline.imdb_ratings --load     only load the last download into the local database

Source: IMDb's free dataset title.ratings.tsv.gz (https://datasets.imdbws.com, columns tconst, averageRating,
numVotes), matched to our films by imdb_id. No scraping, no API key. IMDb licenses this file for personal
and non-commercial use only; see docs/decisions-log.md. The site shows it labelled "IMDb" and
IMDB_RATINGS=false (API setting) hides it everywhere. Models, sorting and filters never use it.

The file is cached per month (data/raw/imdb/<YYYY-MM>/), so the monthly refresh downloads it once.
"""
import argparse
from datetime import date

import httpx
import pandas as pd
from sqlalchemy import Engine, create_engine, text

from pipeline.common import PROCESSED, RAW, env, get_logger

log = get_logger("imdb_ratings")
URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
OUT = PROCESSED / "imdb_ratings.parquet"


def download(today: date):
    dest = RAW / "imdb" / today.strftime("%Y-%m") / "title.ratings.tsv.gz"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        with httpx.stream("GET", URL, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        tmp.replace(dest)
    return dest


def match(ratings: pd.DataFrame, imdb_ids: pd.Series) -> pd.DataFrame:
    """Rows of IMDb's file for our films: imdb_id, imdb_rating (1.0-10.0), imdb_votes."""
    r = ratings.rename(columns={"tconst": "imdb_id", "averageRating": "imdb_rating", "numVotes": "imdb_votes"})
    r = r[r["imdb_id"].isin(set(imdb_ids.dropna()))]
    return r[["imdb_id", "imdb_rating", "imdb_votes"]].astype({"imdb_rating": float, "imdb_votes": int})


def fetch(today: date) -> pd.DataFrame:
    ratings = pd.read_csv(download(today), sep="\t", dtype={"tconst": str}, na_values=r"\N")
    ids = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["imdb_id"])["imdb_id"]
    df = match(ratings, ids)
    df.to_parquet(OUT, index=False)
    log.info("IMDb ratings for %d of %d films with an IMDb id", len(df), ids.notna().sum())
    return df


def load(engine: Engine, df: pd.DataFrame) -> int:
    """Set imdb_rating and imdb_votes by IMDb id; films missing from this file are cleared, never kept stale."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TEMP TABLE imdb_in (imdb_id text PRIMARY KEY, rating numeric(3,1), votes int) "
                          "ON COMMIT DROP"))
        rows = [{"i": r.imdb_id, "r": float(r.imdb_rating), "v": int(r.imdb_votes)} for r in df.itertuples()]
        for k in range(0, len(rows), 5000):
            conn.execute(text("INSERT INTO imdb_in VALUES (:i, :r, :v)"), rows[k:k + 5000])
        n = conn.execute(text("""UPDATE movies m SET imdb_rating = i.rating, imdb_votes = i.votes
                                 FROM imdb_in i WHERE i.imdb_id = m.imdb_id""")).rowcount
        conn.execute(text("""UPDATE movies m SET imdb_rating = NULL, imdb_votes = NULL
                             WHERE m.imdb_rating IS NOT NULL
                               AND NOT EXISTS (SELECT 1 FROM imdb_in i WHERE i.imdb_id = m.imdb_id)"""))
    log.info("stored IMDb ratings for %d films", n)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="load the last download without fetching")
    a = ap.parse_args()
    df = pd.read_parquet(OUT) if a.load else fetch(date.today())
    engine = create_engine(env("DATABASE_URL"))
    load(engine, df)
    engine.dispose()


if __name__ == "__main__":
    main()
