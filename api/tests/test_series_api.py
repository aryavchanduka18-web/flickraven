"""Series and anime are in the catalog with their own type, seasons and episodes; Discover separates the types."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from pipeline.catalog import parse_credits, parse_movie
from pipeline.loader import load_catalog
from pipeline.series import normalize
from pipeline.tests.fixtures import good
from pipeline.tests.test_series import TV


@pytest.fixture(scope="module")
def client(test_engine):
    film = good(id=940001, title="A Film", original_title="A Film", imdb_id="tt940001", credits={"cast": [], "crew": []})
    series = normalize({**TV, "id": 1396})
    anime = normalize({**TV, "id": 31, "name": "Moon Blade", "original_name": "Moon Blade", "original_language": "ja",
                       "origin_country": ["JP"], "genres": [{"id": 16, "name": "Animation"}], "external_ids": {"imdb_id": "tt940031"}})
    details = [film, series, anime]
    movies = pd.DataFrame([parse_movie(d) for d in details])
    movies["catalog_part"] = "D"
    movies["ml_movie_id"] = pd.array([None] * len(movies), dtype="Int64")
    movies["dominant_color"] = "#336699"
    credits = pd.DataFrame([r for d in details for r in parse_credits(d)],
                           columns=["tmdb_id", "tmdb_person_id", "name", "profile_path", "role", "character", "credit_order"])
    load_catalog(test_engine, movies, credits, pd.DataFrame(columns=["tmdb_id"]), pd.DataFrame(), prune=False)
    with TestClient(app) as c:
        yield c


def titles(client, **params):
    return {i["movie"]["title"] for i in client.get("/api/movies", params=params).json()["items"]}


def test_discover_defaults_to_films_and_filters_by_type(client):
    assert "Breaking Bad" not in titles(client, sort="popular") and "A Film" in titles(client, sort="popular")
    assert titles(client, type="series", sort="popular") == {"Breaking Bad"}
    assert titles(client, type="anime", sort="popular") == {"Moon Blade"}
    assert {"A Film", "Breaking Bad", "Moon Blade"} <= titles(client, type="all", sort="popular")


def test_series_page_has_type_seasons_episodes_and_creators(client):
    mid = next(i["movie"]["id"] for i in client.get("/api/movies", params={"type": "series", "sort": "popular"}).json()["items"])
    d = client.get(f"/api/movies/{mid}").json()
    assert (d["title_type"], d["seasons"], d["episodes"], d["series_status"]) == ("series", 5, 62, "Ended")
    assert [w["name"] for w in d["writers"]] == ["Vince Gilligan"] and d["directors"] == []
    assert d["tmdb_id"] == 10_000_000 + 1396


def test_search_finds_series_and_cards_carry_the_type(client):
    items = client.get("/api/search", params={"q": "breaking"}).json()["items"]
    assert items[0]["movie"]["title"] == "Breaking Bad" and items[0]["movie"]["title_type"] == "series"


def test_search_understands_series_and_anime_words(client):
    def names(q):
        r = client.get("/api/search", params={"q": q}).json()
        return {i["movie"]["title"] for i in r["items"]}, r["understood"]
    got, u = names("series")
    assert got == {"Breaking Bad"} and u["kind"] == "series"
    assert names("anime")[0] == {"Moon Blade"}
    assert names("tv shows drama")[0] == {"Breaking Bad"}
    assert names("anime") [1]["kind"] == "anime"
    assert "A Film" in names("a film")[0]


def test_onboarding_offers_films_and_series_but_not_anime(client):
    guest = client.post("/api/auth/guest")
    assert guest.status_code == 200
    d = client.get("/api/onboarding/candidates").json()
    kinds = lambda key: {i["movie"]["title_type"] for i in d[key]}
    assert kinds("movies") <= {"movie"} and kinds("series") == {"series"} and "anime" not in d
    assert [i["movie"]["title"] for i in d["series"]] == ["Breaking Bad"]
    assert "Moon Blade" not in {i["movie"]["title"] for i in d["movies"]}
    assert d["genres"] and "languages" in d


class FakeEngine:
    """Just enough engine for the series-fit endpoint: the user's ranking is the order the series were loaded in."""
    def __init__(self, ids):
        import numpy as np
        self.cat = type("Cat", (), {"movie_ids": np.array(ids)})()

    def kind_rank(self, st, kind):
        import numpy as np
        return np.arange(len(self.cat.movie_ids)), np.ones(len(self.cat.movie_ids))


def test_series_fit_endpoint_filters_sorts_and_never_guesses(client, monkeypatch):
    from app.routers import recs
    ids = [i["movie"]["id"] for i in client.get("/api/movies", params={"type": "series", "sort": "popular"}).json()["items"]]
    monkeypatch.setattr(recs, "engine_or_503", lambda db: FakeEngine(ids))
    monkeypatch.setattr(recs.rec, "user_state", lambda db, uid, engine: None)
    ok = client.get("/api/recs/series-fit", params={"budget": "", "per_day": 2})
    assert ok.status_code == 200
    body = ok.json()
    assert body["total"] + body["unknown_length"] >= 1 and "options" in body
    assert body["items"], body
    it = body["items"][0]
    assert it["series"]["episodes"] == 62 and it["plan"]["finish"] and "a day" in it["plan"]["finish"]
    assert client.get("/api/recs/series-fit", params={"budget": "3"}).json()["items"] == []      # 62 episodes never fit 3 hours
    flex = client.get("/api/recs/series-fit", params={"per_day": 0})
    assert flex.status_code == 200 and all(i["plan"]["finish"] is None for i in flex.json()["items"])
    assert client.get("/api/recs/series-fit", params={"sort": "nonsense"}).status_code == 422
    assert client.get("/api/recs/series-fit", params={"series_type": "huge"}).status_code == 422
    assert client.get("/api/recs/series-fit", params={"genre": "Nonexistent"}).json()["total"] == 0
