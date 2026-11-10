"""Movies, search and genres."""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import user_id_from
from app.db import get_db
from app.services import franchise as fr
from app.services import search as sq
from app.services import similar as similar_svc
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
def similar(movie_id: int, request: Request, offset: int = 0, limit: int = 20, db: Session = Depends(get_db)) -> dict:
    """More Like This: titles of the same type most similar to this one, with the reasons (services/similar.py).
    Paged with offset/limit (at most 40 neighbours are stored per title)."""
    if not rec.artifacts_ready():
        return {"items": [], "total": 0}
    engine = rec.load_engine(db)
    if engine.cat.row_of.get(movie_id) is None:
        raise HTTPException(404, "Unknown movie")
    offset, limit = max(offset, 0), min(max(limit, 1), 40)
    page, extra, total = similar_svc.similar_page(db, engine, movie_id, offset, limit)
    uid = user_id_from(request, db)
    ids = list(extra)
    # Match % only where the models that the calibrator was fitted on can score the title (MovieLens films);
    # a number for the others would not mean what it says.
    known = [i for i in ids if engine.cat.universe_of_row[engine.cat.row_of[i]] >= 0]
    match = rec.match_for(db, uid, known)
    for i in ids:
        if i in match:
            extra[i]["match_pct"] = match[i]["match_pct"]
    return {"items": cards(db, ids, uid, extra), "total": total, "offset": offset}


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
             year_min: int | None = None, year_max: int | None = None, min_imdb: float | None = None,
             provider: int | None = None, min_match: int | None = None,
             db: Session = Depends(get_db)) -> dict:
    """Browse the catalog. `type` is movie (the default), series, anime or all. Extra filters: `year_min`/`year_max`
    (release period), `min_imdb` (IMDb score), `provider` (a TMDB provider id that streams it for free or on subscription
    in the stored region) and `min_match` (Match %, needs a personal sort and a signed-in user)."""
    where, p = ["true"], {}
    if genre == ANIME_SLUG and type in (None, "movie", "all"):
        where.append("m.title_type IN ('movie', 'anime')")          # Japanese animation: TV anime and animated films
    elif type in ("movie", "series", "anime") or type is None:
        where.append("m.title_type = :type"); p["type"] = type or "movie"
    if genre == ANIME_SLUG:
        where.append(f"m.original_language = 'ja' AND {ANIMATION_IDS}")
    elif genre:
        where.append("m.id IN (SELECT mg.movie_id FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE g.slug = :genre)")
        p["genre"] = genre
        if genre == ANIMATION_SLUG:
            where.append("m.original_language IS DISTINCT FROM 'ja'")  # Japanese animation is Anime, not Animation
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
    if year_min:
        where.append("m.year >= :ymin"); p["ymin"] = year_min
    if year_max:
        where.append("m.year <= :ymax"); p["ymax"] = year_max
    if min_imdb:
        where.append("m.imdb_rating >= :mi"); p["mi"] = min_imdb
    if provider:
        where.append("m.id IN (SELECT w.movie_id FROM movie_watch_providers w WHERE w.provider_id = :prov "
                     "AND w.kind IN ('flatrate', 'free', 'ads'))")
        p["prov"] = provider
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
        total = len(all_ids)
        if min_match:
            # Only films that have a Match % (the engine can score them) and reach the chosen level.
            ranked = [i for i in ranked if i in scores and engine.match(stage, scores[i]) >= min_match]
            total = len(ranked)
        start = (max(page, 1) - 1) * 40
        shown = ranked[start:start + 40]
        extra = {i: {"score": scores[i], "match_pct": engine.match(stage, scores[i])} for i in shown if i in scores}
        return {"items": cards(db, shown, uid, extra), "total": total, "page": page, "sort": sort}
    p.update(limit=40, offset=(max(page, 1) - 1) * 40)
    ids = [r[0] for r in db.execute(text(f"SELECT m.id FROM movies m WHERE {' AND '.join(where)} ORDER BY {order} LIMIT :limit OFFSET :offset"), p)]
    total = db.execute(text(f"SELECT count(*) FROM movies m WHERE {' AND '.join(where)}"), p).scalar()
    return {"items": cards(db, ids, uid), "total": total, "page": page, "sort": sort}


PERSONAL_SORTS = {"recommended", "match", "hidden", "novel"}


@router.get("/discover/options")
def discover_options(db: Session = Depends(get_db)) -> dict:
    """Choices for the Discover filters, from what the catalog really holds: countries (ISO codes, most titles
    first) and streaming services (TMDB provider id, name, logo, how many titles), for the stored region."""
    countries = [{"code": r[0], "titles": r[1]} for r in db.execute(text(
        "SELECT c, count(*) FROM movies m, unnest(m.countries) c GROUP BY c ORDER BY 2 DESC, 1 LIMIT 40"))]
    providers = [{"id": r[0], "name": r[1], "logo": r[2], "titles": r[3]} for r in db.execute(text(
        """SELECT w.provider_id, min(w.provider_name), min(w.logo_path), count(DISTINCT w.movie_id) AS n
           FROM movie_watch_providers w WHERE w.kind IN ('flatrate', 'free', 'ads')
           GROUP BY w.provider_id HAVING count(DISTINCT w.movie_id) >= 30 ORDER BY n DESC LIMIT 30"""))]
    return {"countries": countries, "providers": providers}


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


ANIME_SLUG = "anime"
ANIMATION_SLUG = "animation"
ANIMATION_IDS = ("m.id IN (SELECT mg.movie_id FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id "
                 f"WHERE g.slug = '{ANIMATION_SLUG}')")


@router.get("/genres")
def genres(db: Session = Depends(get_db)) -> dict:
    """Genre tiles. Counts are films only. "Anime" is its own entry next to Animation and means Japanese animation
    (TV anime and animated films); Animation is the rest (cartoons and animated films from everywhere else)."""
    rows = [dict(r) for r in db.execute(text(f"""SELECT g.id, g.name, g.slug,
        count(m.id) FILTER (WHERE m.title_type = 'movie' AND NOT (g.slug = '{ANIMATION_SLUG}' AND m.original_language = 'ja')) AS films,
        (SELECT m2.backdrop_path FROM movies m2 JOIN movie_genres x ON x.movie_id = m2.id WHERE x.genre_id = g.id
         AND m2.title_type = 'movie' AND NOT (g.slug = '{ANIMATION_SLUG}' AND m2.original_language = 'ja')
         AND m2.backdrop_path IS NOT NULL ORDER BY m2.tmdb_vote_count DESC NULLS LAST LIMIT 1) AS backdrop
        FROM genres g LEFT JOIN movie_genres mg ON mg.genre_id = g.id LEFT JOIN movies m ON m.id = mg.movie_id
        GROUP BY g.id""")).mappings()]
    anime = db.execute(text(f"""SELECT count(*) AS n, (SELECT m2.backdrop_path FROM movies m2 WHERE m2.title_type IN ('movie', 'anime')
        AND m2.original_language = 'ja' AND {ANIMATION_IDS.replace('m.id', 'm2.id')} AND m2.backdrop_path IS NOT NULL
        ORDER BY m2.tmdb_vote_count DESC NULLS LAST LIMIT 1) AS backdrop
        FROM movies m WHERE m.title_type IN ('movie', 'anime') AND m.original_language = 'ja' AND {ANIMATION_IDS}""")).mappings().first()
    if anime and anime["n"]:
        rows.append({"id": 0, "name": "Anime", "slug": ANIME_SLUG, "films": anime["n"], "backdrop": anime["backdrop"]})
    return {"genres": sorted(rows, key=lambda r: r["name"])}


@router.get("/genres/{slug}/movies")
def genre_movies(slug: str, request: Request, page: int = 1, db: Session = Depends(get_db)) -> dict:
    """A genre page ranks its films FOR THIS USER with the hybrid score (spec 8.3). "anime" (Japanese animation, TV and
    films) is listed most popular first: TV anime and films have no common score to rank them together."""
    if slug == ANIME_SLUG:
        return discover(request, genre=ANIME_SLUG, sort="popular", page=page, type="all", db=db) | {"genre": "Anime"}
    g = db.execute(text("SELECT id, name FROM genres WHERE slug = :s"), {"s": slug}).first()
    if g is None:
        raise HTTPException(404, "Unknown genre")
    uid = user_id_from(request, db)
    if uid is None or not rec.artifacts_ready():
        return discover(request, genre=slug, page=page, db=db) | {"genre": g[1]}
    engine = rec.load_engine(db)
    st = rec.user_state(db, uid, engine)
    scores = engine.rail_scores(st)
    rows = [r for r in np.argsort(-scores) if g[1] in engine.cat.genres[r] and np.isfinite(scores[r])
            and not (slug == ANIMATION_SLUG and engine.cat.language[r] == "ja")]
    start = (max(page, 1) - 1) * 40
    pick = rows[start:start + 40]
    extra = {int(engine.cat.movie_ids[r]): {"score": float(scores[r]), "match_pct": engine.match(st.stage, float(scores[r]))}
             for r in pick}
    return {"genre": g[1], "items": cards(db, list(extra), uid, extra), "total": len(rows), "page": page}