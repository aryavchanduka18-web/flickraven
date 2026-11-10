"""Recommendation report: attribution rules, minimum samples, Match % ranges, statements only with enough data."""
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services.report import summarize, wilson


def row(rating, match=80, genres=("Drama",), n=0, **kw):
    base = {"rating": rating, "match_pct": match, "genres": list(genres), "opened": True, "watched": False, "known_before": False,
            "shown_at": datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(hours=n), "surface": "top_picks"}
    return {**base, **kw}


def test_too_few_ratings_shows_counts_only():
    out = summarize([row(9, n=i) for i in range(4)] + [row(None, n=9)])
    assert out["ready"] is False and out["rated"] == 4 and out["shown"] == 5 and "positive_pct" not in out


def test_unrated_and_known_titles_are_never_counted():
    rows = [row(9, n=i) for i in range(10)] + [row(None, n=20 + i) for i in range(30)] + [row(2, known_before=True)]
    out = summarize(rows)
    assert out["ready"] and out["rated"] == 10 and out["shown"] == 40 and out["positive_pct"] == 100   # 30 unrated are not dislikes


def test_numbers_buckets_and_statements():
    rows = [row(9, 92, ["Mystery"], i) for i in range(6)] + [row(4, 72, ["Action"], 10 + i) for i in range(4)] + \
           [row(8, 85, ["Mystery"], 20 + i) for i in range(10)]
    out = summarize(rows, Counter({"predictable": 3}), Counter({"exactly": 2}))
    assert out["ready"] and out["rated"] == 20 and out["positive_pct"] == 80 and out["avg_rating"] == 7.5
    by = {b["label"]: b for b in out["buckets"]}
    assert by["90% and up"]["n"] == 6 and by["90% and up"]["enough"] and by["70-80%"]["n"] == 4 and not by["70-80%"]["enough"]
    assert any("80-90%" in s and "10 you rated" in s for s in out["statements"])         # 10 ratings: quotable
    assert not any("90% and up" in s for s in out["statements"])                         # only 6: not quoted
    assert out["best_genres"][0]["genre"] == "Mystery" and out["missed_genres"][0]["genre"] == "Action"
    assert out["top_reasons"] == [{"reason": "too predictable", "n": 3}] and out["feedback"][0]["label"] == "Exactly what I wanted"
    assert out["trend"]["earlier"]["n"] == 10 and out["trend"]["later"]["n"] == 10
    assert "higher" in out["ranking_note"].lower()


def test_small_samples_make_no_trend_and_wide_intervals():
    assert summarize([row(8, n=i) for i in range(12)])["trend"] is None
    lo, hi = wilson(4, 5)
    assert hi - lo > 40                                                                  # 4 of 5 is not "80%" with confidence
    assert wilson(0, 0) == (0, 0)


# ------------------------------------------------------------------ the endpoint's attribution rules
@pytest.fixture()
def world(test_engine):
    with test_engine.begin() as conn:
        ids = [conn.execute(text("INSERT INTO movies (tmdb_id, title) VALUES (:t, :n) RETURNING id"), {"t": 980000 + i, "n": f"Rec {i}"}).scalar()
               for i in range(5)]
    yield ids
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})


def test_report_attribution_rules(world, test_engine, monkeypatch):
    monkeypatch.setattr("app.services.report.MIN_RATED", 1)               # let the single valid outcome through
    shown_first, after_edit, known, imported, never_rated = world
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        uid = c.get("/api/me").json()["id"]
        t0 = datetime.now(timezone.utc) - timedelta(days=3)
        with test_engine.begin() as conn:
            def shown(m, at, pct):
                conn.execute(text("INSERT INTO recommendation_logs (user_id, movie_id, surface, match_pct, created_at) VALUES (:u, :m, 'top_picks', :p, :t)"),
                             {"u": uid, "m": m, "p": pct, "t": at})

            def rate(m, at, v, source=None):
                conn.execute(text("INSERT INTO interactions (user_id, movie_id, event_type, value, source, created_at) VALUES (:u, :m, 'rate', :v, :s, :t)"),
                             {"u": uid, "m": m, "v": v, "s": source, "t": at})
            shown(shown_first, t0, 90); shown(shown_first, t0 + timedelta(hours=5), 50)        # first exposure: 90%
            rate(shown_first, t0 + timedelta(hours=1), 9); rate(shown_first, t0 + timedelta(hours=2), 3)   # first rating counts: 9
            shown(known, t0 + timedelta(hours=1), 80); rate(known, t0, 8)                      # rated BEFORE it was shown: left out
            shown(imported, t0, 70); rate(imported, t0 + timedelta(hours=1), 8, "import:letterboxd")   # imports are not outcomes
            shown(never_rated, t0, 60)
        body = c.get("/api/me/report").json()
        assert body["shown"] == 3 and body["rated"] == 1 and body["ready"] is True            # only shown_first is an outcome
        assert body["avg_rating"] == 9.0                                                       # the FIRST rating after exposure, not the edit
        by = {b["label"]: b for b in body["buckets"]}
        assert by["90% and up"]["n"] == 1 and by["Under 60%"]["n"] == 0                       # Match % at first exposure (90), not the later 50
        assert body["opened"] == 0 and body["watched"] == 0


def test_rec_feedback_only_for_recommended_then_rated_titles(world, test_engine):
    rec, plain = world[0], world[1]
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        uid = c.get("/api/me").json()["id"]
        with test_engine.begin() as conn:
            conn.execute(text("INSERT INTO recommendation_logs (user_id, movie_id, surface, match_pct, created_at) VALUES (:u, :m, 'top_picks', 85, now() - interval '1 hour')"),
                         {"u": uid, "m": rec})
        assert c.get(f"/api/feedback/rec-outcome/{rec}").json()["eligible"] is False         # not rated yet
        assert c.put(f"/api/ratings/{rec}", json={"rating": 8}).status_code == 200
        assert c.put(f"/api/ratings/{plain}", json={"rating": 8}).status_code == 200
        assert c.get(f"/api/feedback/rec-outcome/{rec}").json()["eligible"] is True
        assert c.get(f"/api/feedback/rec-outcome/{plain}").json()["eligible"] is False        # never recommended
        assert c.put(f"/api/feedback/rec-outcome/{plain}", json={"answer": "exactly"}).status_code == 409
        assert c.put(f"/api/feedback/rec-outcome/{rec}", json={"answer": "bogus"}).status_code == 422
        assert c.put(f"/api/feedback/rec-outcome/{rec}", json={"answer": "too_slow"}).json() == {"answer": "too_slow"}
        assert c.put(f"/api/feedback/rec-outcome/{rec}", json={"answer": "exactly"}).status_code == 200
        assert c.get(f"/api/feedback/rec-outcome/{rec}").json()["answer"] == "exactly"       # latest answer wins
