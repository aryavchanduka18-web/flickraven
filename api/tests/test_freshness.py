"""Titles shown on earlier days (first places only) count as seen; today's page and deep places do not."""
import datetime as dt

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import daily, freshness


def test_recently_shown_ids_window_and_ranks(test_engine):
    today = dt.date(2026, 11, 14)
    at = lambda d, h=12: dt.datetime.combine(d, dt.time(h), tzinfo=daily.IST)
    with test_engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('fresh@example.com', 'x', 'x', false) RETURNING id")).scalar()
        ids = [conn.execute(text("INSERT INTO movies (tmdb_id, title, year, title_type) VALUES (:t, :n, 2020, 'movie') RETURNING id"),
                            {"t": 993000 + i, "n": f"f-{i}"}).scalar() for i in range(5)]
        rows = [(ids[0], 2, at(today - dt.timedelta(days=1))),     # yesterday, seen place: counts
                (ids[1], 12, at(today - dt.timedelta(days=1))),    # yesterday but deep in a row: not seen
                (ids[2], 1, at(today - dt.timedelta(days=5))),     # too old
                (ids[3], 1, at(today)),                            # today: the page stays the same all day
                (ids[4], None, at(today - dt.timedelta(days=2)))]  # the hero has no rank: counts
        for mid, rank, when in rows:
            conn.execute(text("INSERT INTO recommendation_logs (user_id, movie_id, rank, surface, created_at) VALUES (:u, :m, :k, 'top_picks', :c)"),
                         {"u": uid, "m": mid, "k": rank, "c": when})
    try:
        with Session(test_engine) as db:
            assert freshness.recently_shown_ids(db, uid, today=today) == {ids[0], ids[4]}
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM recommendation_logs WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 993000 AND 993999"))
