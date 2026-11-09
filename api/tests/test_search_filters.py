"""Search understands genre, language and year words and lists matching films, most popular first."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from pipeline.catalog import parse_credits, parse_movie
from pipeline.loader import load_catalog
from pipeline.tests.fixtures import good

HORROR, COMEDY, DRAMA, SCIFI = ({"id": i, "name": n} for i, n in ((27, "Horror"), (35, "Comedy"), (18, "Drama"), (878, "Science Fiction")))
# (tmdb id, title, votes, language, year, genres)
FILMS = [
    (930001, "Midnight Screams", 9000, "en", 1997, [HORROR]),
    (930002, "Quiet House", 4000, "en", 2019, [HORROR, DRAMA]),
    (930003, "Horror of the Deep", 300, "en", 1990, [DRAMA]),            # "horror" is only in the title
    (930004, "Shaadi Gone Wrong", 7000, "hi", 2019, [COMEDY]),
    (930005, "Jugaad", 2000, "hi", 1996, [COMEDY, DRAMA]),
    (930006, "Funny Business", 5000, "en", 2019, [COMEDY]),
    (930007, "Star Drift", 8000, "en", 2014, [SCIFI]),
    (930008, "Robot Hearts", 3000, "en", 1999, [SCIFI, COMEDY]),
]
CREDITS = {930001: {"cast": [{"id": 88001, "name": "Priyanka Sharma", "order": 0}], "crew": []},
           930004: {"cast": [{"id": 88001, "name": "Priyanka Sharma", "order": 0}], "crew": []}}


@pytest.fixture(scope="module")
def client(test_engine):
    details = [good(id=t, title=title, original_title=title, imdb_id=f"tt{t}", vote_count=v, original_language=lang,
                    release_date=f"{y}-06-01", genres=g, credits=CREDITS.get(t, {"cast": [], "crew": []}))
               for t, title, v, lang, y, g in FILMS]
    movies = pd.DataFrame([parse_movie(d) for d in details])
    movies["catalog_part"] = "B"
    movies["ml_movie_id"] = pd.array([None] * len(movies), dtype="Int64")
    movies["dominant_color"] = "#336699"
    credits = pd.DataFrame([r for d in details for r in parse_credits(d)],
                           columns=["tmdb_id", "tmdb_person_id", "name", "profile_path", "role", "character", "credit_order"])
    load_catalog(test_engine, movies, credits, pd.DataFrame(columns=["tmdb_id"]), pd.DataFrame(), prune=False)
    with TestClient(app) as c:
        yield c


def get(client, q):
    res = client.get("/api/search", params={"q": q})
    assert res.status_code == 200
    return res.json()


def titles(client, q):
    return [i["movie"]["title"] for i in get(client, q)["items"]]


def test_genre_word_lists_that_genre_not_title_matches(client):
    got = titles(client, "horror")
    assert got == ["Midnight Screams", "Quiet House"]          # a film titled "Horror of ..." is not a horror film


def test_genre_with_filler_words_and_plural(client):
    assert titles(client, "horror movies") == titles(client, "horror")
    assert titles(client, "comedies")[0] == "Shaadi Gone Wrong"


def test_language_and_genre(client):
    assert titles(client, "hindi comedy") == ["Shaadi Gone Wrong", "Jugaad"]
    assert get(client, "hindi comedy")["understood"]["language"] == "hi"


def test_year_and_decade(client):
    assert titles(client, "comedy 2019") == ["Shaadi Gone Wrong", "Funny Business"]
    assert titles(client, "90s comedy") == ["Robot Hearts", "Jugaad"]
    assert titles(client, "1990s horror") == ["Midnight Screams"]


def test_two_genres_and_aliases(client):
    assert titles(client, "sci-fi comedy") == ["Robot Hearts"]
    assert titles(client, "scifi")[0] == "Star Drift"


def test_filters_plus_title_text(client):
    assert titles(client, "horror quiet") == ["Quiet House"]
    assert titles(client, "hindi shaadi") == ["Shaadi Gone Wrong"]


def test_people_and_genre_suggestions(client):
    res = get(client, "priyanka")
    assert [p["name"] for p in res["people"]] == ["Priyanka Sharma"]
    assert set(titles(client, "priyanka")) == {"Midnight Screams", "Shaadi Gone Wrong"}
    assert [g["slug"] for g in get(client, "horr")["genres"]] == ["horror"]
    assert [p["name"] for p in get(client, "priyankasharma")["people"]] == ["Priyanka Sharma"]   # spaces left out


def test_plain_title_search_is_unchanged(client):
    assert titles(client, "star drift")[0] == "Star Drift"
    assert get(client, "star drift")["understood"]["genres"] == []


def test_suggest_is_light_and_grouped(client):
    res = client.get("/api/search/suggest", params={"q": "shaa"}).json()
    assert res["films"][0]["title"] == "Shaadi Gone Wrong" and set(res["films"][0]) == {"id", "title", "year", "poster"}
    res = client.get("/api/search/suggest", params={"q": "priya"}).json()
    assert res["people"][0]["name"] == "Priyanka Sharma"
    assert client.get("/api/search/suggest", params={"q": "a"}).json() == {"films": [], "people": [], "genres": []}


@pytest.mark.parametrize("q", ["100%", "a_b", "'&!:*", "\\", "x" * 300, "   "])
def test_odd_queries_do_not_fail(client, q):
    assert client.get("/api/search", params={"q": q}).status_code == 200
