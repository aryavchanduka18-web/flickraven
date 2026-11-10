"""Private usage numbers for the site owner (/stats). Only totals, never what one person watched.

Open to the signed-in accounts whose email is in ADMIN_EMAILS (comma-separated); everyone else gets 404,
so the page does not even show that it exists.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

NEON_FREE_BYTES = 1024 ** 3     # 1 GB per project on Neon's free plan


def require_admin(user=Depends(current_user)) -> dict:
    allowed = {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}
    if user["is_guest"] or not user.get("email") or user["email"].lower() not in allowed:
        raise HTTPException(404, "Not found")
    return user


@router.get("/stats")
def stats(_=Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    one = lambda sql: db.execute(text(sql)).scalar() or 0
    active = lambda days, guest: one(f"""SELECT count(DISTINCT i.user_id) FROM interactions i JOIN users u ON u.id = i.user_id
        WHERE i.created_at >= now() - interval '{days} days' AND u.is_guest = {guest}""")
    daily = db.execute(text("""
        WITH d AS (SELECT generate_series(date_trunc('day', now()) - interval '29 days', date_trunc('day', now()), interval '1 day') AS day)
        SELECT to_char(d.day, 'YYYY-MM-DD') AS day,
          (SELECT count(*) FROM users u WHERE NOT u.is_guest AND u.created_at >= d.day AND u.created_at < d.day + interval '1 day') AS signups,
          (SELECT count(DISTINCT i.user_id) FROM interactions i WHERE i.created_at >= d.day AND i.created_at < d.day + interval '1 day') AS active,
          (SELECT count(*) FROM interactions i WHERE i.event_type = 'rate' AND i.created_at >= d.day AND i.created_at < d.day + interval '1 day') AS ratings
        FROM d ORDER BY d.day""")).mappings().all()
    top = db.execute(text("""SELECT m.id, m.title, count(DISTINCT i.user_id) AS people FROM interactions i JOIN movies m ON m.id = i.movie_id
        WHERE i.created_at >= now() - interval '7 days' AND i.event_type IN ('detail_view', 'rate', 'like', 'list_add')
        GROUP BY m.id, m.title ORDER BY people DESC, m.title LIMIT 10""")).mappings().all()
    size = one("SELECT pg_database_size(current_database())")
    return {
        "accounts": one("SELECT count(*) FROM users WHERE NOT is_guest"),
        "guests": one("SELECT count(*) FROM users WHERE is_guest"),
        "signups_7d": one("SELECT count(*) FROM users WHERE NOT is_guest AND created_at >= now() - interval '7 days'"),
        "signups_30d": one("SELECT count(*) FROM users WHERE NOT is_guest AND created_at >= now() - interval '30 days'"),
        "active_accounts": {"day": active(1, "false"), "week": active(7, "false"), "month": active(30, "false")},
        "active_guests": {"day": active(1, "true"), "week": active(7, "true"), "month": active(30, "true")},
        "returning_accounts_7d": one("""SELECT count(*) FROM (SELECT i.user_id FROM interactions i JOIN users u ON u.id = i.user_id
            WHERE NOT u.is_guest AND i.created_at >= now() - interval '7 days'
            GROUP BY i.user_id HAVING count(DISTINCT date_trunc('day', i.created_at)) >= 2) x"""),
        "ratings_7d": one("SELECT count(*) FROM interactions WHERE event_type = 'rate' AND created_at >= now() - interval '7 days'"),
        "imported_ratings_total": one("SELECT count(*) FROM interactions WHERE event_type = 'rate' AND source LIKE 'import:%'"),
        "database_bytes": size,
        "database_limit_bytes": NEON_FREE_BYTES,
        "daily": [dict(r) for r in daily],
        "top_films_7d": [dict(r) for r in top],
    }


@router.get("/similar/{movie_id}")
def similar_debug(movie_id: int, _=Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Owner-only debug view of More Like This for one title: every candidate with its signals and score."""
    from app.services import recommender as rec
    from app.services import similar as similar_svc
    if not rec.artifacts_ready():
        raise HTTPException(503, "Models not loaded")
    engine = rec.load_engine(db)
    if engine.cat.row_of.get(movie_id) is None:
        raise HTTPException(404, "Unknown movie")
    return similar_svc.debug_rows(engine, movie_id)
