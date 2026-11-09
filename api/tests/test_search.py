"""Search tolerates punctuation and typos in titles (normalized title + pg_trgm, migration 0004)."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from pipeline.catalog import parse_credits, parse_movie
from pipeline.loader import load_catalog
from pipeline.tests.fixtures import good

# (tmdb id, title, votes): the four target films plus look-alike decoys.
FILMS = [
    (910001, "L.A. Confidential", 4000), (910002, "Spenser Confidential", 2500),
    (910003, "How to Lose a Guy in 10 Days", 3500), (910004, "How to Train Your Dragon", 9000),
    (910005, "Horrible Bosses", 6000), (910006, "Horrible Bosses 2", 4000), (910007, "Bad Bosses", 100),
    (910008, "Central Intelligence", 5500), (910009, "Central Station", 800),
    (910010, "The Godfather", 20000), (910011, "Godfather", 50),
    # Prefix search: "dar" must reach The Dark Knight ahead of a film whose actor is called Dar.
    (910012, "The Dark Knight", 30000), (910013, "The Darjeeling Limited", 1500), (910014, "Radar Men", 10),
    (910015, "The Covenant", 40000), (910016, "Oppenheimer", 25000),
]
# Cast and crew for a few films, as TMDB sends them: (tmdb id) -> credits.
CREDITS = {
    910015: {"cast": [{"id": 77001, "name": "Dar Salim", "order": 0}], "crew": []},
    910016: {"cast": [], "crew": [{"id": 77002, "name": "Christopher Nolan", "job": "Director"}]},
    910012: {"cast": [], "crew": [{"id": 77002, "name": "Christopher Nolan", "job": "Director"}]},
}


@pytest.fixture(scope="module")
def client(test_engine):
    details = [good(id=t, title=title, original_title=title, imdb_id=f"tt{t}", vote_count=v,
                    credits=CREDITS.get(t, {"cast": [], "crew": []})) for t, title, v in FILMS]
    movies = pd.DataFrame([parse_movie(d) for d in details])
    movies["catalog_part"] = "B"
    movies["ml_movie_id"] = pd.array([None] * len(movies), dtype="Int64")
    movies["dominant_color"] = "#336699"
    credits = pd.DataFrame([r for d in details for r in parse_credits(d)],
                           columns=["tmdb_id", "tmdb_person_id", "name", "profile_path", "role", "character", "credit_order"])
    load_catalog(test_engine, movies, credits, pd.DataFrame(columns=["tmdb_id"]), pd.DataFrame(), prune=False)
    with TestClient(app) as c:
        yield c


def titles(client, q: str) -> list[str]:
    res = client.get("/api/search", params={"q": q})
    assert res.status_code == 200
    return [i["movie"]["title"] for i in res.json()["items"]]


@pytest.mark.parametrize("query, expected", [
    ("LA confidential", "L.A. Confidential"),                 # punctuation in the stored title
    ("how to loose a guy", "How to Lose a Guy in 10 Days"),  # misspelled word
    ("horrible bossses", "Horrible Bosses"),                 # repeated letter
    ("central intellgence", "Central Intelligence"),         # dropped letter
])
def test_typo_and_punctuation_queries_find_the_film_first(client, query, expected):
    assert titles(client, query)[0] == expected


def test_exact_title_ranks_above_less_known_namesakes(client):
    assert titles(client, "godfather")[:2] == ["The Godfather", "Godfather"]


def test_no_false_positives(client):
    assert titles(client, "xqzvt wplkj") == []
    # A different film that shares a word is not returned as a typo match.
    assert "How to Train Your Dragon" not in titles(client, "how to loose a guy")
    assert "Central Station" not in titles(client, "central intellgence")
    assert "Bad Bosses" not in titles(client, "horrible bossses")


def test_first_letters_of_a_title_word_find_the_film_first(client):
    # Typing "dar" shows titles with a word starting "dar" (most voted first) before the actor Dar Salim's film
    # and before a mid-word match ("Radar").
    got = titles(client, "dar")
    assert got[:2] == ["The Dark Knight", "The Darjeeling Limited"]
    assert got.index("The Covenant") > 1 and got.index("Radar Men") > 1


def test_prefix_of_several_words_and_leading_the(client):
    assert titles(client, "dark kni")[0] == "The Dark Knight"
    assert titles(client, "the dar")[0] == "The Dark Knight"


def test_cast_and_director_still_found_by_partial_name(client):
    assert {"Oppenheimer", "The Dark Knight"} <= set(titles(client, "nol"))
    assert set(titles(client, "christopher nolan")) == {"Oppenheimer", "The Dark Knight"}
    assert titles(client, "dar salim")[0] == "The Covenant"


def test_punctuation_only_query_is_harmless(client):
    assert client.get("/api/search", params={"q": "'&!:*"}).status_code == 200
