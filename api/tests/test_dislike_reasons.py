"""Dislike reasons: several at once, each changing something real; the old single-reason call still works."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


@pytest.fixture()
def film(test_engine):
    with test_engine.begin() as conn:
        mid = conn.execute(text("INSERT INTO movies (tmdb_id, title, year, original_language) VALUES (950001, 'Slow Film', 2001, 'en') RETURNING id")).scalar()
    yield mid
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = :i"), {"i": mid})


def test_several_reasons_at_once(film):
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        r = c.post("/api/feedback/dislike-reason", json={"movie_id": film, "reasons": ["slow", "predictable", "unexpected"]})
        assert r.status_code == 200
        body = r.json()
        assert body["reasons"] == ["slow", "predictable", "unexpected"]
        assert body["tuning"]["length"] == 40 and body["tuning"]["adventurous"] == 65 and body["tuning"]["hidden"] == 60
        assert "less obvious picks" in body["message"]


def test_single_reason_still_works_and_unknown_is_rejected(film):
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        assert c.post("/api/feedback/dislike-reason", json={"movie_id": film, "reason": "long"}).json()["tuning"]["length"] == 30
        assert c.post("/api/feedback/dislike-reason", json={"movie_id": film, "reasons": ["nonsense"]}).status_code == 422
        assert c.post("/api/feedback/dislike-reason", json={"movie_id": film, "reasons": []}).status_code == 422
        none = c.post("/api/feedback/dislike-reason", json={"movie_id": film, "reasons": ["none"]}).json()
        assert none["message"].startswith("Thanks, noted")
