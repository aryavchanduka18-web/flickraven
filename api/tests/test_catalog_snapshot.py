"""The catalogue snapshot (shipped in the model bundle) must give the engine exactly what the full query gives,
and must be ignored when it no longer matches the database."""
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import recommender as rec


def _seed(conn):
    g = conn.execute(text("INSERT INTO genres (name, slug) VALUES ('SnapGenre', 'snapgenre') ON CONFLICT (name) DO UPDATE SET slug = genres.slug RETURNING id")).scalar()
    k = conn.execute(text("INSERT INTO keywords (name) VALUES ('snapkw') ON CONFLICT (name) DO UPDATE SET name = 'snapkw' RETURNING id")).scalar()
    mid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
        popularity_score, tmdb_vote_count, title_type) VALUES (990900, 'Snap Film', 2020, 'en', ARRAY['US'], '/b.jpg', 3.0, 500, 'movie')
        RETURNING id""")).scalar()
    conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": mid, "g": g})
    conn.execute(text("INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (:m, :k)"), {"m": mid, "k": k})
    return mid


def test_snapshot_matches_full_query_and_is_ignored_when_stale(test_engine, tmp_path, monkeypatch):
    with test_engine.begin() as conn:
        mid = _seed(conn)
    try:
        monkeypatch.setattr(rec, "MODELS", tmp_path)
        with Session(test_engine) as db:
            full = rec._catalog_from_sql(db)
            assert rec.build_snapshot(db, tmp_path / rec.SNAPSHOT) == len(full)
            fast = rec._catalog_frame(db)
        cols = ["id", "tmdb_id", "title", "original_language", "year", "catalog_part", "title_type", "popularity",
                "votes", "genres", "keywords", "has_award"]
        a = full[cols].sort_values("tmdb_id").reset_index(drop=True)
        b = fast[cols].sort_values("tmdb_id").reset_index(drop=True)
        a["genres"], a["keywords"] = a["genres"].map(list), a["keywords"].map(list)
        b["genres"], b["keywords"] = b["genres"].map(list), b["keywords"].map(list)
        a["has_award"], b["has_award"] = a["has_award"].fillna(False).astype(bool), b["has_award"].astype(bool)
        pd.testing.assert_frame_equal(a, b, check_dtype=False)
        row = b[b["tmdb_id"] == 990900].iloc[0]
        assert row["genres"] == ["SnapGenre"] and row["keywords"] == ["snapkw"]

        # a title added after the snapshot was made: the snapshot is not trusted, the full query runs
        with test_engine.begin() as conn:
            conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (990901, 'Newer Film', 2021, 'en', ARRAY['US'], '/b.jpg', 1.0, 10, 'movie')"""))
        with Session(test_engine) as db:
            assert 990901 in set(rec._catalog_frame(db)["tmdb_id"])
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE tmdb_id IN (990900, 990901)"))
