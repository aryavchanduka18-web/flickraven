"""Franchise sections for the film page: the TMDB collection, studio universes, and fallbacks.

1. "More from <collection>": every part of the film's TMDB collection in the catalog, by release date
   (the film itself included and flagged, so the order of the series is visible).
2. Universes such as Marvel: films from the studio or with the universe keyword, by release date.
3. No collection: other films by the same director. Nothing else: a film that is not part of a franchise gets no
   franchise rows, and series and anime get none (they are not in TMDB film collections).
"""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

# Studio universes: a film belongs when one of its studios or keywords matches.
UNIVERSES = [
    {"key": "marvel", "name": "Marvel", "studios": ["Marvel Studios"], "keywords": ["marvel cinematic universe (mcu)"]},
    {"key": "dc", "name": "DC", "studios": ["DC Films", "DC Studios"],
     "keywords": ["dc extended universe (dceu)", "dc universe (dcu)"]},
    {"key": "pixar", "name": "Pixar", "studios": ["Pixar"], "keywords": []},
    {"key": "ghibli", "name": "Studio Ghibli", "studios": ["Studio Ghibli"], "keywords": []},
    {"key": "dreamworks", "name": "DreamWorks Animation", "studios": ["DreamWorks Animation"], "keywords": []},
]
# Keywords that mark a film as part of a franchise or shared universe.
FRANCHISE_KEYWORD = re.compile(r"cinematic universe|extended universe|\(dcu\)|\(mcu\)|^superhero team$|^based on comic$"
                               r"|^based on video game$|^sequel$|^prequel$|^spin off$")
LIMIT = 30


def collection_title(name: str) -> str:
    """'John Wick Collection' -> 'John Wick'; 'The Avengers Collection' -> 'The Avengers'."""
    return re.sub(r"\s+Collection$", "", name).strip()


def _ids(db: Session, sql: str, **params) -> list:
    return [r[0] for r in db.execute(text(sql), params)]


def sections(db: Session, movie_id: int) -> list[dict]:
    m = db.execute(text("SELECT id, collection_id, collection_name, studios, title_type FROM movies WHERE id = :m"),
                   {"m": movie_id}).mappings().first()
    if m is None or m["title_type"] != "movie":
        return []
    keywords = set(_ids(db, """SELECT k.name FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id
                               WHERE mk.movie_id = :m""", m=movie_id))
    out, shown = [], {movie_id}

    if m["collection_id"] is not None:
        ids = _ids(db, """SELECT id FROM movies WHERE collection_id = :c
                          ORDER BY release_date NULLS LAST, year NULLS LAST, title""", c=m["collection_id"])
        if len(ids) > 1:
            out.append({"key": "collection", "kind": "collection", "current": movie_id, "ids": ids,
                        "title": f"More from {collection_title(m['collection_name'])}"})
            shown |= set(ids)

    studios = set(m["studios"] or [])
    for u in UNIVERSES:
        if not (studios & set(u["studios"]) or keywords & set(u["keywords"])):
            continue
        ids = _ids(db, """SELECT m.id FROM movies m
            WHERE m.studios && CAST(:s AS text[])
               OR EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id
                          WHERE mk.movie_id = m.id AND k.name = ANY(:k))
            ORDER BY m.release_date NULLS LAST, m.title""", s=u["studios"], k=u["keywords"] or [""])
        ids = [i for i in ids if i not in shown][:LIMIT]
        if ids:
            out.append({"key": u["key"], "kind": "universe", "title": f"More from {u['name']}", "ids": ids})
            shown |= set(ids)

    if m["collection_id"] is None:
        out += _fallbacks(db, movie_id, shown)
    return out


def _fallbacks(db: Session, movie_id: int, shown: set[int]) -> list[dict]:
    out = []
    directors = db.execute(text("""SELECT pe.id, pe.name FROM movie_credits mc JOIN people pe ON pe.id = mc.person_id
        WHERE mc.movie_id = :m AND mc.role = 'director' ORDER BY mc.credit_order NULLS LAST, pe.name LIMIT 2"""),
                           {"m": movie_id}).all()
    for pid, name in directors:
        ids = [i for i in _ids(db, """SELECT m.id FROM movie_credits mc JOIN movies m ON m.id = mc.movie_id
            WHERE mc.person_id = :p AND mc.role = 'director' ORDER BY m.release_date DESC NULLS LAST""", p=pid)
               if i not in shown][:LIMIT]
        if ids:
            out.append({"key": f"director-{pid}", "kind": "director", "title": f"More from {name}", "ids": ids})
            shown |= set(ids)

    return out
