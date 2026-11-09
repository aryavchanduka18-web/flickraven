from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import check_password, clear, current_user
from app.db import get_db
from cinematch_engine.profile import BEHAVIORAL_EVENTS, stage_of

router = APIRouter(tags=["me"])


def counts(db: Session, uid: int) -> dict:
    q = lambda sql: db.execute(text(sql), {"u": uid}).scalar()
    b = q(f"""SELECT count(DISTINCT movie_id) FROM interactions WHERE user_id = :u
             AND event_type IN ({", ".join(f"'{e}'" for e in sorted(BEHAVIORAL_EVENTS))})""")
    return {"ratings": q("SELECT count(*) FROM ratings WHERE user_id = :u"),
            "likes": q("SELECT count(*) FROM reactions WHERE user_id = :u AND value = 1"),
            "dislikes": q("SELECT count(*) FROM reactions WHERE user_id = :u AND value = -1"),
            "list": q("SELECT count(*) FROM user_movie_list WHERE user_id = :u"),
            "watched": q("SELECT count(*) FROM watched WHERE user_id = :u"),
            "onboarding_count": q("SELECT count(*) FROM onboarding_picks WHERE user_id = :u"),
            "behavioral_count": b, "stage": stage_of(b)}


@router.get("/me")
def me(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    pref = db.execute(text("SELECT discovery_mode FROM user_preferences WHERE user_id = :u"), {"u": user["id"]}).first()
    user.pop("token_issued_ms", None)
    return {**user, "onboarded": user["onboarded_at"] is not None,
            "discovery_mode": pref[0] if pref else "balanced", "counts": counts(db, user["id"])}


class AccountUpdate(BaseModel):
    display_name: str = Field(max_length=80)


@router.patch("/me")
def update_me(body: AccountUpdate, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    name = body.display_name.strip()
    if not name:
        raise HTTPException(422, "Your name cannot be empty")
    db.execute(text("UPDATE users SET display_name = :n WHERE id = :u"), {"n": name, "u": user["id"]})
    db.commit()
    return {"display_name": name}


class AccountDelete(BaseModel):
    password: str | None = Field(default=None, max_length=200)


@router.delete("/me")
def delete_me(body: AccountDelete, response: Response, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Delete the account and everything it owns (ratings, reactions, list, history, logs cascade).

    Accounts need their password; guests have none and can delete straight away."""
    if not user["is_guest"]:
        hashed = db.execute(text("SELECT password_hash FROM users WHERE id = :u"), {"u": user["id"]}).scalar()
        if not check_password(body.password or "", hashed):
            # 403, not 401: the web client answers a 401 by starting a guest session and retrying.
            raise HTTPException(403, "That password is not right, so nothing was deleted")
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user["id"]})
    db.commit()
    clear(response)
    return {"deleted": True}


class Preferences(BaseModel):
    languages: list[str] | None = None
    liked_genre_ids: list[int] | None = None
    disliked_genre_ids: list[int] | None = None
    discovery_mode: str | None = None


@router.get("/me/preferences")
def get_preferences(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    row = db.execute(text("SELECT languages, liked_genre_ids, disliked_genre_ids, discovery_mode FROM user_preferences WHERE user_id = :u"),
                     {"u": user["id"]}).mappings().first()
    return dict(row) if row else {"languages": [], "liked_genre_ids": [], "disliked_genre_ids": [], "discovery_mode": "balanced"}


@router.put("/me/preferences")
def put_preferences(body: Preferences, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if body.discovery_mode and body.discovery_mode not in ("familiar", "balanced", "discover"):
        raise HTTPException(422, "discovery_mode must be familiar, balanced or discover")
    current = get_preferences(user, db)
    new = {k: v if v is not None else current.get(k) for k, v in body.model_dump().items()}
    db.execute(text("""INSERT INTO user_preferences (user_id, languages, liked_genre_ids, disliked_genre_ids, discovery_mode, updated_at)
        VALUES (:u, :l, :lg, :dg, :dm, now()) ON CONFLICT (user_id) DO UPDATE SET languages = :l, liked_genre_ids = :lg,
        disliked_genre_ids = :dg, discovery_mode = :dm, updated_at = now()"""),
               {"u": user["id"], "l": new["languages"] or [], "lg": new["liked_genre_ids"] or [],
                "dg": new["disliked_genre_ids"] or [], "dm": new["discovery_mode"] or "balanced"})
    db.commit()
    return new


@router.get("/me/taste-profile")
def taste_profile(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """All from real interaction data: liked = rated 8+, liked, or picked in onboarding."""
    p = {"u": user["id"]}
    liked = """(SELECT movie_id FROM ratings WHERE user_id = :u AND rating >= 8
                UNION SELECT movie_id FROM reactions WHERE user_id = :u AND value = 1
                UNION SELECT movie_id FROM onboarding_picks WHERE user_id = :u)"""
    genres = db.execute(text(f"""SELECT g.name, count(*) n FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id IN {liked} GROUP BY g.name ORDER BY n DESC LIMIT 8"""), p).all()
    langs = db.execute(text(f"""SELECT original_language, count(*) n FROM movies WHERE id IN {liked}
        GROUP BY 1 ORDER BY n DESC LIMIT 5"""), p).all()
    eras = db.execute(text(f"""SELECT (year / 10) * 10 AS decade, count(*) n FROM movies WHERE id IN {liked} AND year IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 4"""), p).all()
    avg = db.execute(text("SELECT avg(rating) FROM ratings WHERE user_id = :u"), p).scalar()
    c = counts(db, user["id"])
    mode = db.execute(text("SELECT discovery_mode FROM user_preferences WHERE user_id = :u"), p).scalar()
    return {"top_genres": [{"genre": g, "count": n} for g, n in genres],
            "top_languages": [{"language": l, "count": n} for l, n in langs],
            "eras": [{"decade": int(d), "count": n} for d, n in eras],
            "average_rating": round(float(avg), 1) if avg is not None else None,
            "like_dislike_ratio": round(c["likes"] / c["dislikes"], 2) if c["dislikes"] else None,
            "films_rated": c["ratings"], "films_saved": c["list"], "discovery_mode": mode or "balanced",
            "stage": c["stage"], "behavioral_count": c["behavioral_count"], "onboarding_count": c["onboarding_count"]}

class TuningBody(BaseModel):
    adventurous: int = Field(50, ge=0, le=100)
    hidden: int = Field(50, ge=0, le=100)
    international: int = Field(50, ge=0, le=100)
    length: int = Field(50, ge=0, le=100)


@router.get("/me/tuning")
def get_tuning(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    raw = db.execute(text("SELECT tuning FROM user_preferences WHERE user_id = :u"), {"u": user["id"]}).scalar() or {}
    return TuningBody(**raw).model_dump()


@router.put("/me/tuning")
def put_tuning(body: TuningBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The Tune sliders; the engine re-ranks Top Picks, the hero and Discover with them (engine Tuning)."""
    import json
    db.execute(text("""INSERT INTO user_preferences (user_id, tuning) VALUES (:u, CAST(:t AS jsonb))
        ON CONFLICT (user_id) DO UPDATE SET tuning = CAST(:t AS jsonb), updated_at = now()"""),
               {"u": user["id"], "t": json.dumps(body.model_dump())})
    db.commit()
    return body.model_dump()
