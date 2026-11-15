"""Scenario tests (spec section 16): the live API on the REAL catalog and models.

They use the development database (the test database has no catalog) with throwaway users that are
deleted afterwards (ON DELETE CASCADE removes everything they did). Skipped if the models are missing.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.main import app
from app.services.recommender import artifacts_ready

if not artifacts_ready():
    pytest.skip("models not built yet", allow_module_level=True)

CREATED: list[int] = []


@pytest.fixture(autouse=True)
def _same_daily_seed_for_everyone(monkeypatch):
    """Home draws part of each row with a seed made from the user id and the date, and every test creates a new guest, so a
    scenario that compares two lists could pass or fail depending on the guest's id (test_7 did, 2026-11-15). The seed is
    pinned to the label alone: the same page for every test user, the same on every run."""
    import hashlib
    from app.services import daily
    monkeypatch.setattr(daily, "seed", lambda user_id, label="", day=None: int(hashlib.sha256(label.encode()).hexdigest()[:12], 16))


@pytest.fixture
def client():
    c = TestClient(app)
    uid = c.post("/api/auth/guest").json()["id"]
    CREATED.append(uid)
    c.user_id = uid
    yield c


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": CREATED})
        db.commit()


def find(db_sql: str, **params) -> list[int]:
    with SessionLocal() as db:
        return [r[0] for r in db.execute(text(db_sql), params)]


def genre_ids(*names) -> list[int]:
    return find("SELECT id FROM genres WHERE name = ANY(:n)", n=list(names))


def films_in(*genres, n=5, min_votes=3000) -> list[int]:
    """Well-known part-A films having all the given genres."""
    return find("""SELECT m.id FROM movies m WHERE m.catalog_part = 'A' AND m.tmdb_vote_count >= :v
        AND (SELECT count(*) FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
             WHERE mg.movie_id = m.id AND g.name = ANY(:g)) = :k
        ORDER BY m.tmdb_vote_count DESC LIMIT :n""", g=list(genres), k=len(genres), v=min_votes, n=n)


def onboard(c, movie_ids, languages=("en",), liked=(), disliked=()):
    r = c.post("/api/onboarding", json={"movie_ids": list(movie_ids), "languages": list(languages),
                                        "liked_genre_ids": list(liked), "disliked_genre_ids": list(disliked)})
    assert r.status_code == 200, r.text


def top_ids(home, k=20):
    ids = [i["movie"]["id"] for i in home["hero"]]
    for rail in home["rails"]:
        if rail["key"] == "top_picks":
            ids += [i["movie"]["id"] for i in rail["items"]]
    return ids[:k]


def genres_of(ids) -> dict[int, set]:
    rows = find("""SELECT mg.movie_id || ':' || g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
                   WHERE mg.movie_id = ANY(:ids)""", ids=list(ids))
    out: dict[int, set] = {i: set() for i in ids}
    for r in rows:
        m, g = r.split(":", 1)
        out[int(m)].add(g)
    return out


@pytest.fixture
def unique():
    return uuid.uuid4().hex[:8]