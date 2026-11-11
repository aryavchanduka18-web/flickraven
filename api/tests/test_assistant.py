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
    assert ctx.intent("any good Japanese shows?")["kinds"] == ["series"] and ctx.intent("any good Japanese shows?")["languages"] == ["ja"]
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
    assert ctx.shortlist(engine, None, {"kinds": ["series"], "languages": ["fr"], "genres": []}, set()) == []   # an asked-for language is never swapped for another
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


# ---- hardening after #101 -------------------------------------------------------------------------------------
from app.services import assistant_context as ctx2

BLOCKED = {"parasite": ["Parasite"], "up": ["Up"], "the dark knight": ["The Dark Knight"], "heat": ["Heat"]}


def test_scrub_removes_blocked_titles_from_marks_and_plain_text_but_keeps_valid_recommendations():
    reply = ("Try [[Inception (2010)]] for twists. You might also enjoy [[Parasite (2019)]].\n"
             "The Dark Knight is great too! Another idea is Heat (1995). Great choices all round.")
    clean, removed = ctx2.scrub_reply(reply, BLOCKED)
    assert removed == 3
    assert "Inception" in clean and "Great choices all round." in clean
    assert "Parasite" not in clean and "Dark Knight" not in clean and "Heat" not in clean


def test_scrub_does_not_touch_ordinary_words_that_are_also_titles():
    clean, removed = ctx2.scrub_reply("Look up the hill. I love the heat of summer. A parasite is an organism.", BLOCKED)
    assert removed == 0 and clean.startswith("Look up the hill.")


def test_scrub_lets_the_person_name_a_title_they_typed_but_never_recommends_it_as_a_card():
    assert ctx2.scrub_reply("You said Parasite was not for you.", BLOCKED, allowed="why did i dislike Parasite")[1] == 0
    assert ctx2.scrub_reply("Maybe [[Parasite (2019)]] again?", BLOCKED, allowed="Parasite")[1] == 1


def test_scrub_with_nothing_left_gives_an_honest_note_not_an_empty_reply():
    clean, removed = ctx2.scrub_reply("[[Parasite (2019)]].", BLOCKED)
    assert removed == 1 and "held back" in clean


def test_a_disliked_or_low_rated_title_in_the_written_reply_is_removed_end_to_end(client, test_engine, monkeypatch):
    with test_engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('ai-scrub@example.com', 'x', 'x', false) RETURNING id")).scalar()
        mid = conn.execute(text("SELECT id FROM movies WHERE tmdb_id = 990900")).scalar()
        conn.execute(text("INSERT INTO ratings (user_id, movie_id, rating) VALUES (:u, :m, 3)"), {"u": uid, "m": mid})
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "ai-scrub@example.com", "display_name": "x", "is_guest": False}
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp("I would suggest Assistant Test Film because it is gripping. A second idea is [[Other Film (2001)]]."))
    try:
        r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend a film please"}]}).json()
        assert "Assistant Test Film" not in r["reply"] and "Other Film" in r["reply"] and r["items"] == []
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM ratings WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


def test_requests_with_negations_are_read_correctly():
    i = ctx2.intent
    t = i("I want a psychological thriller series.")
    assert (t["kinds"], t["languages"], t["genres"], t["exclude_languages"], t["exclude_genres"]) == (["series"], [], ["Thriller"], [], [])
    assert i("Recommend Hindi crime dramas.")["languages"] == ["hi"] and i("Recommend Hindi crime dramas.")["genres"] == ["Crime"]
    j = i("I want Japanese live-action shows, not anime.")
    assert j["kinds"] == ["series"] and j["languages"] == ["ja"] and j["genres"] == []     # "live-action" is not the Action genre
    assert i("Give me a movie, not a series.")["kinds"] == ["movie"]
    assert i("Give me a series, no movies please")["kinds"] == ["series"]
    k = i("I don't want Hindi recommendations.")
    assert k["languages"] == [] and k["exclude_languages"] == ["hi"]
    assert i("something to watch, not anime")["kinds"] == ["movie", "series"]
    assert i("recommend something, no horror")["exclude_genres"] == ["Horror"]
    z = i("not anime, a Japanese series please")
    assert (z["kinds"], z["languages"], z["genres"], z["exclude_kinds"]) == (["series"], ["ja"], [], ["anime"])
    assert i("suggest an anime like Death Note")["kinds"] == ["anime"]


def test_wants_suggestions_covers_common_phrasings_and_not_questions_of_fact():
    w = ctx2.wants_suggestions
    assert all(w(q) for q in ["I want a psychological thriller series.", "Suggest something like Death Note.", "Recommend Hindi crime dramas.",
                              "I want Japanese live-action shows, not anime.", "Give me a movie, not a series.", "I don't want Hindi recommendations."])
    assert not w("I want to know who directed Heat") and not w("who directed Heat?")


def _fake_engine():
    import numpy as np
    from types import SimpleNamespace
    cat = SimpleNamespace(kind=["series"] * 8, language=["en", "hi", "en", "hi", "en", "ko", "en", "en"],
                          genres=[["Drama"], ["Comedy"], ["Comedy"], ["Drama"], ["Crime"], ["Drama"], ["Comedy"], ["Comedy"]],
                          titles=list("ABCDEFGH"), year=np.full(8, 2020.0))
    return SimpleNamespace(cat=cat, kind_rank=lambda st, kind: (np.arange(8), np.linspace(1, 0, 8)))


def test_an_asked_for_language_is_never_replaced_by_other_languages():
    e = _fake_engine()
    got = ctx2.shortlist(e, None, {"kinds": ["series"], "languages": ["hi"], "genres": [], "exclude_languages": [], "exclude_genres": []}, set())
    assert got == [1, 3]                                               # only Hindi, even though fewer than 5
    none = ctx2.shortlist(e, None, {"kinds": ["series"], "languages": ["ta"], "genres": [], "exclude_languages": [], "exclude_genres": []}, set())
    assert none == []
    note = ctx2.shortlist_prompt(e, none, {"languages": ["ta"]})
    assert "no titles of the kind and language" in note and "do not offer titles in other languages" in note
    assert ctx2.shortlist_prompt(e, [], {"languages": []}) == ""


def test_a_genre_is_relaxed_when_too_few_match_but_the_language_is_kept():
    e = _fake_engine()
    got = ctx2.shortlist(e, None, {"kinds": ["series"], "languages": ["hi"], "genres": ["Crime"], "exclude_languages": [], "exclude_genres": []}, set())
    assert got == [1, 3]                                               # no Hindi crime: genre dropped, Hindi kept
    en = ctx2.shortlist(e, None, {"kinds": ["series"], "languages": ["en"], "genres": ["Comedy"], "exclude_languages": [], "exclude_genres": []}, set())
    assert en == [2, 6, 7] or set(en) <= {2, 6, 7, 0, 4}               # 3 English comedies: too few, so English of any genre
    assert all(e.cat.language[r] == "en" for r in en)


def test_ruled_out_language_and_genre_are_removed():
    e = _fake_engine()
    got = ctx2.shortlist(e, None, {"kinds": ["series"], "languages": [], "genres": [], "exclude_languages": ["hi"], "exclude_genres": ["Crime"]}, set())
    assert 1 not in got and 3 not in got and 4 not in got and 0 in got


# ---- review round 2 on #102 -----------------------------------------------------------------------------------
def test_a_negation_does_not_carry_past_but():
    i = ctx2.intent
    a = i("I don't want Hindi, but Korean is fine")
    assert a["exclude_languages"] == ["hi"] and a["languages"] == ["ko"]
    b = i("No horror, but psychological thrillers are fine")
    assert b["exclude_genres"] == ["Horror"] and b["genres"] == ["Thriller"]
    c = i("not anime however a Japanese series would be good")
    assert c["kinds"] == ["series"] and c["languages"] == ["ja"]


def test_a_named_title_cannot_override_an_explicit_kind_or_exclusion():
    w = ctx2.intent("Something like Death Note, but not anime")
    assert w["exclude_kinds"] == ["anime"] and w["kinds"] == ["movie", "series"]
    assert ctx2.kinds_for_named(w, "anime") == ["movie", "series"]                  # Death Note is anime, which was ruled out
    plain = ctx2.intent("something like Death Note please")
    assert ctx2.kinds_for_named(plain, "anime") == ["anime"]                        # nothing said: the title's own kind
    asked = ctx2.intent("a series like Death Note")
    assert ctx2.kinds_for_named(asked, "anime") == ["series"]                       # an asked-for kind wins over the title's


def test_live_action_describes_the_format_and_never_picks_series_on_its_own():
    assert ctx2.intent("Recommend a live-action movie")["kinds"] == ["movie"]
    assert ctx2.intent("Recommend something live-action")["kinds"] == ["movie", "series"]        # and never anime
    assert ctx2.intent("live-action shows please")["kinds"] == ["series"]
    assert ctx2.intent("a live-action thriller")["genres"] == ["Thriller"]                        # not the Action genre


def test_scrub_catches_long_titles_and_titles_with_full_stops():
    long = "The Lord of the Rings The Fellowship of the Ring Extended Edition"
    titles = {"mr. robot": ["Mr. Robot"], long.lower(): [long], "dr. strangelove or how i learned to stop worrying and love the bomb": ["x"]}
    clean, removed = ctx2.scrub_reply(f"Try [[Inception (2010)]]. Mr. Robot is dark. Also {long} is long. Fine.", titles)
    assert removed == 2 and clean == "Try [[Inception (2010)]]. Fine."
    assert ctx2.scrub_reply("See Mr. Robot (2015) for that. Nice.", titles) == ("Nice.", 1)
    assert ctx2.scrub_reply("Dr. Strangelove or How I Learned to Stop Worrying and Love the Bomb is a classic. Fine.", titles) == ("Fine.", 1)
    assert ctx2.scrub_reply("Robot movies are fun. Mr smith is here.", titles)[1] == 0               # parts of a title are not the title


# ---- review round 3 on #102 -----------------------------------------------------------------------------------
def test_a_later_negation_beats_an_earlier_request_for_the_same_kind():
    a = ctx2.intent("I want anime, but not anime. Recommend something else.")
    assert a["kinds"] == ["movie", "series"] and a["exclude_kinds"] == ["anime"] and a["kind_asked"] is False
    b = ctx2.intent("Give me movies and series, but no series.")
    assert b["kinds"] == ["movie"] and b["exclude_kinds"] == ["series"]
    c = ctx2.intent("recommend Hindi shows, but no Hindi")
    assert c["languages"] == [] and c["exclude_languages"] == ["hi"]


def test_scrub_has_no_title_length_cap_for_plain_text_or_dated_mentions():
    words = " ".join(f"Word{n}" for n in range(45))                         # a 45-word blocked title
    titles = {words.lower(): [words]}
    assert ctx2.scrub_reply(f"Try Inception. {words} is long. Fine.", titles) == ("Try Inception. Fine.", 1)
    assert ctx2.scrub_reply(f"Also {words} (2001) maybe. Fine.", titles) == ("Fine.", 1)


def _add_titles(test_engine, rows):
    with test_engine.begin() as conn:
        for n, (name, year, lang, kind) in enumerate(rows):
            conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, popularity_score,
                tmdb_vote_count, title_type) VALUES (:t, :n, :y, :l, ARRAY['IN'], '/b.jpg', 7, 5000, :k)"""),
                         {"t": 990950 + n, "n": name, "y": year, "l": lang, "k": kind})


def _remove_titles(test_engine):
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 990950 AND 990960"))


def test_a_marked_title_in_the_wrong_language_or_kind_is_dropped_from_cards_and_text(client, test_engine, monkeypatch):
    _add_titles(test_engine, [("Hindi Show Zed", 2020, "hi", "series"), ("English Show Zed", 2021, "en", "series"),
                              ("Hindi Film Zed", 2019, "hi", "movie")])
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp(
        "Start with [[Hindi Show Zed (2020)]]. Also try [[English Show Zed (2021)]] for fun. And [[Hindi Film Zed (2019)]] is a film. "
        "Enjoy."))
    try:
        r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend Hindi series"}]}).json()
        assert [i["movie"]["title"] for i in r["items"]] == ["Hindi Show Zed"]
        assert "English Show Zed" not in r["reply"] and "Hindi Film Zed" not in r["reply"]
        assert "Hindi Show Zed" in r["reply"] and "Enjoy." in r["reply"]
    finally:
        _remove_titles(test_engine)


def test_a_title_in_a_ruled_out_language_is_dropped_and_questions_of_fact_are_not_filtered(client, test_engine, monkeypatch):
    _add_titles(test_engine, [("Hindi Show Zed", 2020, "hi", "series"), ("English Show Zed", 2021, "en", "series")])
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp("Try [[Hindi Show Zed (2020)]]. Or [[English Show Zed (2021)]]."))
    try:
        r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Suggest a series, I don't want Hindi"}]}).json()
        assert [i["movie"]["title"] for i in r["items"]] == ["English Show Zed"]
        q = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Compare Hindi Show Zed with English Show Zed"}]}).json()
        assert len(q["items"]) == 2                         # a question of fact is not a suggestion request: no filtering
    finally:
        _remove_titles(test_engine)


# ---- review round 4 on #102 -----------------------------------------------------------------------------------
def test_a_kind_inferred_from_a_named_title_is_enforced_on_geminis_answer(client, test_engine, monkeypatch):
    _add_titles(test_engine, [("Zed Note", 2006, "ja", "anime"), ("Zed Anime Two", 2010, "ja", "anime"), ("Zed Thriller Film", 2012, "en", "movie")])
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp("Try [[Zed Anime Two (2010)]]. Or maybe [[Zed Thriller Film (2012)]] for suspense. Enjoy."))
    try:
        r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend something like Zed Note"}]}).json()
        assert [i["movie"]["title"] for i in r["items"]] == ["Zed Anime Two"]
        assert "Zed Thriller Film" not in r["reply"] and "Enjoy." in r["reply"]
        # said outright "not anime": the title does not pull the request into anime
        r2 = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend something like Zed Note, but not anime"}]}).json()
        assert [i["movie"]["title"] for i in r2["items"]] == ["Zed Thriller Film"]
        # a kind the person asked for wins over the title's kind
        r3 = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend a movie like Zed Note"}]}).json()
        assert [i["movie"]["title"] for i in r3["items"]] == ["Zed Thriller Film"]
    finally:
        _remove_titles(test_engine)


def test_a_dotted_title_rejected_for_language_cannot_slip_through_the_sentence_splitter(client, test_engine, monkeypatch):
    _add_titles(test_engine, [("Mr. Zed Robot", 2015, "en", "series"), ("Hindi Show Zed", 2020, "hi", "series")])
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp("Start with [[Hindi Show Zed (2020)]]. Also [[Mr. Zed Robot (2015)]] is tense. Enjoy."))
    try:
        r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "text": "Recommend Hindi series"}]}).json()
        assert [i["movie"]["title"] for i in r["items"]] == ["Hindi Show Zed"]
        assert "Robot" not in r["reply"] and "Enjoy." in r["reply"]
    finally:
        _remove_titles(test_engine)
    assert ctx2.scrub_reply("Also [[Mr. Robot (2015)]] is tense. Enjoy.", {}, "", {"mr. robot"}) == ("Enjoy.", 1)


def test_chat_cards_report_my_list_state_and_an_assistant_add_is_a_normal_list_add(client, test_engine):
    """The chat's + My List button relies on each card's user_state.in_list, and adds through PUT /api/list/{id}
    with source 'assistant'. Nothing about the list is sent to Gemini."""
    with test_engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('ai-list@example.com', 'x', 'x', false) RETURNING id")).scalar()
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "ai-list@example.com", "display_name": "x", "is_guest": False}
    try:
        first = ask(client).json()["items"][0]
        assert first["user_state"]["in_list"] is False
        mid = first["movie"]["id"]
        assert client.put(f"/api/list/{mid}", json={"source": "assistant"}).status_code == 200
        assert client.put(f"/api/list/{mid}", json={"source": "assistant"}).status_code == 200    # a double add is harmless
        assert ask(client).json()["items"][0]["user_state"]["in_list"] is True
        with test_engine.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM user_movie_list WHERE user_id = :u AND movie_id = :m"), {"u": uid, "m": mid}).scalar() == 1
            assert conn.execute(text("""SELECT count(*) FROM interactions WHERE user_id = :u AND movie_id = :m
                AND event_type = 'list_add' AND source = 'assistant'"""), {"u": uid, "m": mid}).scalar() == 2
        sent = json.dumps(client.sent[-1]["body"])
        assert "in_list" not in sent and "user_state" not in sent and "My List" not in sent
    finally:
        with test_engine.begin() as conn:
            for t in ("user_movie_list", "interactions"):
                conn.execute(text(f"DELETE FROM {t} WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


def test_taste_dna_reorders_series_candidates_on_our_side_and_keeps_every_hard_rule():
    import numpy as np
    from types import SimpleNamespace
    from app.services import assistant_context as ctx
    n = 8
    cat = SimpleNamespace(kind=["series"] * n, language=["en"] * n, genres=[["Drama"]] * n, titles=list("ABCDEFGH"),
                          year=np.full(n, 2020.0))
    engine = SimpleNamespace(cat=cat, kind_rank=lambda st, kind: (np.arange(n), np.zeros(n)))      # engine order: 0, 1, 2 ...
    want = {"kinds": ["series"], "languages": [], "genres": []}
    plain = ctx.shortlist(engine, None, want, set(), n=3)
    assert plain == [0, 1, 2]
    fit = {r: (1.0 if r in (3, 4) else 0.0) for r in range(n)}                      # Taste DNA loves two middle-ranked ones
    got = ctx.shortlist(engine, None, want, {4}, n=3, dna=lambda rows: {r: fit[r] for r in rows})
    assert got[0] == 3 and 4 not in got and len(got) == 3                              # reordered by DNA; the blocked title stays out
    # too little DNA evidence: the engine order stands
    assert ctx.shortlist(engine, None, want, set(), n=3, dna=lambda rows: {6: 1.0}) == [0, 1, 2]
    # films keep the hybrid rail score; DNA is for series and anime
    movie_engine = SimpleNamespace(cat=SimpleNamespace(kind=["movie"] * n, language=["en"] * n, genres=[["Drama"]] * n, titles=list("ABCDEFGH"),
                                                       year=np.full(n, 2020.0)), rail_scores=lambda st: np.arange(n)[::-1].astype(float))
    assert ctx.shortlist(movie_engine, None, {"kinds": ["movie"], "languages": [], "genres": []}, set(), n=3,
                         dna=lambda rows: pytest.fail("films must not use DNA")) == [0, 1, 2]


def test_taste_labels_name_only_traits_the_title_really_shows_and_stay_off_the_reply(monkeypatch):
    from types import SimpleNamespace
    from app.services import assistant_context as ctx
    from app.services import taste_dna as dna
    monkeypatch.setattr(dna, "title_vectors", lambda db, ids: {1: {"dark": 0.9, "humour": 0.1}, 2: None})
    monkeypatch.setattr(dna, "fit", lambda prof, v: (0.5, ["dark"]) if v else (None, []))
    got = ctx.dna_reasons(None, SimpleNamespace(), [1, 2])
    assert list(got) == [1] and got[1]["reasons"][0]["text"] == "Fits your Taste DNA: dark, atmospheric tone."
    assert ctx.dna_reasons(None, None, [1]) == {}


def test_chat_uses_taste_dna_locally_and_sends_none_of_it_to_gemini(client, monkeypatch):
    from types import SimpleNamespace
    from app.routers import assistant as router
    from app.services import assistant_context as ctx
    monkeypatch.setattr(router, "taste_profile", lambda db, uid: SimpleNamespace(marker="PRIVATE"))
    monkeypatch.setattr(ctx, "dna_reasons", lambda db, prof, ids: {i: {"reasons": [{"code": "taste_dna", "text": "Fits your Taste DNA: humour.",
                                                                                     "source": "taste_dna", "share": 0.0, "anchor_movie_id": None}]} for i in ids})
    r = ask(client, "Recommend a film please").json()
    assert r["items"] and r["items"][0]["reasons"][0]["text"] == "Fits your Taste DNA: humour."
    blob = json.dumps(client.sent[-1]["body"])
    assert "Taste DNA" not in blob and "humour" not in blob and "PRIVATE" not in blob
    assert "Taste DNA" not in r["reply"]               # the chat history is sent back to Gemini, so the label never goes in the text
