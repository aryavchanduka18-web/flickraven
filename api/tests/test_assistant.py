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
    def __init__(self, reply, status_code=200, provider_status=None):
        self._reply = reply
        self.status_code = status_code
        self.provider_status = provider_status

    def json(self):
        if self.status_code != 200:
            return {"error": {"code": self.status_code, "status": self.provider_status, "message": self._reply}}
        return {"candidates": [{"content": {"parts": [{"text": self._reply}]}}]}


@pytest.fixture
def client(monkeypatch, test_engine):
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    monkeypatch.setattr(s, "gemini_model", "gemini-3.5-flash-lite")
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
    assert "models/gemini-3.5-flash-lite:generateContent" in sent["url"]
    assert sent["body"]["generationConfig"] == {"maxOutputTokens": 1500, "temperature": 0.7}
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


def test_transient_gemini_error_is_retried_once(client, monkeypatch):
    responses = [FakeResp("temporarily unavailable", 503, "UNAVAILABLE"),
                 FakeResp("Try [[Assistant Test Film (2012)]].")]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(True)
        return responses.pop(0)

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    r = ask(client)

    assert r.status_code == 200
    assert len(calls) == 2
    assert r.json()["remaining"] == 2


def test_provider_configuration_error_is_identified_and_refunded(client, monkeypatch, caplog):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(True)
        return FakeResp("model access denied", 403, "PERMISSION_DENIED")

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    before = client.get("/api/assistant/status").json()["remaining"]
    r = ask(client)

    assert r.status_code == 502
    assert "configuration update" in r.json()["detail"]
    assert len(calls) == 1
    assert client.get("/api/assistant/status").json()["remaining"] == before
    assert "PERMISSION_DENIED" in caplog.text
    assert "test-key" not in caplog.text


def test_gemini_call_leaves_room_for_the_answer(monkeypatch):
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}

    def fake_post(url, json=None, **kw):
        seen.update(json)
        return R()

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    assert ai.ask_gemini([{"role": "user", "text": "hello"}], "sys") == "hi"
    assert seen["generationConfig"]["maxOutputTokens"] >= 1000


def test_unknown_model_id_falls_back_to_the_next_and_is_remembered(monkeypatch):
    monkeypatch.setattr(ai, "_working_model", None)
    urls = []

    class R:
        def __init__(self, code): self.status_code = code
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def fake_post(url, **kw):
        urls.append(url)
        return R(404 if "3.5-flash-lite" in url else 200)

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    assert ai.ask_gemini([{"role": "user", "text": "hi"}], "s") == "ok"
    assert "3.5-flash-lite" in urls[0] and "gemini-2.5-flash:" in urls[1]
    urls.clear()
    assert ai.ask_gemini([{"role": "user", "text": "hi"}], "s") == "ok"
    assert len(urls) == 1 and "gemini-2.5-flash:" in urls[0]          # remembered, no second 404
    monkeypatch.setattr(ai, "_working_model", None)


def test_loosely_spelled_title_still_gets_its_catalog_facts(test_engine):
    from sqlalchemy import text as t
    from app.db import SessionLocal
    with test_engine.begin() as conn:
        mid = conn.execute(t("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, popularity_score,
            tmdb_vote_count, title_type, overview) VALUES (990500, 'It''s Okay to Not Be Okay', 2020, 'ko', ARRAY['KR'], '/b.jpg', 8, 5000,
            'series', 'A caretaker and a writer heal each other.') RETURNING id""")).scalar()
    try:
        with SessionLocal() as db:
            facts = ai.named_titles(db, "what about its ok to not be o k drama")
            assert "A caretaker and a writer heal each other." in facts and "series, language ko" in facts
            assert ai.named_titles(db, "recommend me something warm for the weekend") == ""
    finally:
        with test_engine.begin() as conn:
            conn.execute(t("DELETE FROM movies WHERE id = :i"), {"i": mid})


def test_assistant_rules_forbid_catalog_talk_and_kind_switching():
    assert "never tell the person that FlickRaven does not have a title" in ai.SYSTEM
    assert "Never answer a series request with a film" in ai.SYSTEM


def test_assistant_answers_freely_about_any_title_and_stays_on_topic():
    assert "from your own knowledge" in ai.SYSTEM and "whether or not FlickRaven lists it" in ai.SYSTEM
    assert "Stay on films, series, anime" in ai.SYSTEM
    assert "never tell the person that FlickRaven does not" in ai.SYSTEM.replace("\\\n", "")
    assert "||" in ai.SYSTEM                                     # spoilers stay hidden behind a tap


def test_titles_outside_the_catalog_are_simply_not_linked(client):
    from app.db import SessionLocal
    with SessionLocal() as db:
        assert ai.resolve_titles(db, "Try [[A Show That Does Not Exist At All (1999)]].") == []


def test_no_taste_profile_or_history_is_sent_and_disliked_titles_are_never_linked(client, test_engine, monkeypatch):
    """Aryav 2026-11-11: ratings, likes, dislikes, Taste DNA and history stay inside FlickRaven (free Gemini tier)."""
    with test_engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('ai-priv@example.com', 'x', 'x', false) RETURNING id")).scalar()
        mid = conn.execute(text("SELECT id FROM movies WHERE tmdb_id = 990900")).scalar()
        conn.execute(text("INSERT INTO reactions (user_id, movie_id, value) VALUES (:u, :m, -1)"), {"u": uid, "m": mid})
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "ai-priv@example.com", "display_name": "x", "is_guest": False}
    try:
        r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend a film please"}]}).json()
        blob = json.dumps(client.sent[-1]["body"])
        assert "Taste summary" not in blob and "rated highly" not in blob
        assert r["items"] == []                       # Gemini named the disliked film; FlickRaven does not link it
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM reactions WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


def test_request_intent_is_read_locally_and_japanese_is_not_anime():
    from app.services import assistant_context as ctx
    assert ctx.intent("any good Japanese shows?") == {"kinds": ["series"], "languages": ["ja"], "genres": []}
    assert ctx.intent("suggest an anime like Death Note")["kinds"] == ["anime"]
    assert ctx.intent("funny Hindi series")["languages"] == ["hi"] and ctx.intent("funny Hindi series")["genres"] == ["Comedy"]
    assert ctx.intent("something to watch tonight")["kinds"] == ["movie", "series"]
    assert ctx.wants_suggestions("what should I watch next") and not ctx.wants_suggestions("who directed Heat?")


def test_shortlist_follows_the_engine_filters_the_request_and_drops_blocked_titles():
    import numpy as np
    from types import SimpleNamespace
    from app.services import assistant_context as ctx
    cat = SimpleNamespace(kind=["movie", "series", "series", "series"], language=["en", "hi", "en", "hi"],
                          genres=[["Drama"], ["Comedy"], ["Comedy"], ["Drama"]], titles=["F", "A", "B", "C"],
                          year=np.array([2000.0, 2001.0, np.nan, 2003.0]))
    engine = SimpleNamespace(cat=cat, kind_rank=lambda st, kind: (np.array([2, 1, 3]), np.array([0.9, 0.8, 0.7])),
                             rail_scores=lambda st: np.array([1.0, -np.inf, -np.inf, -np.inf]))
    want = {"kinds": ["series"], "languages": ["hi"], "genres": []}
    assert ctx.shortlist(engine, None, want, blocked_rows=set()) == [1, 3]
    assert ctx.shortlist(engine, None, want, blocked_rows={1}) == [3]
    assert ctx.shortlist(engine, None, {"kinds": ["series"], "languages": ["fr"], "genres": []}, set()) == [2, 1, 3]   # nothing fits: unfiltered
    text_ = ctx.shortlist_prompt(engine, [1, 2])
    assert "A (2001, series, language hi, Comedy)" in text_ and "B (series" in text_


def test_like_x_requests_lead_with_x_and_keep_the_persons_exclusions():
    import numpy as np
    from types import SimpleNamespace
    from cinematch_engine.online import UserState
    from app.services import assistant_context as ctx
    cat = SimpleNamespace(titles=["Death Note", "Death Note", "Up"], votes=np.array([10.0, 99.0, 5.0]))
    engine = SimpleNamespace(cat=cat)
    assert ctx.named_row(engine, "something like death note please") == 1          # the better-known of the two
    assert ctx.named_row(engine, "pick me something, cheer me up") is None          # short words never match
    st = UserState(ratings={5: 9.0, 6: 3.0}, likes={7}, dislikes={8}, watched={9})
    s2 = ctx.like_state(st, 1)
    assert s2.likes == {1} and s2.ratings == {6: 3.0} and s2.dislikes == {8} and s2.watched == {9}
