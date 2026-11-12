"""Cast and crew pages: a person and their films in the FlickRaven catalog."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import user_id_from
from app.db import get_db
from app.services import recommender as rec
from app.services.movies import cards

router = APIRouter(tags=["people"])
DEPARTMENT = {"cast": "Acting", "director": "Directing", "writer": "Writing"}
RECOMMENDED = 10


def _person(db: Session, person_id: int) -> dict:
    p = db.execute(text("SELECT id, name, profile_path FROM people WHERE id = :p"), {"p": person_id}).mappings().first()
    if p is None:
        raise HTTPException(404, "Unknown person")
    return dict(p)


@router.get("/people/{person_id}")
def person(person_id: int, db: Session = Depends(get_db)) -> dict:
    """Name, photo, what they are known for (their most frequent role here) and their best-known films."""
    p = _person(db, person_id)
    roles = dict(db.execute(text("""SELECT role, count(DISTINCT movie_id) FROM movie_credits WHERE person_id = :p
                                    GROUP BY role"""), {"p": person_id}).all())
    known_for = DEPARTMENT[max(roles, key=lambda r: (roles[r], r == "cast"))] if roles else None
    films = db.execute(text("SELECT count(DISTINCT movie_id) FROM movie_credits WHERE person_id = :p"), {"p": person_id}).scalar()
    top = db.execute(text("""SELECT m.id, m.title, m.year, mc.character FROM movie_credits mc JOIN movies m ON m.id = mc.movie_id
        WHERE mc.person_id = :p ORDER BY m.tmdb_vote_count DESC NULLS LAST LIMIT 4"""), {"p": person_id}).mappings().all()
    return {**p, "known_for": known_for, "film_count": films,
            "departments": {DEPARTMENT[r]: n for r, n in roles.items()},
            "known_for_titles": [dict(t) for t in top]}


@router.get("/people/{person_id}/movies")
def person_movies(person_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    """Every catalog film with this person, newest first, with their role(s) and character; plus the ones the
    recommender rates highest for this user (real Match %, only films the engine can score)."""
    _person(db, person_id)
    rows = db.execute(text("""SELECT mc.movie_id, mc.role, mc.character FROM movie_credits mc JOIN movies m ON m.id = mc.movie_id
        WHERE mc.person_id = :p ORDER BY m.release_date DESC NULLS LAST, m.title, mc.role"""), {"p": person_id}).all()
    ids, credits = [], {}
    for mid, role, character in rows:
        if mid not in credits:
            ids.append(mid)
            credits[mid] = {"roles": [], "character": None}
        credits[mid]["roles"].append(DEPARTMENT[role])
        if role == "cast" and character:
            credits[mid]["character"] = character
    uid = user_id_from(request, db)
    match = rec.match_for(db, uid, ids)
    items = [{**c, **credits[c["movie"]["id"]]} for c in cards(db, ids, uid, match)]
    recommended = sorted((i for i in items if i["score"] is not None and not i["user_state"]["rating"]),
                         key=lambda i: -i["score"])[:RECOMMENDED]
    return {"items": items, "recommended": recommended}
