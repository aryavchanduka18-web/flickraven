"""Movie page "where to watch": services stored by pipeline/watch_providers.py, none invented."""
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from pipeline.catalog import parse_movie
from pipeline.loader import load_catalog
from pipeline.tests.fixtures import good
from pipeline.watch_providers import load

FILMS = [(920001, "Streaming Film"), (920002, "Nowhere Film")]


@pytest.fixture(scope="module")
def client(test_engine):
    details = [good(id=t, title=title, original_title=title, imdb_id=f"tt{t}", credits={"cast": [], "crew": []})
               for t, title in FILMS]
    movies = pd.DataFrame([parse_movie(d) for d in details])
    movies["catalog_part"] = "B"
    movies["ml_movie_id"] = pd.array([None] * len(movies), dtype="Int64")
    movies["dominant_color"] = "#336699"
    credits = pd.DataFrame(columns=["tmdb_id", "tmdb_person_id", "name", "profile_path", "role", "character", "credit_order"])
    load_catalog(test_engine, movies, credits, pd.DataFrame(columns=["tmdb_id"]), pd.DataFrame(), prune=False)
    with TestClient(app) as c:
        yield c


def movie_id(engine, tmdb_id: int) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT id FROM movies WHERE tmdb_id = :t"), {"t": tmdb_id}).scalar_one()


def test_movie_page_shows_stored_services_and_nothing_otherwise(client, test_engine):
    rows = [{"tmdb_id": 920001, "region": "IN", "kind": kind, "provider_id": pid, "provider_name": name,
             "logo_path": "/n.png", "display_priority": pid, "link": "https://www.themoviedb.org/movie/920001/watch?locale=IN",
             "fetched_on": date(2026, 11, 1)} for kind, pid, name in [("flatrate", 8, "Netflix"), ("rent", 2, "Apple TV")]]
    assert load(test_engine, pd.DataFrame(rows)) == 2
    watch = client.get(f"/api/movies/{movie_id(test_engine, 920001)}").json()["watch"]
    assert watch["region"] == "IN" and watch["updated"] == "2026-11-01"
    assert watch["providers"] == {"flatrate": [{"name": "Netflix", "logo": "/n.png"}], "rent": [{"name": "Apple TV", "logo": "/n.png"}]}
    assert client.get(f"/api/movies/{movie_id(test_engine, 920002)}").json()["watch"] is None
    # A later fetch replaces the old one: a film that left every service has no rows left.
    assert load(test_engine, pd.DataFrame(rows[:0], columns=list(rows[0]))) == 0
    assert client.get(f"/api/movies/{movie_id(test_engine, 920001)}").json()["watch"] is None
