"""Series More Like This is helped by Gemini names, kept only when they exist in the catalog."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.routers import catalog as catalog_router
from app.services import ai_similar as ai


def test_parse_reads_title_year_lines_only():
    reply = "1. **Sex Education (2019)**\n- Ginny & Georgia (2021)\nHere you go!\n[[Heartstopper (2022)]]\nSex Education (2019)"
    assert ai.parse(reply) == [("Sex Education", 2019), ("Ginny & Georgia", 2021), ("Heartstopper", 2022)]


@pytest.fixture
def titles(test_engine):
    ids = {}
    with test_engine.begin() as conn:
        for n, (name, kind, year) in enumerate([("AIS Anchor", "series", 2020), ("AIS Friend", "series", 2019),
                                                ("AIS Film", "movie", 2019), ("AIS Other", "series", 2021)]):
            ids[name] = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, :y, 'en', ARRAY['US'], '/b.jpg', 8, 1000, :k) RETURNING id"""),
                                     {"t": 990400 + n, "n": name, "y": year, "k": kind}).scalar()
    yield ids
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": list(ids.values())})


def test_resolve_keeps_only_catalog_titles_of_the_same_kind(test_engine, titles):
    from app.db import SessionLocal
    with SessionLocal() as db:
        got = ai.resolve(db, [("AIS Film", 2019), ("Not In Catalog", 2020), ("AIS Friend", 2019), ("AIS Anchor", 2020), ("AIS Other", 2030)],
                         ["series", "anime"], titles["AIS Anchor"])
    assert got == [titles["AIS Friend"]]          # film, unknown, the anchor itself and a wrong year are all dropped


def test_suggest_is_off_without_a_key_and_cached_and_capped(test_engine, titles, monkeypatch):
    from app.db import SessionLocal
    ai._cache.clear(); ai._calls.clear()
    calls = []
    monkeypatch.setattr(ai.assistant, "ask_gemini", lambda h, s, timeout=25: calls.append(1) or "AIS Friend (2019)")
    s = ai.get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "")
    with SessionLocal() as db:
        assert ai.suggest(db, titles["AIS Anchor"], "AIS Anchor", 2020, [], "series") == [] and not calls
        monkeypatch.setattr(s, "gemini_api_key", "k")
        assert ai.suggest(db, titles["AIS Anchor"], "AIS Anchor", 2020, [], "series") == [titles["AIS Friend"]]
        assert ai.suggest(db, titles["AIS Anchor"], "AIS Anchor", 2020, [], "series") == [titles["AIS Friend"]]
        assert len(calls) == 1                     # second answer came from the cache
        ai._cache.clear()
        monkeypatch.setattr(s, "ai_similar_daily_cap", 1)
        assert ai.suggest(db, titles["AIS Anchor"], "AIS Anchor", 2020, [], "series") == []   # daily cap reached
    ai._cache.clear(); ai._calls.clear()


def test_gemini_failure_never_breaks_the_page_list(test_engine, titles, monkeypatch):
    from app.db import SessionLocal
    ai._cache.clear(); ai._calls.clear()
    def boom(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(ai.assistant, "ask_gemini", boom)
    monkeypatch.setattr(ai.get_settings(), "gemini_api_key", "k")
    with SessionLocal() as db:
        assert ai.suggest(db, titles["AIS Anchor"], "AIS Anchor", 2020, [], "series") == []
    ai._cache.clear(); ai._calls.clear()


def test_series_page_puts_gemini_picks_first_then_the_stored_list(test_engine, titles, monkeypatch):
    a, f, o = titles["AIS Anchor"], titles["AIS Friend"], titles["AIS Other"]

    class Cat:
        row_of = {a: 0, f: 1, o: 2}
        kind = ["series"] * 3; titles = ["AIS Anchor", "f", "o"]; year = np.array([2020.0] * 3); genres = [["Drama"]] * 3
        universe_of_row = [-1, -1, -1]

    class Engine:
        cat = Cat()

    monkeypatch.setattr(catalog_router.rec, "artifacts_ready", lambda: True)
    monkeypatch.setattr(catalog_router.rec, "load_engine", lambda db: Engine())
    monkeypatch.setattr(catalog_router.rec, "match_for", lambda db, uid, ids: {})
    monkeypatch.setattr(catalog_router.similar_svc, "similar_page",
                        lambda db, e, mid, off, lim: ([], {o: {"score": 0.5, "reasons": []}}, 1))
    monkeypatch.setattr(catalog_router.ai_similar, "suggest", lambda *a_, **k: [f])
    with TestClient(app) as c:
        items = c.get(f"/api/movies/{a}/similar").json()["items"]
    got = [i["movie"]["id"] for i in items]
    assert got == [f, o]
    assert items[0]["reasons"][0]["code"] == "ai_similar" and not items[1]["reasons"]
