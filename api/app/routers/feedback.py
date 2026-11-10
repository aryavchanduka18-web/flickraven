from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.ratelimit import EVENTS
from app.services import events as ev
from app.services.events import IMPLICIT_EVENTS
from app.services.movies import cards

router = APIRouter(tags=["feedback"])


def exists(db: Session, movie_id: int) -> None:
    if not db.execute(text("SELECT 1 FROM movies WHERE id = :m"), {"m": movie_id}).first():
        raise HTTPException(404, "Unknown movie")


class RatingBody(BaseModel):
    rating: int = Field(ge=1, le=10)
    source: str | None = None


class ReactionBody(BaseModel):
    value: int
    source: str | None = None


class SourceBody(BaseModel):
    source: str | None = None


@router.put("/ratings/{movie_id}")
def rate(movie_id: int, body: RatingBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    exists(db, movie_id)
    ev.set_rating(db, user["id"], movie_id, body.rating, body.source)
    db.commit()
    return {"ok": True}


@router.delete("/ratings/{movie_id}")
def unrate(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ev.clear_rating(db, user["id"], movie_id)
    db.commit()
    return {"ok": True}


@router.put("/reactions/{movie_id}")
def react(movie_id: int, body: ReactionBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if body.value not in (1, -1):
        raise HTTPException(422, "value must be 1 (like) or -1 (dislike)")
    exists(db, movie_id)
    ev.set_reaction(db, user["id"], movie_id, body.value, body.source)
    db.commit()
    return {"ok": True}


@router.delete("/reactions/{movie_id}")
def unreact(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ev.clear_reaction(db, user["id"], movie_id)
    db.commit()
    return {"ok": True}


@router.put("/list/{movie_id}")
def list_add(movie_id: int, body: SourceBody | None = None, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    exists(db, movie_id)
    ev.add_to_list(db, user["id"], movie_id, body.source if body else None)
    db.commit()
    return {"ok": True}


@router.delete("/list/{movie_id}")
def list_remove(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ev.remove_from_list(db, user["id"], movie_id)
    db.commit()
    return {"ok": True}


@router.get("/list")
def get_list(sort: str = "recent", user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    order = {"recent": "l.added_at DESC", "rating": "m.popularity_score DESC NULLS LAST", "year": "m.year DESC NULLS LAST",
             "title": "m.title"}.get(sort, "l.added_at DESC")
    ids = [r[0] for r in db.execute(text(f"""SELECT m.id FROM user_movie_list l JOIN movies m ON m.id = l.movie_id
        WHERE l.user_id = :u ORDER BY {order}"""), {"u": user["id"]})]
    items = cards(db, ids, user["id"])
    if sort == "genre":
        items.sort(key=lambda c: (c["movie"]["genres"] or ["~"])[0])
    return {"items": items}


@router.put("/watched/{movie_id}")
def watched(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    exists(db, movie_id)
    ev.mark_watched(db, user["id"], movie_id)
    db.commit()
    return {"ok": True}


@router.delete("/watched/{movie_id}")
def unwatched(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ev.unmark_watched(db, user["id"], movie_id)
    db.commit()
    return {"ok": True}


class EventBody(BaseModel):
    movie_id: int | None = None
    event_type: str
    source: str | None = None
    position: int | None = None


@router.post("/events")
def event(body: EventBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Lightweight implicit events. Hover is never logged; detail_view counts once per film per day."""
    if body.event_type not in IMPLICIT_EVENTS:
        raise HTTPException(422, f"event_type must be one of {sorted(IMPLICIT_EVENTS)}")
    if not EVENTS.allow(f"user:{user['id']}"):
        return {"ok": True, "dropped": True}      # too many too fast: not stored, and the page carries on
    if body.event_type == "detail_view" and body.movie_id and ev.detail_view_logged_today(db, user["id"], body.movie_id):
        return {"ok": True, "deduplicated": True}
    ev.log(db, user["id"], body.movie_id, body.event_type, None, body.source, body.position)
    db.commit()
    return {"ok": True}

DISLIKE_REASONS = {"genre", "long", "slow", "predictable", "language", "seen", "similar", "unexpected", "none"}


class DislikeReasonBody(BaseModel):
    movie_id: int
    reason: str | None = None              # one reason (older clients)
    reasons: list[str] = []                # or several at once


@router.post("/feedback/dislike-reason")
def dislike_reason(body: DislikeReasonBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Why a disliked film was not for you; one or several reasons. Each is logged as an event, and each reason
    changes something real on top of the dislike itself (which already removes the film and steers the content
    profile away from it):
    genre -> its main genre goes to your disliked genres (unless you said you like it); long -> the Length slider
    moves 20 towards shorter; slow -> the Length slider moves 10 towards shorter (shorter films are usually
    tighter); predictable -> the Adventurous slider moves 15 up and Hidden gems 10 up (less obvious picks);
    language -> the International slider moves 20 towards your languages if the film is outside them, else away;
    seen -> marked watched (never recommended again); similar -> the Adventurous slider moves 15 up;
    unexpected / none -> just the dislike."""
    reasons = list(dict.fromkeys([*body.reasons, *([body.reason] if body.reason else [])]))
    if not reasons or any(r not in DISLIKE_REASONS for r in reasons):
        raise HTTPException(422, f"reasons must be one or more of {sorted(DISLIKE_REASONS)}")
    exists(db, body.movie_id)
    uid = user["id"]
    for r in reasons:
        ev.log(db, uid, body.movie_id, "dislike_reason", None, r)
    db.execute(text("INSERT INTO user_preferences (user_id) VALUES (:u) ON CONFLICT (user_id) DO NOTHING"), {"u": uid})
    pref = db.execute(text("SELECT liked_genre_ids, disliked_genre_ids, tuning FROM user_preferences WHERE user_id = :u"),
                      {"u": uid}).mappings().one()
    tuning = {"adventurous": 50, "hidden": 50, "international": 50, "length": 50, **(pref["tuning"] or {})}
    said: list[str] = []

    def nudge(key: str, by: int):
        tuning[key] = max(0, min(100, int(tuning[key]) + by))

    for reason in reasons:
        if reason == "genre":
            g = db.execute(text("""SELECT g.id, g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
                WHERE mg.movie_id = :m ORDER BY g.id LIMIT 1"""), {"m": body.movie_id}).first()
            if g and g[0] not in (pref["liked_genre_ids"] or []):
                db.execute(text("""UPDATE user_preferences SET disliked_genre_ids =
                    ARRAY(SELECT DISTINCT unnest(coalesce(disliked_genre_ids, '{}') || ARRAY[CAST(:g AS int)])) WHERE user_id = :u"""),
                           {"g": g[0], "u": uid})
                said.append(f"less {g[1]}")
        elif reason == "long":
            nudge("length", -20)
            said.append("shorter titles a little higher")
        elif reason == "slow":
            nudge("length", -10)
            said.append("tighter, shorter titles a little higher")
        elif reason == "predictable":
            nudge("adventurous", 15)
            nudge("hidden", 10)
            said.append("less obvious picks")
        elif reason == "language":
            local = db.execute(text("SELECT original_language FROM movies WHERE id = :m"), {"m": body.movie_id}).scalar()
            outside = local not in {"en", "hi", "ta", "te", "ml", "kn", "bn", "mr"}
            nudge("international", -20 if outside else 20)
            said.append("more in your usual languages" if outside else "more international titles")
        elif reason == "seen":
            ev.mark_watched(db, uid, body.movie_id, "dislike_reason")
            said.append("marked as watched, so it won't come back")
        elif reason == "similar":
            nudge("adventurous", 15)
            said.append("more varied lists")
    db.execute(text("UPDATE user_preferences SET tuning = CAST(:t AS jsonb), updated_at = now() WHERE user_id = :u"),
               {"u": uid, "t": __import__("json").dumps(tuning)})
    change = ("Got it: " + "; ".join(said) + ".") if said else "Thanks, noted. The dislike already steers your picks."
    db.commit()
    return {"ok": True, "message": change, "tuning": tuning, "reasons": reasons}
