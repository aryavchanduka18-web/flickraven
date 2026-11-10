"""Discover filters: release period, IMDb score, streaming service, country, and the options endpoint."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


def test_discover_filters_and_options(test_engine):
    ids = []
    with test_engine.begin() as conn:
        for n, (year, imdb, country, prov) in enumerate([(1995, 8.1, "FR", 8), (2010, 6.0, "KR", 8), (2022, 7.5, "KR", 337), (2023, None, "US", None)]):
            mid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type, imdb_rating) VALUES (:t, :n, :y, 'xx', ARRAY[:c], '/b.jpg', 8.0, 99999, 'movie', :i)
                RETURNING id"""), {"t": 990200 + n, "n": f"Filter test {n}", "y": year, "c": country, "i": imdb}).scalar()
            ids.append(mid)
            if prov:
                conn.execute(text("""INSERT INTO movie_watch_providers (movie_id, kind, provider_id, region, provider_name, fetched_on)
                    VALUES (:m, 'flatrate', :p, 'IN', :n, current_date)"""), {"m": mid, "p": prov, "n": f"Service {prov}"})
    mine = {f"Filter test {n}" for n in range(4)}

    def listed(c, qs):
        return {i["movie"]["title"] for i in c.get(f"/api/movies?sort=popular&lang=xx&{qs}").json()["items"]} & mine
    try:
        with TestClient(app) as c:
            assert listed(c, "") == mine
            assert listed(c, "year_min=2000&year_max=2022") == {"Filter test 1", "Filter test 2"}
            assert listed(c, "min_imdb=7") == {"Filter test 0", "Filter test 2"}          # no IMDb score never passes a minimum
            assert listed(c, "provider=8") == {"Filter test 0", "Filter test 1"}
            assert listed(c, "country=KR&min_imdb=7") == {"Filter test 2"}
            opts = c.get("/api/discover/options").json()
            assert any(o["code"] == "KR" for o in opts["countries"])
            assert isinstance(opts["providers"], list)
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})
