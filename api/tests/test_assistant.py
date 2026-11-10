"""AI assistant: caps, off switch, grounding, privacy and spoiler handling (Gemini is faked)."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import current_user
from app.config import get_settings
from app.main import app
from app.services import assistant as ai


class FakeResp:
    status_code = 200

    def __init__(self, reply):
        self._reply = reply

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._reply}]}}]}


@pytest.fixture
def client(monkeypatch, test_engine):
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    monkeypatch.setattr(s, "assistant_enabled", True)
    monkeypatch.setattr(s, "assistant_daily_cap", 3)
    monkeypatch.setattr(s, "assistant_guest_cap", 1)
    ai._used.clear()
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append({"url": url, "body": json, "headers": headers})
        return FakeResp("Try [[Assistant Test Film (2012)]]. ||The ending: he wakes up.|| Also [[Not In Catalog (1999)]].")
    monkeypatch.setattr(ai.httpx, "post", fake_post)
    with test_engine.begin() as conn:
        conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, popularity_score,
            tmdb_vote_count, title_type, overview) VALUES (990900, 'Assistant Test Film', 2012, 'en', ARRAY['US'], '/b.jpg', 7, 5000, 'movie',
            'A dreamer fights a machine.')"""))
    app.dependency_overrides[current_user] = lambda: {"id": 987654, "email": "secret@example.com", "display_name": "Secret Name", "is_guest": False}
    with TestClient(app) as c:
        c.sent = sent
        yield c
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE tmdb_id = 990900"))


def ask(c, q="Suggest something like Assistant Test Film"):
    return c.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": q}]})


def test_reply_links_only_catalog_titles_and_keeps_spoiler_marks(client):
    r = ask(client).json()
    assert [i["movie"]["title"] for i in r["items"]] == ["Assistant Test Film"]        # the made-up title is not linked
    assert "||The ending: he wakes up.||" in r["reply"]
    assert r["remaining"] == 2


def test_nothing_personal_is_sent_and_catalog_facts_are_added(client):
    ask(client)
    sent = client.sent[0]
    blob = json.dumps(sent["body"])
    assert "secret@example.com" not in blob and "Secret Name" not in blob
    assert "A dreamer fights a machine." in blob                                       # catalog synopsis for the named title
    assert sent["headers"]["x-goog-api-key"] == "test-key" and "test-key" not in sent["url"]


def test_daily_cap_and_off_switch(client, monkeypatch):
    for _ in range(3):
        assert ask(client).status_code == 200
    assert ask(client).status_code == 429
    assert client.get("/api/assistant/status").json()["remaining"] == 0
    monkeypatch.setattr(get_settings(), "assistant_enabled", False)
    assert client.get("/api/assistant/status").json()["enabled"] is False
    assert ask(client).status_code == 503


def test_long_messages_are_cut_and_empty_ones_refused(client):
    ask(client, "x" * 5000)
    assert len(client.sent[0]["body"]["contents"][-1]["parts"][0]["text"]) == ai.MAX_CHARS
    assert client.post("/api/assistant/chat", json={"messages": []}).status_code == 422


def test_a_failed_gemini_call_does_not_use_up_a_message(client, monkeypatch):
    def boom(url, json=None, headers=None, timeout=None):
        raise ai.httpx.ConnectError("down")
    monkeypatch.setattr(ai.httpx, "post", boom)
    before = client.get("/api/assistant/status").json()["remaining"]
    r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "hi"}]})
    assert r.status_code == 502
    assert client.get("/api/assistant/status").json()["remaining"] == before
