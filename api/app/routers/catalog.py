"""Movies, search and genres."""
import re

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import user_id_from
from app.db import get_db
from app.models.catalog import normalize_sql
from app.services import franchise as fr
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
             sort: str = "popular", page: int = 1, db: Session = Depends(get_db)) -> dict:
    where, p = ["true"], {}
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


SEARCH_LIMIT = 60
FUZZY_BELOW = 10          # fuzzy title matches are added only when the exact search finds fewer films
FUZZY_MIN_CHARS = 3       # shorter queries have too few trigrams to compare
FUZZY_THRESHOLD = 0.6     # pg_trgm word_similarity of the query to the closest part of a title


def prefix_words(q: str) -> list[str]:
    """The query's words for a prefix tsquery, normalized like titles: lower case, dots and apostrophes
    dropped, anything that is not a letter or digit splits words."""
    q = re.sub(r"[.'’`]", "", q.lower())
    return [w for w in re.split(r"[\W_]+", q) if w][:8]


@router.get("/search")
def search(q: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Search as you type: titles, cast and director, genre and language by name.

    Every word of the query also matches as the start of a word, so "dar" finds "The Dark Knight" and
    "nol" finds Christopher Nolan's films. Titles are compared after normalization (no dots or
    apostrophes, punctuation as spaces), so "LA confidential" finds "L.A. Confidential".
    Ranking: exact title, then titles that start with the query (a leading "The" is optional), then
    titles with a word that starts with it; most-voted (TMDB) first within each of those. Everything
    else (cast, director, genre, mid-word matches) follows by text rank, then votes. If that finds fewer
    than FUZZY_BELOW films, trigram similarity on the normalized title adds typo matches
    ("horrible bossses"), best match first, with TMDB vote count as the tie-break."""
    q = q.strip()
    if not q:
        return {"items": []}
    # text() would read ":alnum" in the regex as a bind parameter, so those colons are escaped.
    qn = "(" + normalize_sql(":q").replace("[:alnum:]", r"[\:alnum\:]") + ")"
    words = prefix_words(q)
    # 'dar':* & 'kni':* -- only letters and digits reach the tsquery, so nothing in it needs escaping.
    # A query of only punctuation gives an empty tsquery, which matches nothing (Postgres only notes it).
    tsq = " & ".join(f"'{w}':*" for w in words)
    ids = [r[0] for r in db.execute(text(f"""
        WITH hits AS (
            SELECT m.id, m.tmdb_vote_count AS votes,
                   ts_rank(m.search_vector, to_tsquery('simple', :tsq)) AS rank,
                   CASE WHEN m.title_norm IN ({qn}, 'the ' || {qn}) THEN 0
                        WHEN m.title_norm LIKE {qn} || '%' OR m.title_norm LIKE 'the ' || {qn} || '%' THEN 1
                        WHEN ' ' || m.title_norm LIKE '% ' || {qn} || '%' THEN 2
                        ELSE 3 END AS tier
            FROM movies m
            WHERE (:has_words AND m.search_vector @@ to_tsquery('simple', :tsq))
               OR m.id IN (SELECT mg.movie_id FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE g.name ILIKE :like)
               OR m.title ILIKE :like
               OR ({qn} <> '' AND m.title_norm LIKE '%' || {qn} || '%'))
        SELECT id FROM hits
        ORDER BY tier, CASE WHEN tier < 3 THEN votes END DESC NULLS LAST, rank DESC, votes DESC NULLS LAST
        LIMIT :limit"""), {"q": q, "tsq": tsq, "has_words": bool(words), "like": f"%{q}%",
                             "limit": SEARCH_LIMIT})]
    if len(ids) < FUZZY_BELOW and len(q) >= FUZZY_MIN_CHARS:
        # Sets the threshold of the indexed <% operator for this transaction only.
        db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
                   {"t": str(FUZZY_THRESHOLD)})
        fuzzy = db.execute(text(f"""
            SELECT m.id FROM movies m
            WHERE {qn} <% m.title_norm
            ORDER BY round(greatest(word_similarity({qn}, m.title_norm), similarity({qn}, m.title_norm))::numeric, 2) DESC,
                     m.tmdb_vote_count DESC NULLS LAST
            LIMIT :limit"""), {"q": q, "limit": SEARCH_LIMIT})
        seen = set(ids)
        ids += [r[0] for r in fuzzy if r[0] not in seen][:SEARCH_LIMIT - len(ids)]
    return {"items": cards(db, ids, user_id_from(request, db))}


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