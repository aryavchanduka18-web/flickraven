"""Every action writes BOTH the current-state table and the append-only interactions log (spec 10)."""
from sqlalchemy import text
from sqlalchemy.orm import Session

IMPLICIT_EVENTS = {"detail_view", "quick_view", "search_click", "hero_view"}


def log(db: Session, user_id: int, movie_id: int | None, event_type: str, value: float | None = None,
        source: str | None = None, position: int | None = None, origin: str | None = None) -> None:
    """`source` = where the action happened (a row, the film page); `origin` = the row or page that led there."""
    db.execute(text("""INSERT INTO interactions (user_id, movie_id, event_type, value, source, position, origin)
                       VALUES (:u, :m, :e, :v, :s, :p, :o)"""),
               {"u": user_id, "m": movie_id, "e": event_type, "v": value, "s": source, "p": position, "o": origin})


def detail_view_logged_today(db: Session, user_id: int, movie_id: int) -> bool:
    """detail_view counts once per film per day (spec 6.2)."""
    return db.execute(text("""SELECT 1 FROM interactions WHERE user_id = :u AND movie_id = :m
        AND event_type = 'detail_view' AND created_at >= date_trunc('day', now()) LIMIT 1"""),
                      {"u": user_id, "m": movie_id}).first() is not None


def set_rating(db, uid, mid, rating, source=None, origin=None):
    db.execute(text("""INSERT INTO ratings (user_id, movie_id, rating) VALUES (:u, :m, :r)
        ON CONFLICT (user_id, movie_id) DO UPDATE SET rating = :r, updated_at = now()"""), {"u": uid, "m": mid, "r": rating})
    log(db, uid, mid, "rate", rating, source, None, origin)


def clear_rating(db, uid, mid, source=None, origin=None):
    db.execute(text("DELETE FROM ratings WHERE user_id = :u AND movie_id = :m"), {"u": uid, "m": mid})
    log(db, uid, mid, "unrate", None, source, None, origin)


def set_reaction(db, uid, mid, value, source=None, origin=None):
    db.execute(text("""INSERT INTO reactions (user_id, movie_id, value) VALUES (:u, :m, :v)
        ON CONFLICT (user_id, movie_id) DO UPDATE SET value = :v, updated_at = now()"""), {"u": uid, "m": mid, "v": value})
    log(db, uid, mid, "like" if value > 0 else "dislike", value, source, None, origin)


def clear_reaction(db, uid, mid, source=None, origin=None):
    db.execute(text("DELETE FROM reactions WHERE user_id = :u AND movie_id = :m"), {"u": uid, "m": mid})
    log(db, uid, mid, "clear_reaction", None, source, None, origin)


def add_to_list(db, uid, mid, source=None, origin=None):
    db.execute(text("INSERT INTO user_movie_list (user_id, movie_id) VALUES (:u, :m) ON CONFLICT DO NOTHING"),
               {"u": uid, "m": mid})
    log(db, uid, mid, "list_add", None, source, None, origin)


def remove_from_list(db, uid, mid, source=None, origin=None):
    db.execute(text("DELETE FROM user_movie_list WHERE user_id = :u AND movie_id = :m"), {"u": uid, "m": mid})
    log(db, uid, mid, "list_remove", None, source, None, origin)


def mark_watched(db, uid, mid, source=None, origin=None):
    db.execute(text("INSERT INTO watched (user_id, movie_id) VALUES (:u, :m) ON CONFLICT DO NOTHING"), {"u": uid, "m": mid})
    log(db, uid, mid, "watched", None, source, None, origin)


def unmark_watched(db, uid, mid, source=None, origin=None):
    db.execute(text("DELETE FROM watched WHERE user_id = :u AND movie_id = :m"), {"u": uid, "m": mid})
    log(db, uid, mid, "unwatched", None, source, None, origin)