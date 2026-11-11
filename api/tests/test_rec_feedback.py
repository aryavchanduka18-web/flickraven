"""Feedback on recommendations: Not interested, hidden rows, and Home rows that move from use."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services import rec_feedback as rf


# ---- row learning (pure) -------------------------------------------------------------------
def S(shows, good=0.0, bad=0.0):
    return {"shows": shows, "good": good, "bad": bad}


KEYS = ["rail:top_picks", "rail:a", "rail:b", "rail:c", "rail:d"]


def test_nothing_moves_without_any_good_action():
    assert rf.shifts(KEYS, {k: S(10) for k in KEYS}) == {}
    assert rf.reorder(KEYS, {})[0] == [0, 1, 2, 3, 4]


def test_used_row_moves_up_and_top_picks_stays():
    stats = {"rail:top_picks": S(10, 0), "rail:a": S(10, 0), "rail:b": S(10, 0), "rail:c": S(10, 0), "rail:d": S(10, 12)}
    order, learned = rf.reorder(KEYS, stats)
    assert order[0] == 0                       # pinned
    assert order == [0, 1, 4, 2, 3]            # the used row moved up two places; nothing else moved
    assert learned["rail:d"] == "up"


def test_silence_never_moves_a_row_down():
    """Rows nobody touched stay put, even next to a row that is used a lot (finding 5 of the #113 review)."""
    stats = {"rail:top_picks": S(10, 0), "rail:a": S(40, 0), "rail:b": S(40, 0), "rail:c": S(40, 0), "rail:d": S(10, 12)}
    move = rf.shifts(KEYS, stats)
    assert all(v > 0 for v in move.values())
    assert "rail:a" not in move and "rail:b" not in move and "rail:c" not in move
    _, learned = rf.reorder(KEYS, stats)
    assert "down" not in learned.values()


def test_few_showings_do_not_move_a_row():
    stats = {"rail:a": S(10, 3), "rail:d": S(2, 5)}
    assert "rail:d" not in rf.shifts(KEYS, stats)


def test_explicit_negatives_move_a_row_down():
    stats = {"rail:a": S(10, 6, 0), "rail:b": S(10, 1, 3), "rail:c": S(10, 6, 0), "rail:d": S(10, 0, 5)}
    move = rf.shifts(KEYS, stats)
    assert move["rail:b"] == -1 and move["rail:d"] == -2
    assert "rail:top_picks" not in move


def test_one_negative_is_not_enough():
    assert rf.shifts(KEYS, {"rail:a": S(10, 0, 1)}) == {}


def test_base_key():
    assert rf.base_key("rail:because:12") == "rail:because"
    assert rf.base_key("collection:rom-com") == "collection:rom-com"
    assert rf.base_key("because:12") == "because"


# ---- routes ----------------------------------------------------------------------------------
@pytest.fixture()
def film(test_engine):
    with test_engine.begin() as conn:
        mid = conn.execute(text("INSERT INTO movies (tmdb_id, title, year, original_language) VALUES (960001, 'Meh Film', 2005, 'en') RETURNING id")).scalar()
    yield mid
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = :i"), {"i": mid})


def test_not_interested_is_not_a_dislike_and_can_be_undone(film):
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        assert c.put(f"/api/feedback/not-interested/{film}", json={"source": "rail:because"}).json()["ok"]
        items = c.get("/api/feedback/not-interested").json()["items"]
        assert [i["movie"]["id"] for i in items] == [film]
        assert items[0]["user_state"]["not_interested"] is True
        assert items[0]["user_state"]["reaction"] == 0           # not a dislike
        me = c.get("/api/me").json()
        assert c.get("/api/me").status_code == 200 and me is not None
        assert c.delete(f"/api/feedback/not-interested/{film}").json()["ok"]
        assert c.get("/api/feedback/not-interested").json()["items"] == []


def test_liking_a_not_interested_title_ends_the_hide(film):
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        c.put(f"/api/feedback/not-interested/{film}")
        c.put(f"/api/reactions/{film}", json={"value": 1})
        assert c.get("/api/feedback/not-interested").json()["items"] == []


def test_hide_and_restore_rows_and_top_picks_is_protected():
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        assert c.put("/api/feedback/rows", json={"source": "rail:top_picks"}).status_code == 422
        r = c.put("/api/feedback/rows", json={"source": "rail:because:77"}).json()
        assert r["hidden_rows"] == ["rail:because"]
        assert c.get("/api/feedback/rows").json()["hidden_rows"] == ["rail:because"]
        assert c.delete("/api/feedback/rows").json()["restored"] == 1
        assert c.get("/api/feedback/rows").json()["hidden_rows"] == []


def test_row_stats_count_showings_and_actions(film, test_engine):
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        uid = c.get("/api/me").json()["id"]
        with test_engine.begin() as conn:
            for i in range(3):
                conn.execute(text("INSERT INTO recommendation_logs (request_id, user_id, surface, movie_id) VALUES (gen_random_uuid(), :u, 'because:1', :m)"), {"u": uid, "m": film})
        c.put(f"/api/reactions/{film}", json={"value": 1, "source": "rail:because"})
        with test_engine.connect() as conn:
            from sqlalchemy.orm import Session
            stats = rf.row_stats(Session(bind=conn), uid)
        assert stats["rail:because"] == {"shows": 3, "good": 1.0, "bad": 0.0}


# ---- the fixes from the #113 review ----------------------------------------------------------
ACTIONS = [("put", "/ratings/{m}", {"rating": 8}), ("delete", "/ratings/{m}", None),
           ("put", "/reactions/{m}", {"value": 1}), ("delete", "/reactions/{m}", None),
           ("put", "/list/{m}", {}), ("delete", "/list/{m}", None),
           ("put", "/watched/{m}", {}), ("delete", "/watched/{m}", None)]


def test_every_action_carries_its_source(film, test_engine):
    """Row learning credits an action to the row it came from, so no action endpoint may drop the source."""
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        uid = c.get("/api/me").json()["id"]
        for method, path, body in ACTIONS:
            url = "/api" + path.format(m=film)
            if method == "put":
                r = c.put(url, json={**(body or {}), "source": "rail:because"})
            else:
                r = c.delete(url + "?source=rail:because")
            assert r.status_code == 200, (method, path)
        with test_engine.connect() as conn:
            sources = conn.execute(text("SELECT event_type, source FROM interactions WHERE user_id = :u AND movie_id = :m"),
                                   {"u": uid, "m": film}).all()
    missing = [e for e, s in sources if s != "rail:because"]
    assert not missing, f"events without a source: {missing}"
    assert {"watched", "unwatched", "list_remove", "unrate", "clear_reaction"} <= {e for e, _ in sources}


def test_hero_never_falls_back_to_hidden_titles():
    entry = lambda r: {"row": r, "score": 1.0}
    plan = {"hero": [entry(1), entry(2), entry(3)],
            "rails": [{"key": "top_picks", "rows": [10, 11, 12], "scored": {10: entry(10), 11: entry(11), 12: entry(12)}}]}
    # one hidden: the next best Top Pick fills the place, and is not repeated in the rows
    rows, skip = rf.hero_without_hidden(plan, {2})
    assert [e["row"] for e in rows] == [1, 3, 10] and 10 in skip
    # every hero title hidden: refilled from Top Picks, never the original list
    rows, _ = rf.hero_without_hidden(plan, {1, 2, 3})
    assert [e["row"] for e in rows] == [10, 11, 12]
    # everything hidden: the hero is empty, the hidden titles do not return
    rows, _ = rf.hero_without_hidden(plan, {1, 2, 3, 10, 11, 12})
    assert rows == []
