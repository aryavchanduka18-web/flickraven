"""Opt-in taste summary for the assistant: off by default, coarse words only, suggestion requests only (Gemini is faked)."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import current_user
from app.config import get_settings
from app.main import app
from app.services import assistant as ai
from app.services import assistant_taste as taste

LIKED = ["Quiet Harbour Murders", "The Glass Witness", "Night Ferry Seoul"]


class FakeResp:
    status_code = 200

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "Try something tense tonight."}]}}]}


@pytest.fixture
def client(monkeypatch, test_engine):
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    monkeypatch.setattr(s, "assistant_enabled", True)
    monkeypatch.setattr(s, "assistant_daily_cap", 20)
    ai._used.clear()
    sent = []
    monkeypatch.setattr(ai.httpx, "post", lambda url, json=None, headers=None, timeout=None: sent.append(json) or FakeResp())
    with test_engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (display_name, email) VALUES ('Secret Name', 'taste-secret@example.com') RETURNING id")).scalar()
        conn.execute(text("INSERT INTO genres (id, name, slug) VALUES (990801, 'Thriller', 'thriller-t'), (990802, 'Crime', 'crime-t'), "
                          "(990803, 'Horror', 'horror-t') ON CONFLICT DO NOTHING"))
        gid = {n: i for i, n in conn.execute(text("SELECT id, name FROM genres WHERE name IN ('Thriller', 'Crime', 'Horror')"))}
        ids = []
        for n, title in enumerate(LIKED):
            mid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, title_type)
                VALUES (:t, :ti, 2015, 'ko', 'series') RETURNING id"""), {"t": 990810 + n, "ti": title}).scalar()
            ids.append(mid)
            conn.execute(text("INSERT INTO movie_genres VALUES (:m, :g), (:m, :g2)"), {"m": mid, "g": gid["Thriller"], "g2": gid["Crime"]})
        c_ids = ids
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "taste-secret@example.com", "display_name": "Secret Name", "is_guest": False}
    with TestClient(app) as c:
        c.sent, c.uid, c.movie_ids, c.engine, c.gid = sent, uid, c_ids, test_engine, gid
        yield c
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 990810 AND 990819"))
        conn.execute(text("DELETE FROM genres WHERE id IN (990801, 990802, 990803)"))


def like(c, n=3):
    with c.engine.begin() as conn:
        for mid in c.movie_ids[:n]:
            conn.execute(text("INSERT INTO reactions (user_id, movie_id, value) VALUES (:u, :m, 1)"), {"u": c.uid, "m": mid})


def ask(c, q="Recommend me something for tonight"):
    r = c.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": q}]})
    assert r.status_code == 200
    return r.json(), json.dumps(c.sent[-1])


def test_off_by_default_and_nothing_is_sent(client):
    like(client)
    assert client.get("/api/assistant/status").json()["taste_sharing"] is False
    r, blob = ask(client)
    assert "Taste summary" not in blob and "Thriller" not in blob and r["taste_shared"] is False


def test_preview_is_coarse_with_no_titles_or_identity(client):
    like(client)
    with client.engine.begin() as conn:
        conn.execute(text("INSERT INTO user_preferences (user_id, disliked_genre_ids) VALUES (:u, ARRAY[:g])"),
                     {"u": client.uid, "g": client.gid["Horror"]})
    got = client.get("/api/assistant/taste-sharing").json()
    assert got["enabled"] is False
    line = got["summary"]
    assert "Crime and Thriller" in line or "Thriller and Crime" in line
    assert "mostly in Korean" in line and "mostly TV series" in line and "does not want Horror" in line
    for secret in [*LIKED, "Secret Name", "taste-secret", str(client.uid), "2015"]:
        assert secret not in line
    assert not any(ch.isdigit() for ch in line)


def test_opted_in_suggestion_request_sends_the_line_and_nothing_else_personal(client):
    like(client)
    assert client.put("/api/assistant/taste-sharing", json={"enabled": True}).json()["enabled"] is True
    assert client.get("/api/assistant/status").json()["taste_sharing"] is True
    r, blob = ask(client)
    assert "Taste summary this person chose to share" in blob and "mostly in Korean" in blob and r["taste_shared"] is True
    for secret in [*LIKED, "Secret Name", "taste-secret@example.com"]:
        assert secret not in blob


def test_question_of_fact_never_carries_the_line(client):
    like(client)
    client.put("/api/assistant/taste-sharing", json={"enabled": True})
    r, blob = ask(client, "Who directed Heat?")
    assert "Taste summary" not in blob and r["taste_shared"] is False


def test_too_little_taste_sends_nothing(client):
    like(client, 2)
    client.put("/api/assistant/taste-sharing", json={"enabled": True})
    assert client.get("/api/assistant/taste-sharing").json()["summary"] is None
    r, blob = ask(client)
    assert "Taste summary" not in blob and r["taste_shared"] is False


def test_turning_it_off_stops_it(client):
    like(client)
    client.put("/api/assistant/taste-sharing", json={"enabled": True})
    client.put("/api/assistant/taste-sharing", json={"enabled": False})
    _, blob = ask(client)
    assert "Taste summary" not in blob


def test_only_plain_words_pass_the_filter():
    assert taste._safe(["Thriller", "Science Fiction", None, "Sci-Fi & Fantasy", "Drama 2", "<b>x</b>", "a" * 40]) == \
        ["Thriller", "Science Fiction", "Sci-Fi & Fantasy"]
