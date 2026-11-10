"""Film page franchise sections: the collection in release order, Marvel, and the director fallback."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services.franchise import collection_title

FILMS = [  # tmdb, title, date, collection, studios
    (930001, "Wick One", "2014-10-24", 77, []), (930002, "Wick Two", "2017-02-10", 77, []),
    (930003, "Wick Three", "2019-05-17", 77, []),
    (930011, "Hero Alpha", "2008-05-02", 88, ["Marvel Studios"]), (930012, "Hero Team", "2012-05-04", None, ["Marvel Studios"]),
    (930021, "Lone Film", "2001-01-01", None, []), (930022, "Lone Film Too", "2005-01-01", None, []),
]


@pytest.fixture(scope="module")
def ids(test_engine):
    out = {}
    with test_engine.begin() as conn:
        for t, title, d, col, studios in FILMS:
            out[title] = conn.execute(text("""INSERT INTO movies (tmdb_id, title, release_date, year, collection_id,
                collection_name, studios) VALUES (:t, :ti, :d, :y, :c, :cn, :s) RETURNING id"""),
                {"t": t, "ti": title, "d": d, "y": int(d[:4]), "c": col, "s": studios,
                 "cn": {77: "Wick Collection", 88: "Hero Alpha Collection"}.get(col)}).scalar()
        pid = conn.execute(text("INSERT INTO people (tmdb_person_id, name) VALUES (930900, 'Some Director') RETURNING id")).scalar()
        for title in ("Lone Film", "Lone Film Too"):
            conn.execute(text("INSERT INTO movie_credits (movie_id, person_id, role) VALUES (:m, :p, 'director')"),
                         {"m": out[title], "p": pid})
    yield out
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 930000 AND 930999"))
        conn.execute(text("DELETE FROM people WHERE tmdb_person_id = 930900"))


def sections(movie_id: int) -> dict[str, dict]:
    res = TestClient(app).get(f"/api/movies/{movie_id}/franchise")
    assert res.status_code == 200
    return {s["kind"]: s for s in res.json()["sections"]}


def test_collection_lists_every_part_in_release_order(ids):
    s = sections(ids["Wick Two"])["collection"]
    assert s["title"] == "More from Wick"
    assert [i["movie"]["title"] for i in s["items"]] == ["Wick One", "Wick Two", "Wick Three"]
    assert s["current"] == ids["Wick Two"]


def test_marvel_universe_comes_with_the_collection(ids):
    secs = sections(ids["Hero Alpha"])
    assert [i["movie"]["title"] for i in secs["universe"]["items"]] == ["Hero Team"]
    assert secs["universe"]["title"] == "More from Marvel"


def test_film_without_a_collection_falls_back_to_its_director(ids):
    secs = sections(ids["Lone Film"])
    assert "collection" not in secs
    assert secs["director"]["title"] == "More from Some Director"
    assert [i["movie"]["title"] for i in secs["director"]["items"]] == ["Lone Film Too"]


def test_unknown_film_is_404():
    assert TestClient(app).get("/api/movies/999999999/franchise").status_code == 404


def test_collection_title():
    assert collection_title("The Avengers Collection") == "The Avengers"
    assert collection_title("X-Men Collection") == "X-Men"


def test_no_franchise_rows_for_a_film_that_is_not_part_of_one(ids):
    secs = sections(ids["Lone Film"])
    assert "franchise_like" not in secs and set(secs) <= {"director"}


def test_series_get_no_franchise_rows(ids, test_engine):
    with test_engine.begin() as conn:
        sid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, title_type, year) VALUES (930500, 'A Series', 'series', 2020)
                                   RETURNING id""")).scalar()
    try:
        assert TestClient(app).get(f"/api/movies/{sid}/franchise").json() == {"sections": []}
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = :i"), {"i": sid})
