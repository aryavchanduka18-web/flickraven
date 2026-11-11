"""Themed collections (services/collections.py): rails for Home and a page per collection."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from cinematch_engine.rerank import refresh

from app.auth import user_id_from
from app.db import get_db
from app.services import collections as col
from app.services import daily
from app.services import recommender as rec
from app.services.movies import cards

router = APIRouter(tags=["collections"])
RAIL = 20
PAGE = 40


def hidden(db: Session, uid: int | None) -> set[int]:
    """Films the user rated, liked, disliked, watched or picked in onboarding: like Home and Top Picks,
    collections do not offer them again (More Like This still shows them; it is similarity alone)."""
    if uid is None:
        return set()
    return set(db.execute(text("""SELECT movie_id FROM ratings WHERE user_id = :u
        UNION SELECT movie_id FROM reactions WHERE user_id = :u
        UNION SELECT movie_id FROM watched WHERE user_id = :u
        UNION SELECT movie_id FROM onboarding_picks WHERE user_id = :u"""), {"u": uid}).scalars())


@router.get("/collections")
def collections(request: Request, db: Session = Depends(get_db)) -> dict:
    """Every collection with at least MIN_FILMS films, each with its first RAIL films for this user."""
    uid = user_id_from(request, db)
    skip = hidden(db, uid)
    interest = col.interest_languages(db, uid)
    members = {c["key"]: [i for i in col.member_ids(db, c) if i not in skip] for c in col.COLLECTIONS if col.offered(c, interest)}
    members = {k: v for k, v in members.items() if len(v) >= col.MIN_FILMS}
    match = rec.match_for(db, uid, sorted({i for ids in members.values() for i in ids}))
    out = []
    day = daily.rng(uid, "collections") if uid is not None else None
    for c in col.COLLECTIONS:
        if c["key"] not in members:
            continue
        ids = col.ordered(db, c, match, members[c["key"]])
        # Each day the row shows a fresh part of the same ordering (the best few stay), and the rows change places.
        shown = refresh(ids, RAIL, day) if day is not None else ids[:RAIL]
        out.append({"key": c["key"], "title": c["title"], "count": len(ids),
                    "items": cards(db, shown, uid, match)})
    if day is not None:
        order = list(day.permutation(len(out)))
        out = [out[i] for i in order]
    return {"collections": out}


@router.get("/collections/{key}")
def collection(key: str, request: Request, page: int = 1, db: Session = Depends(get_db)) -> dict:
    c = col.BY_KEY.get(key)
    if c is None:
        raise HTTPException(404, "Unknown collection")
    uid = user_id_from(request, db)
    skip = hidden(db, uid)
    members = [i for i in col.member_ids(db, c) if i not in skip]
    match = rec.match_for(db, uid, members)
    ids = col.ordered(db, c, match, members)
    page = max(page, 1)
    return {"key": key, "title": c["title"], "count": len(ids), "page": page,
            "items": cards(db, ids[(page - 1) * PAGE: page * PAGE], uid, match)}
