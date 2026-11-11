"""Impressions: rows and cards that were genuinely visible, reported by the browser.

An impression means "this was on screen long enough to be seen" (the browser decides: at least 50% of a row or 60% of a
card visible for 1 second with the tab in front, once per page load). It says nothing about whether the person liked it:
no learning step may read a missing action as a no. Impressions are only the denominator for row statistics.

The server cannot prove a row was really on screen. What it does check: the person is signed in (a guest counts), the
title exists, the surface name has the expected shape, at most MAX_BATCH items per call, at most DAILY_CAP stored
per person per day, and each row or card counts once per page load (unique index).
"""
import re
import uuid
from datetime import datetime  # noqa: F401  (kept for type readers)

from sqlalchemy import text
from sqlalchemy.orm import Session

SURFACE = re.compile(r"^(rail|collection|hero)(:[A-Za-z0-9_\-]{1,60}){0,2}$")
KINDS = ("row", "card")
MAX_BATCH = 100
DAILY_CAP = 2000
CARD_KEEP_DAYS = 30        # card-level impressions are deleted after this
ROW_KEEP_DAYS = 60         # row-level impressions are deleted after this


def record(db: Session, user_id: int, page_id: str, items: list[dict]) -> dict:
    """Store the valid items; returns how many were stored and how many were dropped."""
    try:
        page = uuid.UUID(page_id)
    except ValueError:
        return {"stored": 0, "dropped": len(items)}
    today = db.execute(text("""SELECT count(*) FROM impressions WHERE user_id = :u
        AND created_at >= date_trunc('day', now())"""), {"u": user_id}).scalar() or 0
    room = max(DAILY_CAP - int(today), 0)
    stored = 0
    for it in items[:MAX_BATCH]:
        if stored >= room:
            break
        surface, kind, movie_id = it.get("surface"), it.get("kind"), it.get("movie_id")
        if kind not in KINDS or not isinstance(surface, str) or not SURFACE.match(surface):
            continue
        if kind == "card" and not isinstance(movie_id, int):
            continue
        if kind == "row":
            movie_id = None
        pos = it.get("position")
        pos = pos if isinstance(pos, int) and 0 <= pos < 1000 else None
        ms = it.get("visible_ms")
        ms = min(max(ms, 0), 60_000) if isinstance(ms, int) else None
        done = db.execute(text("""
            INSERT INTO impressions (user_id, page_id, surface, kind, movie_id, position, visible_ms)
            SELECT :u, :p, :s, :k, m.id, :pos, :ms FROM (SELECT CAST(:m AS integer) AS mid) q
            LEFT JOIN movies m ON m.id = q.mid
            WHERE :k = 'row' OR m.id IS NOT NULL
            ON CONFLICT (user_id, page_id, surface, kind, (coalesce(movie_id, 0))) DO NOTHING"""),
                          {"u": user_id, "p": page, "s": surface, "k": kind, "m": movie_id, "pos": pos, "ms": ms}).rowcount
        stored += done
    return {"stored": stored, "dropped": len(items) - stored}
