"""Fix brief 2026-11-15, issue 1: deleting a rating (or clearing a like, removing a save) takes its effect away again.
Stage, the behavioral count and Your Current Phase come from what stands now, not from the append-only log. Issue 4:
the person's own high ratings overrule an old genre dislike, and deleting them brings the dislike back."""
import uuid

import numpy as np
import scipy.sparse as sp
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.main import app
from app.services import recommender as rec
from cinematch_engine.online import Catalog, OnlineEngine

GOOD = "Very-long-pass-123!"


def _engine(movie_ids, genres):
    n = len(movie_ids)
    cat = Catalog(movie_ids=np.array(movie_ids), titles=[f"t{i}" for i in range(n)], genres=genres, keywords=[[]] * n,
                  language=["en"] * n, runtime=np.full(n, 100.0), year=np.full(n, 2000.0), part=np.array(["D"] * n),
                  popularity=np.full(n, 7.0), votes=np.arange(n, dtype=float), has_award=np.zeros(n, dtype=bool),
                  content=sp.identity(n, format="csr", dtype=np.float32), universe_rows=np.array([], dtype=np.int64),
                  recent=np.zeros(n, dtype=bool))
    e = OnlineEngine.__new__(OnlineEngine)
    e.cat = cat
    return e


def test_rate_then_delete_leaves_no_trace_in_stage_phase_or_genre_lift(test_engine):
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": f"undo-{uuid.uuid4().hex[:8]}@example.com", "password": GOOD})
    uid = r.json()["id"]
    with test_engine.begin() as conn:
        horror = conn.execute(text("INSERT INTO genres (id, name, slug) VALUES (9901, 'UndoHorror', 'undo-horror') ON CONFLICT (id) DO UPDATE SET name = 'UndoHorror' RETURNING id")).scalar()
        mids = [conn.execute(text("INSERT INTO movies (tmdb_id, title) VALUES (:t, :n) RETURNING id"),
                             {"t": -9100 - i, "n": f"Undo {i}"}).scalar() for i in range(4)]
        for m in mids:
            conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": m, "g": horror})
        conn.execute(text("INSERT INTO user_preferences (user_id, disliked_genre_ids) VALUES (:u, ARRAY[:g])"), {"u": uid, "g": horror})
    try:
        for m in mids[:3]:
            assert c.put(f"/api/ratings/{m}", json={"rating": 10, "source": "detail"}).status_code == 200
        assert c.put(f"/api/reactions/{mids[3]}", json={"value": 1}).status_code == 200
        assert c.put(f"/api/list/{mids[3]}", json={}).status_code == 200
        counts = c.get("/api/me").json()["counts"]
        assert counts["behavioral_count"] == 4 and counts["stage"] == "warming"
        eng = _engine(mids, [["UndoHorror"]] * 4)
        with SessionLocal() as db:
            st = rec.user_state(db, uid, eng)
            assert st.lifted_genres == ["UndoHorror"] and st.disliked_genres == []   # three 10/10s overrule the dislike
            assert len(rec.recent_positive_rows(db, uid, eng, st)) == 4

        for m in mids:
            c.delete(f"/api/ratings/{m}")
            c.delete(f"/api/reactions/{m}")
            c.delete(f"/api/list/{m}")
        counts = c.get("/api/me").json()["counts"]
        assert counts["ratings"] == 0
        assert counts["behavioral_count"] == 0 and counts["stage"] == "cold"         # same as an account that never rated
        with SessionLocal() as db:
            st = rec.user_state(db, uid, eng)
            assert st.behavioral_count == 0 and st.stage == "cold"
            assert st.disliked_genres == ["UndoHorror"] and st.lifted_genres == []   # the dislike is back
            assert rec.recent_positive_rows(db, uid, eng, st) == []                  # nothing left for Your Current Phase
            logged = db.execute(text("SELECT count(*) FROM interactions WHERE user_id = :u AND event_type = 'rate'"),
                                {"u": uid}).scalar()
            assert logged == 3                                                        # the log itself keeps the history
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:m)"), {"m": mids})
            conn.execute(text("DELETE FROM genres WHERE id = 9901"))
