"""POST /recs/perfect-pick end to end with a small fake engine: kinds, time, language and relaxation reach the result."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import current_user
from app.main import app
from app.routers import recs as recs_router


class Cat:
    def __init__(self, ids, kind, genres, lang, runtime):
        self.movie_ids = np.array(ids)
        self.kind = kind
        self.genres = genres
        self.keywords = [[] for _ in ids]
        self.language = lang
        self.runtime = np.array(runtime, dtype=float)
        self.novelty = np.full(len(ids), 0.3)


class Engine:
    def __init__(self, cat):
        self.cat = cat

    def rail_scores(self, st):
        return np.array([0.9 - 0.05 * i if k == "movie" else -np.inf for i, k in enumerate(self.cat.kind)])

    def kind_rank(self, st, kind):
        rows = [i for i, k in enumerate(self.cat.kind) if k == kind]
        return np.array(rows, dtype=int), np.array([0.8 - 0.05 * r for r in rows])

    def match(self, stage, score):
        return int(score * 100)


class State:
    stage = "established"


@pytest.fixture
def client(test_engine, monkeypatch):
    rows = [("pp-f1", "movie", "Comedy", "en", 85), ("pp-f2", "movie", "Comedy", "hi", 100), ("pp-f3", "movie", "Drama", "hi", 130),
            ("pp-f4", "movie", "Comedy", "en", 95), ("pp-s1", "series", "Drama", "ko", 50), ("pp-s2", "series", "Drama", "ko", 50),
            ("pp-s3", "series", "Drama", "ko", 50)]
    ids = []
    with test_engine.begin() as conn:
        for n, (t, kind, g, lang, rt) in enumerate(rows):
            ids.append(conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, poster_path,
                popularity_score, tmdb_vote_count, title_type, runtime_min, episodes, seasons, series_status)
                VALUES (:t, :n, 2015, :l, ARRAY['US'], '/b.jpg', '/p.jpg', 7, 5000, :k, :rt, :ep, :se, :st) RETURNING id"""),
                {"t": 991000 + n, "n": t, "l": lang, "k": kind, "rt": rt, "ep": 8 if kind == "series" else None,
                 "se": 1 if kind == "series" else None, "st": "Ended" if kind == "series" else None}).scalar())
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('pp-route@example.com', 'x', 'x', false) RETURNING id")).scalar()
    cat = Cat(ids, [r[1] for r in rows], [[r[2]] for r in rows], [r[3] for r in rows], [r[4] for r in rows])
    monkeypatch.setattr(recs_router, "engine_or_503", lambda db: Engine(cat))
    monkeypatch.setattr(recs_router.rec, "user_state", lambda db, uid, e: State())
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "x@example.com", "display_name": "x", "is_guest": False}
    with TestClient(app) as c:
        c.ids = ids
        yield c
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM recommendation_logs WHERE user_id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 991000 AND 991010"))


def pick(c, **body):
    r = c.post("/api/recs/perfect-pick", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_series_only_and_film_only(client):
    shows = pick(client, kind="series", time="h10", adventure="familiar")
    assert {i["movie"]["title"] for i in shows["items"]} == {"pp-s1", "pp-s2", "pp-s3"}
    films = pick(client, kind="movie", time="any", adventure="familiar")
    assert all(i["movie"]["title"].startswith("pp-f") for i in films["items"])


def test_film_time_band_and_language_and_reasons(client):
    got = pick(client, kind="movie", time="90_120", languages=["hi"], adventure="familiar")
    # only one Hindi film fits 90-120 minutes; English ones are offered, never added silently
    assert [i["movie"]["title"] for i in got["items"]] == ["pp-f2"] and got["alternatives"] == []
    assert got["offer"] == "other_languages" and "Include other languages" in got["message"]
    wider = pick(client, kind="movie", time="90_120", languages=["hi"], adventure="familiar", other_languages=True)
    assert {i["movie"]["title"] for i in wider["items"]} == {"pp-f2", "pp-f4"} and wider["offer"] is None
    for it in got["items"]:
        assert it["reasons"] and all(r["source"] == "perfect_pick" for r in it["reasons"])


def test_relaxation_is_reported_and_not_these_excludes(client):
    first = pick(client, kind="movie", mood="Scary", time="any", adventure="familiar")
    # no horror film exists: nothing is passed off as an exact match; the alternatives each say they miss the mood
    assert first["items"] == [] and len(first["alternatives"]) == 3 and first["relaxed"] == ["mood"]
    assert all(a["misses"] == ["mood"] for a in first["alternatives"]) and "broader alternatives" in first["message"]
    assert all(any(r["text"] == 'Does not match the "scary" mood' for r in a["reasons"]) for a in first["alternatives"])
    again = pick(client, kind="movie", time="any", adventure="familiar", exclude=[i["movie"]["id"] for i in first["alternatives"]])
    assert not {i["movie"]["id"] for i in again["items"]} & {i["movie"]["id"] for i in first["alternatives"]}


def test_some_exact_then_labelled_alternatives(client, test_engine):
    got = pick(client, kind="movie", genres=["Drama"], time="any", adventure="familiar")
    assert [i["movie"]["title"] for i in got["items"]] == ["pp-f3"] and all(i["misses"] == [] for i in got["items"])
    assert len(got["alternatives"]) == 2 and all(a["misses"] == ["genres"] for a in got["alternatives"])
    assert got["message"].startswith("Only 1 title meets every answer")
    with test_engine.begin() as conn:
        surfaces = {r[0] for r in conn.execute(text("SELECT surface FROM recommendation_logs WHERE movie_id = ANY(:i)"), {"i": client.ids})}
    assert {"perfect_pick", "perfect_pick_alt"} <= surfaces


def test_romantic_korean_series_match_through_keywords(client, monkeypatch):
    # TMDB gives series no Romance genre; a "romance" keyword must be enough for the Romantic mood and the Romance genre
    cat = recs_router.engine_or_503(None).cat
    cat.keywords[4] = ["romance", "first love"]
    got = pick(client, kind="series", mood="Romantic", genres=["Romance"], languages=["ko"], time="h10", adventure="familiar")
    assert [i["movie"]["title"] for i in got["items"]] == ["pp-s1"]
    assert any("from TMDB keywords" in r["text"] for r in got["items"][0]["reasons"])
    assert {a["movie"]["title"] for a in got["alternatives"]} == {"pp-s2", "pp-s3"}
    assert all(a["misses"] == ["mood", "genres"] for a in got["alternatives"])


def test_bad_values_are_refused(client):
    assert client.post("/api/recs/perfect-pick", json={"kind": "movie", "time": "h10"}).status_code == 422
    assert client.post("/api/recs/perfect-pick", json={"kind": "movie", "mood": "Sleepy"}).status_code == 422


def test_show_more_continues_in_order_then_ends(client):
    first = pick(client, kind="movie", time="any", adventure="familiar")
    assert len(first["items"]) == 3 and first["remaining"] == {"exact": 1, "alternatives": 0}
    shown = [i["movie"]["id"] for i in first["items"]]
    more = pick(client, kind="movie", time="any", adventure="familiar", exclude=shown, more=True)
    assert len(more["items"]) == 1 and not set(shown) & {i["movie"]["id"] for i in more["items"]}
    assert more["message"] == "That is the last of the titles that meet every answer."
    assert more["remaining"] == {"exact": 0, "alternatives": 0}
    shown += [i["movie"]["id"] for i in more["items"]]
    end = pick(client, kind="movie", time="any", adventure="familiar", exclude=shown, more=True)
    assert end["items"] == [] and end["alternatives"] == [] and end["message"].startswith("That is everything")


def test_anime_genre_returns_anime_only(client, test_engine):
    with test_engine.begin() as conn:
        aid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, poster_path,
            popularity_score, tmdb_vote_count, title_type, runtime_min, episodes, seasons, series_status)
            VALUES (991009, 'pp-a1', 2015, 'ja', ARRAY['JP'], '/b.jpg', '/p.jpg', 7, 5000, 'anime', 24, 12, 1, 'Ended') RETURNING id""")).scalar()
    cat = recs_router.engine_or_503(None).cat
    cat.movie_ids = np.append(cat.movie_ids, aid)
    cat.kind = cat.kind + ["anime"]
    cat.genres = cat.genres + [["Animation", "Action"]]
    cat.keywords = cat.keywords + [[]]
    cat.language = cat.language + ["ja"]
    cat.runtime = np.append(cat.runtime, 24.0)
    cat.novelty = np.append(cat.novelty, 0.3)
    got = pick(client, kind="series", genres=["Anime"], time="any", adventure="familiar")
    assert [i["movie"]["title"] for i in got["items"]] == ["pp-a1"] and got["alternatives"] == []
    assert any(r["text"] == "Anime, which you picked" for r in got["items"][0]["reasons"])
