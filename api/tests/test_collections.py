"""Themed collections: membership from real genres, pinned titles first, small collections hidden."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app

FILMS = [  # tmdb, title, year, genres, votes
    (940001, "Leap Year", 2010, ["Romance", "Comedy"], 2000), (940002, "Big Romcom", 2015, ["Romance", "Comedy"], 9000),
    (940003, "Only Romance", 2001, ["Romance"], 5000), (940004, "Romcom Three", 2003, ["Romance", "Comedy"], 100),
    (940005, "Romcom Four", 2004, ["Comedy", "Romance"], 50), (940006, "Romcom Five", 2005, ["Romance", "Comedy"], 40),
    (940007, "Romcom Six", 2006, ["Romance", "Comedy"], 30),
]


@pytest.fixture(scope="module")
def films(test_engine):
    with test_engine.begin() as conn:
        for t, title, year, genres, votes in FILMS:
            mid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, tmdb_vote_count, popularity_score)
                VALUES (:t, :ti, :y, :v, :v) RETURNING id"""), {"t": t, "ti": title, "y": year, "v": votes}).scalar()
            for g in genres:
                gid = conn.execute(text("""INSERT INTO genres (name, slug) VALUES (:g, lower(:g))
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"""), {"g": g}).scalar()
                conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": mid, "g": gid})
    yield
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 940000 AND 940999"))


def test_rom_com_pins_leap_year_then_orders_by_popularity(films):
    res = TestClient(app).get("/api/collections")
    rom = next(c for c in res.json()["collections"] if c["key"] == "rom-com")
    titles = [i["movie"]["title"] for i in rom["items"]]
    assert titles[0] == "Leap Year"
    assert titles[1] == "Big Romcom"
    assert "Only Romance" not in titles
    assert rom["count"] == 6


def test_collections_under_six_films_are_hidden(films):
    keys = {c["key"] for c in TestClient(app).get("/api/collections").json()["collections"]}
    assert "crime-thriller" not in keys


def test_collection_page_and_unknown_key(films):
    c = TestClient(app)
    assert c.get("/api/collections/rom-com").json()["count"] == 6
    assert c.get("/api/collections/nope").status_code == 404


def test_disliked_and_watched_films_leave_the_collection(films, test_engine):
    c = TestClient(app)
    c.post("/api/auth/guest")
    with test_engine.connect() as conn:
        big = conn.execute(text("SELECT id FROM movies WHERE tmdb_id = 940002")).scalar()
        three = conn.execute(text("SELECT id FROM movies WHERE tmdb_id = 940004")).scalar()
    c.put(f"/api/reactions/{big}", json={"value": -1})
    c.put(f"/api/watched/{three}")
    titles = [i["movie"]["title"] for i in c.get("/api/collections/rom-com").json()["items"]]
    assert "Big Romcom" not in titles and "Romcom Three" not in titles and "Leap Year" in titles


HINDI = [(941000 + n, f"Hindi Film {n}", 2012 + (n % 8) if n < 8 else 1985 + n, ["Comedy", "Romance"] if n % 2 else ["Thriller"], 1000 - n)
         for n in range(14)]
TAMIL = [(941100 + n, f"Tamil Film {n}", 2015, ["Drama"], 500 - n) for n in range(7)]


@pytest.fixture
def indian(test_engine, monkeypatch):
    from app.routers import collections as router
    with test_engine.begin() as conn:
        for lang, rows in (("hi", HINDI), ("ta", TAMIL)):
            for t, title, year, genres, votes in rows:
                mid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, tmdb_vote_count, popularity_score, original_language)
                    VALUES (:t, :ti, :y, :v, :v, :l) RETURNING id"""), {"t": t, "ti": title, "y": year, "v": votes, "l": lang}).scalar()
                for g in genres:
                    gid = conn.execute(text("""INSERT INTO genres (name, slug) VALUES (:g, lower(:g))
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"""), {"g": g}).scalar()
                    conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": mid, "g": gid})
        uid_en = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('col-en@example.com', 'a', 'x', false) RETURNING id")).scalar()
        uid_hi = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('col-hi@example.com', 'a', 'x', false) RETURNING id")).scalar()
        conn.execute(text("INSERT INTO user_preferences (user_id, languages) VALUES (:u, ARRAY['en'])"), {"u": uid_en})
        conn.execute(text("INSERT INTO user_preferences (user_id, languages) VALUES (:u, ARRAY['hi', 'en'])"), {"u": uid_hi})
    who = {"uid": None}
    monkeypatch.setattr(router, "user_id_from", lambda request, db: who["uid"])
    yield who, uid_en, uid_hi
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 941000 AND 941999"))
        conn.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": [uid_en, uid_hi]})


def keys(client):
    return {c["key"]: c for c in client.get("/api/collections").json()["collections"]}


def test_hindi_rows_appear_only_for_people_interested_in_hindi(indian):
    who, uid_en, uid_hi = indian
    c = TestClient(app)
    who["uid"] = None
    assert not {"hindi-picked", "modern-bollywood", "indian-beyond"} & set(keys(c))
    who["uid"] = uid_en
    assert not {"hindi-picked", "modern-bollywood", "hindi-comedy"} & set(keys(c))      # English-only: no Hindi quota
    who["uid"] = uid_hi
    got = keys(c)
    assert {"hindi-picked", "modern-bollywood", "hindi-thriller-crime", "hindi-comedy", "bollywood-rom-com", "retro-hindi"} <= set(got)
    assert all(i["movie"]["title"].startswith("Hindi Film") for i in got["modern-bollywood"]["items"] if i["movie"]["year"] >= 2010)
    assert all(i["movie"]["year"] >= 2010 for i in got["modern-bollywood"]["items"])
    assert "indian-beyond" not in got            # Hindi-only profile: regional cinema row needs its own interest
    assert got["retro-hindi"]["title"] == "Bollywood Classics"
