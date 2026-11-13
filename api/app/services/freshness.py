"""Titles this person was shown on earlier days and did not act on, so Home can move them behind fresh ones.

Home is reshuffled every day (daily.py), but the reshuffle draws from the top of the same ranking, so about half the
titles repeated day after day. Every title Home serves is logged (recommendation_logs). Titles that were in the first
few places of a row or in the hero within the last few days count as seen. Today's own logs are left out, so the page
stays the same all day and only changes when the day changes.
"""
import datetime as dt

from sqlalchemy import text

from . import daily

DAYS = 3          # how many earlier days count
SEEN_RANKS = 8    # the first places of a row are the ones a person actually sees without scrolling


def recently_shown_ids(db, user_id: int, today: dt.date | None = None, days: int = DAYS, ranks: int = SEEN_RANKS) -> set[int]:
    today = today or daily.today()
    start = dt.datetime.combine(today - dt.timedelta(days=days), dt.time.min, tzinfo=daily.IST)
    end = dt.datetime.combine(today, dt.time.min, tzinfo=daily.IST)
    rows = db.execute(text("""SELECT DISTINCT movie_id FROM recommendation_logs
        WHERE user_id = :u AND created_at >= :a AND created_at < :b AND (rank IS NULL OR rank < :k)"""),
                      {"u": user_id, "a": start, "b": end, "k": ranks}).scalars()
    return {int(r) for r in rows}
