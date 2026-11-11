"""Feel-good and Romantic work as a mood filter on every genre page and on Discover, for films and shows."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


def test_feelgood_and_romance_filter_on_genre_pages_and_discover(test_engine):
    ids = {}
    spec = {  # key: (title_type, genres, keyword)
        "warm_film": ("movie", ["Drama", "Comedy"], None),
        "dark_film": ("movie", ["Drama", "Crime"], None),
        "warm_show": ("series", ["Drama", "Family"], None),
        "love_show": ("series", ["Drama"], "romance"),
        "love_film": ("movie", ["Drama", "Romance"], None),
        "plain_film": ("movie", ["Drama"], None),
    }
    with test_engine.begin() as conn:
        gid = {}
        for g in {x for _, gs, _ in spec.values() for x in gs}:
            gid[g] = conn.execute(text("""INSERT INTO genres (name, slug) VALUES (:n, :s)
                ON CONFLICT (name) DO UPDATE SET slug = genres.slug RETURNING id"""), {"n": g, "s": g.lower()}).scalar()
        kid = conn.execute(text("INSERT INTO keywords (name) VALUES ('romance') ON CONFLICT (name) DO UPDATE SET name = 'romance' RETURNING id")).scalar()
        for n, (key, (kind, gs, kw)) in enumerate(spec.items()):
            ids[key] = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 2015, 'en', ARRAY['US'], '/b.jpg', 8.0, 99999, :k)
                RETURNING id"""), {"t": 990300 + n, "n": f"Vibe {key}", "k": kind}).scalar()
            for g in gs:
                conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": ids[key], "g": gid[g]})
            if kw:
                conn.execute(text("INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (:m, :k)"), {"m": ids[key], "k": kid})

    def listed(c, path):
        return set(i["movie"]["id"] for i in c.get(path).json()["items"])
    try:
        with TestClient(app) as c:
            feel = listed(c, "/api/genres/drama/movies?type=all&vibe=feelgood")
            assert {ids["warm_film"], ids["warm_show"]} <= feel and not {ids["dark_film"], ids["plain_film"]} & feel
            love = listed(c, "/api/genres/drama/movies?type=all&vibe=romance")
            assert {ids["love_film"], ids["love_show"]} <= love and not {ids["warm_film"], ids["plain_film"]} & love
            # the same on Discover, and the type filter still applies
            assert listed(c, "/api/movies?type=show&vibe=romance&genre=drama") & {ids["love_show"], ids["love_film"]} == {ids["love_show"]}
            assert ids["plain_film"] in listed(c, "/api/genres/drama/movies?type=all")          # no vibe = unchanged
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": list(ids.values())})
