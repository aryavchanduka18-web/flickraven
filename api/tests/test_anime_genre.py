"""Anime (Japanese animation, TV and films) is its own genre next to Animation, which keeps the rest."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


def test_anime_is_japanese_animation_and_animation_is_the_rest(test_engine):
    ids = {}
    with test_engine.begin() as conn:
        gid = conn.execute(text("""INSERT INTO genres (name, slug) VALUES ('Animation', 'animation')
            ON CONFLICT (name) DO UPDATE SET slug = 'animation' RETURNING id""")).scalar()
        for n, (kind, lang) in enumerate([("movie", "ja"), ("movie", "en"), ("anime", "ja"), ("series", "ja")]):
            key = f"{kind}-{lang}"
            ids[key] = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 2015, :l, ARRAY['JP'], '/b.jpg', 8.0, 99999, :k)
                RETURNING id"""), {"t": 990100 + n, "n": f"Test {key}", "l": lang, "k": kind}).scalar()
            conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": ids[key], "g": gid})
    jp_film, us_film, jp_tv, jp_series = ids["movie-ja"], ids["movie-en"], ids["anime-ja"], ids["series-ja"]

    def listed(c, path):
        return [i["movie"]["id"] for i in c.get(path).json()["items"]]
    try:
        with TestClient(app) as c:
            body = c.get("/api/genres").json()["genres"]
            by = {g["slug"]: g for g in body}
            assert by["anime"]["name"] == "Anime" and by["anime"]["films"] >= 2           # Japanese film + Japanese TV anime
            assert by["animation"]["films"] >= 1
            names = [g["name"] for g in body]
            assert names == sorted(names)                                                  # Anime sits beside Animation
            anime = listed(c, "/api/genres/anime/movies")
            assert jp_film in anime and jp_tv in anime and us_film not in anime and jp_series not in anime
            assert c.get("/api/genres/anime/movies").json()["genre"] == "Anime"
            animation = listed(c, "/api/genres/animation/movies")
            assert us_film in animation and jp_film not in animation and jp_tv not in animation
            assert jp_film in listed(c, "/api/movies?genre=anime&type=all") and jp_film not in listed(c, "/api/movies?genre=animation")
            assert jp_tv in listed(c, "/api/movies?genre=anime&type=anime") and us_film not in listed(c, "/api/movies?genre=anime&type=anime")
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": list(ids.values())})


def test_media_type_filters_on_every_genre_page(test_engine):
    """All = films and shows, Movies = films only, Shows = TV only (also for Anime), on genre pages too."""
    ids = {}
    with test_engine.begin() as conn:
        gid = conn.execute(text("""INSERT INTO genres (name, slug) VALUES ('Animation', 'animation')
            ON CONFLICT (name) DO UPDATE SET slug = 'animation' RETURNING id""")).scalar()
        for n, (kind, lang) in enumerate([("movie", "ja"), ("anime", "ja"), ("series", "en"), ("movie", "en")]):
            key = f"{kind}-{lang}"
            ids[key] = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 2015, :l, ARRAY['JP'], '/b.jpg', 8.0, 99999, :k)
                RETURNING id"""), {"t": 990200 + n, "n": f"Type {key}", "l": lang, "k": kind}).scalar()
            conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": ids[key], "g": gid})
    film_ja, tv_ja, tv_en, film_en = ids["movie-ja"], ids["anime-ja"], ids["series-en"], ids["movie-en"]

    def listed(c, path):
        return [i["movie"]["id"] for i in c.get(path).json()["items"]]
    try:
        with TestClient(app) as c:
            both = listed(c, "/api/genres/anime/movies")
            assert film_ja in both and tv_ja in both
            assert listed(c, "/api/genres/anime/movies?type=movie") and tv_ja not in listed(c, "/api/genres/anime/movies?type=movie")
            shows = listed(c, "/api/genres/anime/movies?type=show")
            assert tv_ja in shows and film_ja not in shows
            # Shows never contain a film; Movies never contain a show
            assert set(listed(c, "/api/movies?type=show&genre=animation")) >= {tv_en} and not {film_ja, film_en} & set(listed(c, "/api/movies?type=show&genre=animation"))
            mv = listed(c, "/api/movies?type=movie&genre=animation")
            assert film_en in mv and tv_en not in mv and tv_ja not in mv
            allv = listed(c, "/api/genres/animation/movies?type=all")
            assert film_en in allv and tv_en in allv
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": list(ids.values())})
