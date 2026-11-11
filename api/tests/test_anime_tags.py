"""Anime genre / theme / avoid filters on the Anime genre page: OR inside the group, AND with the rest, avoid wins."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services import anime_tags as at


def test_rules_are_known_and_parse_ignores_unknown():
    assert at.parse("action, bogus,isekai,action") == ["action", "isekai"]
    conds, params = at.where(["action", "isekai"], ["isekai", "ecchi"])
    assert len(conds) == 3 and "tk0" in params           # action included; isekai only avoided; ecchi avoided


def test_anime_filters_end_to_end(test_engine):
    spec = {  # key: (title_type, genres, keywords)
        "tv_isekai": ("anime", ["Animation", "Action", "Fantasy"], ["isekai"]),
        "tv_ecchi_isekai": ("anime", ["Animation"], ["isekai", "ecchi"]),
        "tv_sports": ("anime", ["Animation"], ["sports"]),
        "film_romance": ("movie", ["Animation", "Romance"], []),
        "tv_plain": ("anime", ["Animation"], []),
        "tv_adv_genre_only": ("anime", ["Animation", "Adventure"], []),   # coarse TV genre alone is not enough for Adventure
        "film_adv_genre": ("movie", ["Animation", "Adventure"], []),      # a film's real genre is
    }
    ids = {}
    with test_engine.begin() as conn:
        gid = {g: conn.execute(text("INSERT INTO genres (name, slug) VALUES (:n, :s) ON CONFLICT (name) DO UPDATE SET slug = genres.slug RETURNING id"),
                               {"n": g, "s": g.lower()}).scalar() for g in {x for _, gs, _ in spec.values() for x in gs}}
        kid = {k: conn.execute(text("INSERT INTO keywords (name) VALUES (:n) ON CONFLICT (name) DO UPDATE SET name = :n RETURNING id"), {"n": k}).scalar()
               for k in {x for _, _, ks in spec.values() for x in ks}}
        for n, (key, (kind, gs, ks)) in enumerate(spec.items()):
            ids[key] = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 2015, 'ja', ARRAY['JP'], '/b.jpg', 8.0, 99999, :k)
                RETURNING id"""), {"t": 990400 + n, "n": f"Tag {key}", "k": kind}).scalar()
            for g in gs:
                conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": ids[key], "g": gid[g]})
            for k in ks:
                conn.execute(text("INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (:m, :k)"), {"m": ids[key], "k": kid[k]})

    def listed(c, q):
        return {i["movie"]["id"] for i in c.get(f"/api/genres/anime/movies?type=all&{q}").json()["items"]}
    try:
        with TestClient(app) as c:
            both = listed(c, "anime_tags=isekai,sports")                       # OR inside the group
            assert {ids["tv_isekai"], ids["tv_sports"], ids["tv_ecchi_isekai"]} <= both and ids["tv_plain"] not in both
            assert ids["tv_ecchi_isekai"] not in listed(c, "anime_tags=isekai&anime_avoid=ecchi")   # avoid wins
            assert ids["tv_isekai"] in listed(c, "anime_tags=isekai&anime_avoid=ecchi")
            assert ids["tv_plain"] not in listed(c, "anime_tags=action")
            assert ids["film_romance"] in listed(c, "anime_tags=romance")
            assert ids["film_adv_genre"] in listed(c, "anime_tags=adventure") and ids["tv_adv_genre_only"] not in listed(c, "anime_tags=adventure")
            assert ids["tv_isekai"] in listed(c, "anime_tags=isekai&type=show") and ids["film_romance"] not in listed(c, "anime_tags=romance&type=show")
            assert ids["tv_plain"] in listed(c, "")                                                  # no filter = unchanged
            body = c.get("/api/genres/anime/tags").json()
            assert "tags" in body and all(t["titles"] >= body["min_titles"] for t in body["tags"])
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": list(ids.values())})
