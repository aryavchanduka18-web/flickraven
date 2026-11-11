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


def test_shipped_file_answers_without_any_gemini_call(test_engine, titles, monkeypatch):
    from app.db import SessionLocal
    with SessionLocal() as db:
        tmdb = db.execute(text("SELECT tmdb_id FROM movies WHERE id = :i"), {"i": titles["AIS Anchor"]}).scalar()
    monkeypatch.setattr(ai, "_file", {str(tmdb): ["AIS Friend (2019)", "Unknown Show (2020)", "AIS Film (2019)"]})
    ai._file_ids.clear(); ai._cache.clear()
    def boom(*a, **k): raise AssertionError("Gemini must not be called")
    monkeypatch.setattr(ai.assistant, "ask_gemini", boom)
    monkeypatch.setattr(ai.get_settings(), "gemini_api_key", "k")
    with SessionLocal() as db:
        assert ai.suggest(db, titles["AIS Anchor"], "AIS Anchor", 2020, [], "series") == [titles["AIS Friend"]]
    ai._file_ids.clear()


def test_signed_in_user_never_gets_a_gemini_pick_they_dislike_and_taste_reorders_the_rest(test_engine, titles, monkeypatch):
    a, f, o, fi = titles["AIS Anchor"], titles["AIS Friend"], titles["AIS Other"], titles["AIS Film"]

    class Cat:
        row_of = {a: 0, f: 1, o: 2, fi: 3}
        kind = ["series"] * 4; titles = ["a", "f", "o", "fi"]; year = np.array([2020.0] * 4); genres = [["Drama"]] * 4
        universe_of_row = [-1] * 4

    class Engine:
        cat = Cat()
        def personal_fit(self, st, rows):
            # the user disliked the first Gemini pick (f); of the others, o fits their taste better than fi
            fit = {1: 0.9, 2: 0.9, 3: 0.2}
            return np.array([r != 1 for r in rows]), np.array([fit[r] for r in rows]), True

    monkeypatch.setattr(catalog_router.rec, "artifacts_ready", lambda: True)
    monkeypatch.setattr(catalog_router.rec, "load_engine", lambda db: Engine())
    monkeypatch.setattr(catalog_router.rec, "user_state", lambda db, uid, e: object())
    monkeypatch.setattr(catalog_router.rec, "match_for", lambda db, uid, ids: {})
    monkeypatch.setattr(catalog_router, "user_id_from", lambda request, db: 1)
    monkeypatch.setattr(catalog_router.similar_svc, "similar_page",
                        lambda db, e, mid, off, lim: ([], {fi: {"score": 0.5, "reasons": []}}, 1))
    monkeypatch.setattr(catalog_router.ai_similar, "suggest", lambda *a_, **k: [f, fi, o])   # Gemini's order: f, fi, o
    with TestClient(app) as c:
        got = [i["movie"]["id"] for i in c.get(f"/api/movies/{a}/similar").json()["items"]]
    assert f not in got                     # disliked: never shown just because Gemini named it
    assert got == [o, fi]                   # o fits this person's taste better, so it moves ahead of Gemini's earlier fi


def test_anime_page_keeps_anime_in_the_main_list_and_labels_live_action_separately(test_engine, titles, monkeypatch):
    a, f, o = titles["AIS Anchor"], titles["AIS Friend"], titles["AIS Other"]

    class Cat:
        row_of = {a: 0, f: 1, o: 2}
        kind = ["anime", "series", "anime"]; titles = ["AIS Anchor", "f", "o"]; year = np.array([2020.0] * 3); genres = [["Drama"]] * 3
        universe_of_row = [-1, -1, -1]

    class Engine:
        cat = Cat()

    monkeypatch.setattr(catalog_router.rec, "artifacts_ready", lambda: True)
    monkeypatch.setattr(catalog_router.rec, "load_engine", lambda db: Engine())
    monkeypatch.setattr(catalog_router.rec, "match_for", lambda db, uid, ids: {})
    monkeypatch.setattr(catalog_router.similar_svc, "similar_page",
                        lambda db, e, mid, off, lim: ([], {o: {"score": 0.5, "reasons": []}}, 1))
    monkeypatch.setattr(catalog_router.ai_similar, "suggest", lambda *a_, **k: [f, o])      # f is live-action
    with TestClient(app) as c:
        body = c.get(f"/api/movies/{a}/similar").json()
    assert [i["movie"]["id"] for i in body["items"]] == [o]                  # anime only in the main list
    assert body["cross_kind"]["title"] == "Live-action series in a similar vein"
    assert [i["movie"]["id"] for i in body["cross_kind"]["items"]] == [f]
    with TestClient(app) as c:
        assert "cross_kind" not in c.get(f"/api/movies/{a}/similar?offset=1").json()


@pytest.mark.parametrize("field,value", [("likes", "liked"), ("picks", "picked"), ("in_list", "saved"), ("watched", "watched"),
                                         ("ratings", "rated"), ("dislikes", "disliked")])
def test_cross_kind_row_never_repeats_titles_the_person_already_acted_on(test_engine, titles, monkeypatch, field, value):
    a, f, o = titles["AIS Anchor"], titles["AIS Friend"], titles["AIS Other"]

    class Cat:
        row_of = {a: 0, f: 1, o: 2}
        kind = ["anime", "series", "series"]; titles = ["AIS Anchor", "f", "o"]; year = np.array([2020.0] * 3); genres = [["Drama"]] * 3
        universe_of_row = [-1, -1, -1]

    class State:
        ratings, likes, picks, in_list, watched, dislikes = {}, set(), set(), set(), set(), set()

    st = State()
    setattr(st, field, {1: 8.0} if field == "ratings" else {1})            # row 1 is f, the first live-action suggestion

    class Engine:
        cat = Cat()
        def personal_fit(self, st_, rows):
            return np.ones(len(rows), dtype=bool), np.full(len(rows), 0.5), True

    monkeypatch.setattr(catalog_router.rec, "artifacts_ready", lambda: True)
    monkeypatch.setattr(catalog_router.rec, "load_engine", lambda db: Engine())
    monkeypatch.setattr(catalog_router.rec, "user_state", lambda db, uid, e: st)
    monkeypatch.setattr(catalog_router.rec, "match_for", lambda db, uid, ids: {})
    monkeypatch.setattr(catalog_router, "user_id_from", lambda request, db: 1)
    monkeypatch.setattr(catalog_router.similar_svc, "similar_page", lambda db, e, mid, off, lim: ([], {}, 0))
    monkeypatch.setattr(catalog_router.ai_similar, "suggest", lambda *a_, **k: [f, o])        # both are live-action, a is anime
    with TestClient(app) as c:
        body = c.get(f"/api/movies/{a}/similar").json()
    shown = [i["movie"]["id"] for i in body["cross_kind"]["items"]]
    assert f not in shown and o in shown, value


def test_shipped_files_are_read_as_utf8_whatever_the_machine_default_is(tmp_path, monkeypatch):
    """The laptop (Windows, cp1252 default) failed with "ai_similar.json could not be read": the file is UTF-8 with
    accented titles, and read_text() without an encoding used the machine default."""
    import json
    import pathlib
    from app.services import ai_similar as ai_mod
    from app.services import recommender as rec_mod
    (tmp_path / "ai_similar.json").write_text(json.dumps({"titles": {"1": ["Naruto Shippūden (2007)", "Ōoku (2003)"]}}, ensure_ascii=False), encoding="utf-8")
    real = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, encoding=None, errors=None: real(self, encoding=encoding or "cp1252", errors=errors))
    monkeypatch.setattr(ai_mod, "MODELS", tmp_path)
    monkeypatch.setattr(ai_mod, "_file", None)
    monkeypatch.setattr(ai_mod, "_file_ids", {})
    try:
        ai_mod.precomputed(None, 1, "anime")        # the file is loaded first; the lookup that follows needs a database
    except AttributeError:
        pass
    assert ai_mod._file == {"1": ["Naruto Shippūden (2007)", "Ōoku (2003)"]}
