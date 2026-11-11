"""kind rail and series rails with a fake engine: daily refresh, anime hits first, new feel-good and romance rows."""
import datetime as dt

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import current_user
from app.main import app
from app.routers import recs as recs_router
from app.services import daily


class Cat:
    def __init__(self, ids, kind, genres, lang, pop, keywords):
        self.movie_ids = np.array(ids)
        self.kind, self.genres, self.language, self.keywords = kind, genres, lang, keywords
        self.popularity = np.array(pop, dtype=float)
        self.fame_pct = np.linspace(0, 100, len(ids))
        self.titles = [f"T{i}" for i in range(len(ids))]
        self.runtime = np.full(len(ids), 40.0)
        self.novelty = np.full(len(ids), 0.3)


class Engine:
    anime_fans = 1                      # how many anime the test person has shown interest in

    def __init__(self, cat):
        self.cat = cat

    def anime_interest(self, st):
        return self.anime_fans

    def kind_rank(self, st, kind):
        rows = [i for i, k in enumerate(self.cat.kind) if k == kind][::-1]
        return np.array(rows, dtype=int), np.linspace(1, 0.1, len(rows))

    def similar(self, row, k=20):
        return []

    def rail_scores(self, st):
        return np.full(len(self.cat.kind), -np.inf)


class State:
    stage = "established"
    ratings, likes, picks, in_list, languages = {}, set(), set(), set(), []


@pytest.fixture
def client(test_engine, monkeypatch):
    kinds, genres, langs, pops, kws, titles, extra = [], [], [], [], [], [], []
    for n in range(40):                     # comedies: feel-good series
        kinds.append("series"); genres.append(["Comedy"]); langs.append(["ko", "en", "ja"][n % 3]); pops.append(7.3); kws.append([])
        extra.append(("series", 2, 40, 55, "Ended"))
    for n in range(60):                     # romance by keyword
        kinds.append("series"); genres.append(["Soap"]); langs.append("en"); pops.append(7.3); kws.append(["romance"])
        extra.append(("series", 2, 40, 55, "Ended"))
    for n in range(90):                     # anime: romance, comedy and plain action
        kinds.append("anime"); genres.append([["Romance", "Animation"], ["Comedy", "Animation"], ["Action", "Animation"]][n % 3])
        langs.append("ja"); pops.append(8.0); kws.append([]); extra.append(("anime", 2, 24, 24, "Ended"))
    ids = []
    with test_engine.begin() as conn:
        for n, (kind, seasons, episodes, runtime, status) in enumerate(extra):
            ids.append(conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, poster_path,
                popularity_score, tmdb_vote_count, title_type, runtime_min, episodes, seasons, series_status)
                VALUES (:t, :n, 2015, :l, ARRAY['US'], '/b.jpg', '/p.jpg', :p, 5000, :k, :rt, :ep, :se, :st) RETURNING id"""),
                {"t": 992000 + n, "n": f"dr-{n}", "l": langs[n], "p": pops[n], "k": kind, "rt": runtime, "ep": episodes, "se": seasons, "st": status}).scalar())
            for g in genres[n]:
                gid = conn.execute(text("INSERT INTO genres (name, slug) VALUES (:g, lower(:g)) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"), {"g": g}).scalar()
                conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": ids[n], "g": gid})
            for k in kws[n]:
                kid = conn.execute(text("INSERT INTO keywords (name) VALUES (:k) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"), {"k": k}).scalar()
                conn.execute(text("INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (:m, :k)"), {"m": ids[n], "k": kid})
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('daily-route@example.com', 'x', 'x', false) RETURNING id")).scalar()
    cat = Cat(ids, kinds, genres, langs, pops, kws)
    monkeypatch.setattr(recs_router, "engine_or_503", lambda db: Engine(cat))
    monkeypatch.setattr(recs_router.rec, "user_state", lambda db, u, e: State())
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "x@example.com", "display_name": "x", "is_guest": False}
    with TestClient(app) as c:
        c.ids, c.uid = ids, uid
        yield c
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendation_logs WHERE user_id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 992000 AND 992999"))


def test_anime_hits_wait_for_people_with_no_anime_interest(client, monkeypatch):
    monkeypatch.setattr(Engine, "anime_fans", 0)
    keys = [r["key"] for r in client.get("/api/recs/series-rails").json()["rails"]]
    assert "anime_hits" in keys and keys.index("anime_hits") == 2        # after the first two themed rows, still shown


def test_series_rails_have_anime_hits_first_and_the_new_rows(client):
    rails = client.get("/api/recs/series-rails").json()["rails"]
    keys = [r["key"] for r in rails]
    assert keys[0] == "anime_hits"
    assert {"feelgood", "romance", "anime_romance", "anime_feelgood"} <= set(keys)
    seen = [i["movie"]["id"] for r in rails if r["key"] != "mix" for i in r["items"]]
    assert len(seen) == len(set(seen))                                   # no title in two rows
    anime = {r["key"]: r for r in rails}["anime_romance"]
    assert all(i["movie"]["title_type"] == "anime" for i in anime["items"])


def test_kind_rail_keeps_a_core_and_changes_with_the_day(client, monkeypatch):
    day = {"d": dt.date(2026, 11, 11)}
    monkeypatch.setattr(daily, "today", lambda: day["d"])
    first = [i["movie"]["id"] for i in client.get("/api/recs/kind/anime?limit=12").json()["items"]]
    again = [i["movie"]["id"] for i in client.get("/api/recs/kind/anime?limit=12").json()["items"]]
    assert first == again                                                # same day, same list
    changed = False
    for n in range(1, 8):
        day["d"] = dt.date(2026, 11, 11 + n)
        other = [i["movie"]["id"] for i in client.get("/api/recs/kind/anime?limit=12").json()["items"]]
        changed = changed or other != first
        assert len(set(other) & set(first)) >= 3                         # a strong core stays
    assert changed
