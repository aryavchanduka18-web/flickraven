"""The Anime page route with a fake engine: anime series and anime films only, never live-action, never a title the
person has seen (the engine's job) or marked Not interested (the route's job), and no title twice."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import current_user
from app.main import app
from app.routers import recs as recs_router


class Cat:
    def __init__(self, ids, kind, genres, lang, pop):
        self.movie_ids = np.array(ids)
        self.kind, self.genres, self.language = kind, genres, lang
        self.keywords = [[] for _ in ids]
        self.popularity = np.array(pop, dtype=float)
        self.fame_pct = np.linspace(0, 100, len(ids))
        self.titles = [f"T{i}" for i in range(len(ids))]
        self.row_of = {int(m): i for i, m in enumerate(ids)}


class State:
    stage = "established"
    ratings, picks, in_list, watched, dislikes, languages = {}, set(), set(), set(), set(), []
    likes: set = set()


class Engine:
    def __init__(self, cat, seen):
        self.cat, self.seen = cat, seen

    def kind_rank(self, st, kind):
        rows = [i for i, k in enumerate(self.cat.kind) if k == kind and i not in self.seen]
        return np.array(rows, dtype=int), np.linspace(1, 0.1, len(rows))

    def rail_scores(self, st):
        s = np.where(np.asarray(self.cat.kind) == "movie", np.linspace(1, 0.1, len(self.cat.kind)), -np.inf)
        s[list(self.seen)] = -np.inf
        return s

    def similar(self, row, k=20):
        return [i for i, kd in enumerate(self.cat.kind) if i != row and kd == self.cat.kind[row]][:k]


@pytest.fixture
def client(test_engine, monkeypatch):
    spec = ([("anime", ["Animation", "Action & Adventure"], "ja")] * 40 + [("movie", ["Animation", "Fantasy"], "ja")] * 40
            + [("movie", ["Drama"], "ja")] * 10 + [("movie", ["Animation", "Family"], "en")] * 10 + [("series", ["Drama"], "ja")] * 10)
    ids = []
    with test_engine.begin() as conn:
        for n, (kind, genres, lang) in enumerate(spec):
            ids.append(conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, poster_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 2015, :l, ARRAY['JP'], '/b.jpg', '/p.jpg', 8.0, 5000, :k)
                RETURNING id"""), {"t": 993000 + n, "n": f"an-{n}", "l": lang, "k": kind}).scalar())
            for g in genres:
                gid = conn.execute(text("INSERT INTO genres (name, slug) VALUES (:g, lower(:g)) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"), {"g": g}).scalar()
                conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": ids[n], "g": gid})
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('anime-route@example.com', 'x', 'x', false) RETURNING id")).scalar()
        conn.execute(text("INSERT INTO interactions (user_id, movie_id, event_type) VALUES (:u, :m, 'not_interested')"), {"u": uid, "m": ids[1]})
    cat = Cat(ids, [k for k, _, _ in spec], [g for _, g, _ in spec], [l for _, _, l in spec], [8.0] * len(spec))
    seen = {0, 40}                                                    # one anime series and one anime film already watched
    state = State()
    state.likes = {2}
    monkeypatch.setattr(recs_router, "engine_or_503", lambda db: Engine(cat, seen))
    monkeypatch.setattr(recs_router.rec, "user_state", lambda db, u, e: state)
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "x@example.com", "display_name": "x", "is_guest": False}
    with TestClient(app) as c:
        c.ids, c.uid = ids, uid
        yield c
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendation_logs WHERE user_id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM interactions WHERE user_id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 993000 AND 993999"))


def test_anime_page_holds_anime_series_and_films_only(client):
    body = client.get("/api/recs/anime").json()
    rails = {r["key"]: r for r in body["rails"]}
    assert {"because", "series", "films"} <= set(rails)
    assert list(rails)[0] == "because" and rails["because"]["title"] == "Because you liked T2"
    anime_series, anime_films = set(client.ids[:40]), set(client.ids[40:80])
    shown = [i["movie"]["id"] for r in body["rails"] for i in r["items"]]
    assert set(shown) <= anime_series | anime_films                 # no live-action, no Pixar, no plain series
    assert len(shown) == len(set(shown))                             # no title twice
    assert {i["movie"]["id"] for i in rails["series"]["items"]} <= anime_series
    assert {i["movie"]["id"] for i in rails["films"]["items"]} <= anime_films
    assert client.ids[0] not in shown and client.ids[40] not in shown   # watched
    assert client.ids[1] not in shown                                 # Not interested
