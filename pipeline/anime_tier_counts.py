"""How many real site users fall in each anime-model tier (no model change, aggregate counts only).

    python -m pipeline.anime_tier_counts --db-env DATABASE_URL

Read-only: the connection is opened with default_transaction_read_only. Counts, per user, the distinct catalog titles
the anime model knows (data/processed/anime_model_map.csv, titles with ratings in --ratings) that they rated 7+, liked
or picked in onboarding: the same count the engine uses (OnlineEngine.anime_scores). Output: users per tier
(none 0, short 1-7, mid 8-24, long 25+) and the total users; no user id or title leaves the script.
"""
import argparse
import collections

import pandas as pd
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

from pipeline.common import PROCESSED, RAW
from pipeline.mixed_home_replay import ROOT


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-env", default="DATABASE_URL", help="name of the .env entry with the database URL")
    ap.add_argument("--ratings", default=str(RAW / "anime2023" / "rating.csv"))
    a = ap.parse_args()
    m = pd.read_csv(PROCESSED / "anime_model_map.csv")
    have = set(pd.read_csv(a.ratings, usecols=["anime_id"])["anime_id"].unique())
    known = set(m[m["sid"].isin(have)]["tmdb_id"].astype(int))
    url = dotenv_values(ROOT / ".env")[a.db_env].strip()
    db = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    sql = """SELECT x.user_id, mv.tmdb_id FROM (
               SELECT user_id, movie_id FROM ratings WHERE rating >= 7
               UNION SELECT user_id, movie_id FROM reactions WHERE value > 0
               UNION SELECT user_id, movie_id FROM onboarding_picks) x
             JOIN movies mv ON mv.id = x.movie_id"""
    with db.connect() as c:
        users = c.execute(text("SELECT count(*) FROM users")).scalar()
        liked = collections.defaultdict(set)
        for u, t in c.execute(text(sql)):
            if t is not None and int(t) in known:
                liked[u].add(int(t))
    tier = lambda n: "short 1-7" if n <= 7 else "mid 8-24" if n <= 24 else "long 25+"
    counts = collections.Counter(tier(len(v)) for v in liked.values())
    counts["none 0"] = users - sum(counts.values())
    print({"users": users, **dict(sorted(counts.items()))})


if __name__ == "__main__":
    main()
