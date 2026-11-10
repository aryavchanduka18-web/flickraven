from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db

router = APIRouter(tags=["activity"])
TYPES = {"views": ("detail_view", "quick_view", "search_click"), "ratings": ("rate", "unrate"),
         "likes": ("like", "dislike", "clear_reaction"), "list": ("list_add", "list_remove"),
         "watched": ("watched", "unwatched"), "onboarding": ("onboarding_pick",)}


@router.get("/activity/titles")
def activity_titles(type: str | None = None, offset: int = 0, user=Depends(current_user),
                    db: Session = Depends(get_db)) -> dict:
    """Recent Activity: one row per title (its latest event, how many times each kind happened), newest first.
    The raw list is /activity (Full Interaction History)."""
    where, p = ["i.user_id = :u", "i.movie_id IS NOT NULL"], {"u": user["id"], "o": max(offset, 0)}
    if type in TYPES:
        where.append("i.event_type = ANY(:types)"); p["types"] = list(TYPES[type])
    rows = db.execute(text(f"""
        SELECT g.movie_id, m.title, m.title_type, m.backdrop_path, m.year, g.last_at, g.last_event, g.counts,
               (SELECT r.value FROM interactions r WHERE r.user_id = :u AND r.movie_id = g.movie_id
                  AND r.event_type = 'rate' ORDER BY r.id DESC LIMIT 1) AS rating
        FROM (SELECT e.movie_id, max(e.last_at) AS last_at,
                     (array_agg(e.event_type ORDER BY e.last_at DESC))[1] AS last_event,
                     jsonb_object_agg(e.event_type, e.n) AS counts
              FROM (SELECT i.movie_id, i.event_type, max(i.created_at) AS last_at, count(*) AS n
                    FROM interactions i WHERE {' AND '.join(where)} GROUP BY i.movie_id, i.event_type) e
              GROUP BY e.movie_id) g
        JOIN movies m ON m.id = g.movie_id
        ORDER BY g.last_at DESC OFFSET :o LIMIT 31"""), p).mappings().all()
    items = [{**dict(r), "last_at": r["last_at"].isoformat()} for r in rows[:30]]
    return {"items": items, "next_offset": p["o"] + 30 if len(rows) > 30 else None}


@router.get("/activity")
def activity(type: str | None = None, cursor: int | None = None, user=Depends(current_user),
             db: Session = Depends(get_db)) -> dict:
    where, p = ["i.user_id = :u"], {"u": user["id"]}
    if type in TYPES:
        where.append("i.event_type = ANY(:types)"); p["types"] = list(TYPES[type])
    if cursor:
        where.append("i.id < :c"); p["c"] = cursor
    rows = db.execute(text(f"""SELECT i.id, i.event_type, i.value, i.source, i.created_at, m.id AS movie_id, m.title,
        m.poster_path, m.backdrop_path, m.year, m.title_type FROM interactions i LEFT JOIN movies m ON m.id = i.movie_id
        WHERE {' AND '.join(where)} ORDER BY i.id DESC LIMIT 50"""), p).mappings().all()
    items = [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]
    return {"items": items, "next_cursor": items[-1]["id"] if len(items) == 50 else None}