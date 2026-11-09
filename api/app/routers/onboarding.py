import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.services.events import log
from app.services.movies import cards

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
MIN_LANGUAGE_FILMS = 150


@router.get("/candidates")
def candidates(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """~60 films to pick from (the most voted overall plus the most voted per onboarding language), and the
    most voted series, so a new user can start from TV as well. Anime is left out of the first picks."""
    popular = [r[0] for r in db.execute(text(
        "SELECT id FROM movies WHERE title_type = 'movie' AND backdrop_path IS NOT NULL "
        "ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 30"))]
    intl = [r[0] for r in db.execute(text("""
        SELECT id FROM (SELECT id, original_language, row_number() OVER (PARTITION BY original_language
                        ORDER BY tmdb_vote_count DESC NULLS LAST) rn
                        FROM movies WHERE title_type = 'movie' AND original_language <> 'en' AND backdrop_path IS NOT NULL) t
        WHERE rn <= 3 AND original_language IN (SELECT original_language FROM movies GROUP BY 1 HAVING count(*) >= :n)"""),
        {"n": MIN_LANGUAGE_FILMS})]
    ids = list(dict.fromkeys(popular + intl))[:60]
    random.Random(42).shuffle(ids)
    return {"movies": cards(db, ids, user["id"]), "series": cards(db, top_of(db, "series", 24), user["id"]),
            "languages": languages(db), "genres": genres(db)}


def top_of(db: Session, kind: str, n: int) -> list[int]:
    ids = [r[0] for r in db.execute(text(
        "SELECT id FROM movies WHERE title_type = :k AND backdrop_path IS NOT NULL "
        "ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT :n"), {"k": kind, "n": n})]
    random.Random(42).shuffle(ids)
    return ids


def languages(db: Session) -> list[dict]:
    return [{"code": c, "films": n} for c, n in db.execute(text(
        "SELECT original_language, count(*) FROM movies GROUP BY 1 HAVING count(*) >= :n ORDER BY 2 DESC"),
        {"n": MIN_LANGUAGE_FILMS})]


def genres(db: Session) -> list[dict]:
    return [dict(r) for r in db.execute(text("SELECT id, name, slug FROM genres ORDER BY name")).mappings()]


class OnboardingBody(BaseModel):
    movie_ids: list[int] = Field(min_length=5, max_length=10)
    languages: list[str] = Field(min_length=1)
    liked_genre_ids: list[int] = []
    disliked_genre_ids: list[int] = []


@router.post("")
def save(body: OnboardingBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Onboarding picks are preference signals, NOT behavior: they never add to the stage counter b."""
    allowed = {l["code"] for l in languages(db)}
    if not set(body.languages) <= allowed:
        raise HTTPException(422, "Only languages with at least 150 films can be chosen")
    uid = user["id"]
    db.execute(text("DELETE FROM onboarding_picks WHERE user_id = :u"), {"u": uid})
    for m in dict.fromkeys(body.movie_ids):
        db.execute(text("INSERT INTO onboarding_picks (user_id, movie_id) VALUES (:u, :m) ON CONFLICT DO NOTHING"), {"u": uid, "m": m})
        log(db, uid, m, "onboarding_pick", source="onboarding")
    db.execute(text("""INSERT INTO user_preferences (user_id, languages, liked_genre_ids, disliked_genre_ids, updated_at)
        VALUES (:u, :l, :lg, :dg, now()) ON CONFLICT (user_id) DO UPDATE SET languages = :l, liked_genre_ids = :lg,
        disliked_genre_ids = :dg, updated_at = now()"""),
               {"u": uid, "l": body.languages, "lg": body.liked_genre_ids, "dg": body.disliked_genre_ids})
    db.execute(text("UPDATE users SET onboarded_at = coalesce(onboarded_at, now()) WHERE id = :u"), {"u": uid})
    db.commit()
    return {"ok": True, "onboarding_count": len(set(body.movie_ids))}