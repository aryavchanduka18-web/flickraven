"""Movies, search and genres."""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import user_id_from
from app.db import get_db
from app.services import franchise as fr
from app.services import search as sq
from app.services.confidence import confidence
from app.services import recommender as rec
from app.services.movies import cards, detail

router = APIRouter(tags=["catalog"])


@router.get("/movies/{movie_id}")
def movie(movie_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    uid = user_id_from(request, db)
    d = detail(db, movie_id, uid)
    if d is None:
        raise HTTPException(404, "Unknown movie")
    if uid is not None and rec.artifacts_ready():
        engine = rec.load_engine(db)
        st = rec.user_state(db, uid, engine)
        row = engine.cat.row_of.get(movie_id)
        if row is not None:
            source_scores = engine.scores(st)
            scores = engine.rail_scores(st, source_scores)
            raw = float(scores[row]) if np.isfinite(scores[row]) else None
            d["match_pct"] = engine.match(st.stage, raw) if raw is not None else None
            us = d["user_state"]
            if d["match_pct"] is None and (us["rating"] is not None or us["reaction"] != 0):
                # Already rated, liked or disliked: part of the user's profile, not recommended back to them,
                # so no "why you're seeing this" and no confidence card (the page says so instead).
                d["in_profile"] = True
            else:
                shares = _shares(engine, st, row, source_scores)
                d["why"] = engine.reasons(st, row, shares)
                d["confidence"] = confidence(engine, st, row, d["match_pct"], source_scores)
    return d


def _shares(engine, st, row, scores=None) -> dict:
    """Per-source share of a single film's catalog-wide hybrid score (for Why This on any page)."""
    scores = scores or engine.scores(st)
    w = engine.weights[st.stage]
    parts = {}
    for s, v in scores.items():
        ok = np.isfinite(v)
        if not ok[row] or not w.get(s):
            continue
        pct = (np.argsort(np.argsort(v[ok])) + 1) / ok.sum()
        parts[s] = w[s] * float(pct[np.nonzero(ok)[0].tolist().index(row)])
    total = sum(parts.values()) or 1.0
    return {s: p / total for s, p in parts.items()}


@router.get("/movies/{movie_id}/similar")
def similar(movie_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    if not rec.artifacts_ready():
        return {"items": []}
    engine = rec.load_engine(db)
    row = engine.cat.row_of.get(movie_id)
    if row is None:
        raise HTTPException(404, "Unknown movie")
    ids = [int(engine.cat.movie_ids[r]) for r in engine.similar(row)]
    return {"items": cards(db, ids, user_id_from(request, db))}


@router.get("/movies/{movie_id}/franchise")
def franchise(movie_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    """More from the film's collection, its studio universe (e.g. Marvel), or fallbacks (services/franchise.py)."""
    if not db.execute(text("SELECT 1 FROM movies WHERE id = :m"), {"m": movie_id}).first():
        raise HTTPException(404, "Unknown movie")
    secs = fr.sections(db, movie_id)
    uid = user_id_from(request, db)
    match = rec.match_for(db, uid, sorted({i for s in secs for i in s["ids"]}))
    return {"sections": [{**{k: v for k, v in s.items() if k != "ids"}, "items": cards(db, s["ids"], uid, match)}
                         for s in secs]}


@router.get("/movies")
def discover(request: Request, genre: str | None = None, lang: str | None = None, decade: int | None = None,
             runtime: str | None = None, country: str | None = None, min_rating: float | None = None,
             sort: str = "popular", page: int = 1, type: str | None = None,
             db: Session = Depends(get_db)) -> dict:
    """Browse the catalog. `type` is movie (the default), series, anime or all."""
    where, p = ["true"], {}
    if type in ("movie", "series", "anime") or type is None:
        where.append("m.title_type = :type"); p["type"] = type or "movie"
    if genre:
        where.append("m.id IN (SELECT mg.movie_id FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE g.slug = :genre)")
        p["genre"] = genre
    if lang:
        where.append("m.original_language = :lang"); p["lang"] = lang
    if decade:
        where.append("m.year BETWEEN :d AND :d + 9"); p["d"] = decade
    if runtime in ("short", "medium", "long"):
        where.append({"short": "m.runtime_min < 90", "medium": "m.runtime_min BETWEEN 90 AND 120",
                      "long": "m.runtime_min > 120"}[runtime])
    if country:
        where.append(":country = ANY(m.countries)"); p["country"] = country
    if min_rating:
        where.append("m.popularity_score >= :mr"); p["mr"] = min_rating
    order = {"popular": "m.tmdb_vote_count DESC NULLS LAST", "rating": "m.popularity_score DESC NULLS LAST",
             "newest": "m.release_date DESC NULLS LAST", "title": "m.title"}.get(sort, "m.tmdb_vote_count DESC NULLS LAST")
    uid = user_id_from(request, db)
    if type in ("series", "anime") and sort in ("recommended", "match") and uid is not None and rec.artifacts_ready():
        # No ratings exist for series and anime: their order is content similarity to the user's taste plus popularity.
        all_ids = [r[0] for r in db.execute(text(f"SELECT m.id FROM movies m WHERE {' AND '.join(where)}"), p)]
        engine = rec.load_engine(db)
        rows, scores = engine.kind_rank(rec.user_state(db, uid, engine), type)
        allowed, rank = set(all_ids), [(int(engine.cat.movie_ids[r]), float(s)) for r, s in zip(rows, scores)]
        ranked = [(i, s) for i, s in rank if i in allowed]
        start = (max(page, 1) - 1) * 40
        shown = ranked[start:start + 40]
        return {"items": cards(db, [i for i, _ in shown], uid, {i: {"score": s} for i, s in shown}),
                "total": len(ranked), "page": page, "sort": sort}
    if sort in PERSONAL_SORTS and uid is not None and rec.artifacts_ready():
        all_ids = [r[0] for r in db.execute(text(f"SELECT m.id FROM movies m WHERE {' AND '.join(where)} ORDER BY {order}"), p)]
        ranked, scores, engine, stage = personal_order(db, uid, all_ids, sort)
        start = (max(page, 1) - 1) * 40
        shown = ranked[start:start + 40]
        extra = {i: {"score": scores[i], "match_pct": engine.match(stage, scores[i])} for i in shown if i in scores}
        return {"items": cards(db, shown, uid, extra), "total": len(all_ids), "page": page, "sort": sort}
    p.update(limit=40, offset=(max(page, 1) - 1) * 40)
    ids = [r[0] for r in db.execute(text(f"SELECT m.id FROM movies m WHERE {' AND '.join(where)} ORDER BY {order} LIMIT :limit OFFSET :offset"), p)]
    total = db.execute(text(f"SELECT count(*) FROM movies m WHERE {' AND '.join(where)}"), p).scalar()
    return {"items": cards(db, ids, uid), "total": total, "page": page, "sort": sort}


PERSONAL_SORTS = {"recommended", "match", "hidden", "novel"}


def personal_order(db: Session, uid: int, ids: list[int], sort: str):
    """Discover sorts that need the engine (the filtered films, best first):
    recommended: hybrid percentile, re-ranked with the user's Tune sliders (novelty and the slider boosts);
    match: hybrid score only; hidden: hybrid percentile x (1 - fame percentile), i.e. high match, little known;
    novel: films whose genres the user has not liked before come first, then by hybrid score.
    Films the engine excludes (rated, disliked) go last, in the filter's popularity order."""
    engine = rec.load_engine(db)
    st = rec.user_state(db, uid, engine)
    rail = engine.rail_scores(st)
    rows = np.array([engine.cat.row_of.get(i, -1) for i in ids])
    known = rows >= 0
    r = np.where(known, rows, 0)
    s = np.where(known, rail[r], -np.inf)
    ok = np.isfinite(s)
    pct = np.zeros(len(ids))
    if ok.any():
        pct[ok] = (np.argsort(np.argsort(s[ok])) + 1) / ok.sum()
    if sort == "match":
        key = pct
    elif sort == "recommended":
        tuning = rec.user_tuning(db, uid)
        key = pct + (0.05 + 0.15 * tuning.shift("hidden")) * engine.cat.novelty[r] + engine._tuning_boost(r, tuning)
    elif sort == "hidden":
        key = pct * (1 - engine.cat.fame_pct[r] / 100)
    else:
        liked = {g for row in st.liked_rows() for g in engine.cat.genres[row]}
        fresh = np.array([0.0 if set(engine.cat.genres[x]) & liked else 1.0 for x in r])
        key = fresh + pct
    key = np.where(ok, key, -np.inf)
    order = np.argsort(-key, kind="stable")
    return [ids[j] for j in order], {ids[j]: float(s[j]) for j in np.nonzero(ok)[0]}, engine, st.stage


@router.get("/search")
def search(q: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Films for a query, best first (see app/services/search.py), plus what the query was understood as
    (genre / language / year words), matching people and genres for links."""
    q = q.strip()
    if not q:
        return {"items": [], "understood": sq.Parsed().understood(), "people": [], "genres": []}
    ids, parsed = sq.search_ids(db, q)
    plain = not parsed.has_filters
    return {"items": cards(db, ids, user_id_from(request, db)), "understood": parsed.understood(),
            "people": sq.find_people(db, q) if plain else [], "genres": sq.find_genres(db, q) if plain else []}


@router.get("/search/suggest")
def suggest(q: str, db: Session = Depends(get_db)) -> dict:
    """Search-as-you-type: a few films, people and genres. Light: no recommender and no per-user state."""
    q = q.strip()
    if len(q) < 2:
        return {"films": [], "people": [], "genres": []}
    ids, parsed = sq.search_ids(db, q, limit=6)
    films = []
    if ids:
        rows = {r["id"]: r for r in db.execute(text(
            "SELECT id, title, year, poster_path FROM movies WHERE id = ANY(:ids)"), {"ids": ids}).mappings()}
        films = [{"id": i, "title": rows[i]["title"], "year": rows[i]["year"], "poster": rows[i]["poster_path"]}
                 for i in ids if i in rows]
    plain = not parsed.has_filters
    return {"films": films, "people": sq.find_people(db, q, 3) if plain else [],
            "genres": sq.find_genres(db, q) if plain else [], "understood": parsed.understood()}


@router.get("/genres")
def genres(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(text("""SELECT g.id, g.name, g.slug, count(mg.movie_id) AS films,
        (SELECT m.backdrop_path FROM movies m JOIN movie_genres x ON x.movie_id = m.id WHERE x.genre_id = g.id
         AND m.backdrop_path IS NOT NULL ORDER BY m.tmdb_vote_count DESC NULLS LAST LIMIT 1) AS backdrop
        FROM genres g LEFT JOIN movie_genres mg ON mg.genre_id = g.id GROUP BY g.id ORDER BY g.name""")).mappings()
    return {"genres": [dict(r) for r in rows]}


@router.get("/genres/{slug}/movies")
def genre_movies(slug: str, request: Request, page: int = 1, db: Session = Depends(get_db)) -> dict:
    """A genre page ranks its films FOR THIS USER with the hybrid score (spec 8.3)."""
    g = db.execute(text("SELECT id, name FROM genres WHERE slug = :s"), {"s": slug}).first()
    if g is None:
        raise HTTPException(404, "Unknown genre")
    uid = user_id_from(request, db)
    if uid is None or not rec.artifacts_ready():
        return discover(request, genre=slug, page=page, db=db) | {"genre": g[1]}
    engine = rec.load_engine(db)
    st = rec.user_state(db, uid, engine)
    scores = engine.rail_scores(st)
    rows = [r for r in np.argsort(-scores) if g[1] in engine.cat.genres[r] and np.isfinite(scores[r])]
    start = (max(page, 1) - 1) * 40
    pick = rows[start:start + 40]
    extra = {int(engine.cat.movie_ids[r]): {"score": float(scores[r]), "match_pct": engine.match(st.stage, float(scores[r]))}
             for r in pick}
    return {"genre": g[1], "items": cards(db, list(extra), uid, extra), "total": len(rows), "page": page}