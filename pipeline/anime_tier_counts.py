"""How many real site users fall in each anime-model tier (no model change, aggregate counts only).

    python -m pipeline.anime_tier_counts --model work/anime-rank-eval-2023/anime_model.json --db-env DATABASE_URL

Read-only: the connection is opened with default_transaction_read_only. Uses the site's own rules end to end, so the
count is the engine's count:
- catalog rows: artifacts/models/content_rows.parquet joined with the database's movies, in the engine's row order
  (api recommender.load_engine);
- the model: the given model file read by the engine's reader (anime_model_file.parse, the same as the site);
- each person's liked anime: their current ratings, likes and onboarding picks turned into the engine's input
  (OnlineEngine.anime_liked: rated 7+, liked or picked; one entry per title);
- known: anime_model_file.known_inputs, the rule OnlineEngine.anime_scores uses to pick the tier.
Output: users per tier (none 0, short 1-7, mid 8-24, long 25+) and the total; no user id or title leaves the script.
"""
import argparse
import collections
import sys
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

from pipeline.common import ARTIFACTS, ROOT

MODELS = ARTIFACTS / "models"      # same folder as pipeline.models_io.MODELS, without its model-library imports

sys.path.insert(0, str(ROOT / "engine"))
from cinematch_engine import anime_model_file  # noqa: E402
from cinematch_engine.online import ANIME_MID_MAX, ANIME_SHORT_MAX, OnlineEngine, UserState  # noqa: E402


def tier_of(n: int) -> str:
    if n == 0:
        return "none 0"
    return "short 1-7" if n <= ANIME_SHORT_MAX else "mid 8-24" if n <= ANIME_MID_MAX else "long 25+"


def main() -> None:
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="the anime model file to count against (built by pipeline.anime_model)")
    ap.add_argument("--db-env", default="DATABASE_URL", help="name of the .env entry with the database URL")
    a = ap.parse_args()
    url = dotenv_values(ROOT / ".env")[a.db_env].strip()
    db = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    with db.connect() as c:
        movies = pd.DataFrame(c.execute(text("SELECT id, tmdb_id FROM movies")).mappings().all())
        rows = pd.read_parquet(MODELS / "content_rows.parquet")
        movies = rows.merge(movies, on="tmdb_id", how="inner").sort_values("row").reset_index(drop=True)
        row_of = {int(m): i for i, m in enumerate(movies["id"])}
        sims = anime_model_file.parse(json.loads(Path(a.model).read_text(encoding="utf-8")), movies["tmdb_id"].tolist())
        users = [u for (u,) in c.execute(text("SELECT id FROM users"))]
        st = collections.defaultdict(UserState)
        for u, m, r in c.execute(text("SELECT user_id, movie_id, rating FROM ratings")):
            if m in row_of:
                st[u].ratings[row_of[m]] = float(r)
        for u, m, v in c.execute(text("SELECT user_id, movie_id, value FROM reactions")):
            if m in row_of:
                (st[u].likes if v > 0 else st[u].dislikes).add(row_of[m])
        for u, m in c.execute(text("SELECT user_id, movie_id FROM onboarding_picks")):
            if m in row_of:
                st[u].picks.add(row_of[m])
    # anime_liked reads only the state, not the engine; called unbound so no full engine has to load here
    counts = collections.Counter(
        tier_of(len(anime_model_file.known_inputs(sims, OnlineEngine.anime_liked(None, st[u])))) for u in users)
    print({"users": len(users), **dict(sorted(counts.items()))})


if __name__ == "__main__":
    main()
