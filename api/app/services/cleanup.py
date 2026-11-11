"""Housekeeping that keeps the free database (Neon, 1 GB) from filling up.

- Guest accounts with no activity for GUEST_IDLE_DAYS are deleted (their ratings, list and history go
  with them through ON DELETE CASCADE). Guests who signed up are no longer guests, so they are never touched.
- recommendation_logs (one row per film shown, used only for offline analysis) older than LOG_KEEP_DAYS
  are deleted.
- impressions (rows and cards that were visible): cards after 30 days, rows after 60.

It runs once shortly after start-up and then every CLEANUP_EVERY_HOURS while the server is awake.
"""
import logging
import threading

from sqlalchemy import text

GUEST_IDLE_DAYS = 30
LOG_KEEP_DAYS = 60
CLEANUP_EVERY_HOURS = 12

log = logging.getLogger("uvicorn.error")


def run(db) -> dict:
    guests = db.execute(text("""
        DELETE FROM users u
        WHERE u.is_guest
          AND u.created_at < now() - make_interval(days => :d)
          AND NOT EXISTS (SELECT 1 FROM interactions i
                          WHERE i.user_id = u.id AND i.created_at >= now() - make_interval(days => :d))"""),
                        {"d": GUEST_IDLE_DAYS}).rowcount
    logs = db.execute(text("DELETE FROM recommendation_logs WHERE created_at < now() - make_interval(days => :d)"),
                      {"d": LOG_KEEP_DAYS}).rowcount
    from app.services import impressions
    imps = db.execute(text("""DELETE FROM impressions WHERE (kind = 'card' AND created_at < now() - make_interval(days => :c))
                                 OR created_at < now() - make_interval(days => :r)"""),
                      {"c": impressions.CARD_KEEP_DAYS, "r": impressions.ROW_KEEP_DAYS}).rowcount
    db.commit()
    return {"guests_deleted": guests, "logs_deleted": logs, "impressions_deleted": imps}


def _loop(stop: threading.Event) -> None:
    from app.db import SessionLocal
    if stop.wait(60):                      # let the server finish starting first
        return
    while True:
        try:
            with SessionLocal() as db:
                result = run(db)
            log.info("cleanup: %s", result)
        except Exception as e:             # never take the server down over housekeeping
            log.warning("cleanup skipped: %s", e)
        if stop.wait(CLEANUP_EVERY_HOURS * 3600):
            return


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True).start()
    return stop
