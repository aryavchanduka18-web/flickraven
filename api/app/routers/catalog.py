"""Movies, search and genres."""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import user_id_from
from app.db import get_db
from app.services import ai_similar
from app.services import anime_tags as anime_tags_mod
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
    row = engine.cat.row_of[movie_id]
    kind = engine.cat.kind[row]
    ai_ids, cross_ids = [], []
    if kind in ("series", "anime", "movie"):
        # Stored similarity is weak for TV (no viewing data): Gemini names similar series, we keep only those in the catalog.
        # Films (Hindi so far) come only from the offline file ai_similar_films.json: no live Gemini call per film.
        year = engine.cat.year[row]
        ai_ids = ai_similar.suggest(db, movie_id, engine.cat.titles[row], None if np.isnan(year) else int(year),
                                    list(engine.cat.genres[row]), kind)
        ai_ids = [i for i in ai_ids if i in engine.cat.row_of]     # titles the model has never seen cannot be scored or shown with it
        # Type-aware: the main list keeps this page's kind (anime page: anime only). Gemini's few cross-kind picks
        # (about 2% of its names) go to their own, clearly labelled row.
        cross_ids = [i for i in ai_ids if engine.cat.kind[engine.cat.row_of[i]] != kind]
        ai_ids = [i for i in ai_ids if engine.cat.kind[engine.cat.row_of[i]] == kind]
    if ai_ids:
        _, extra_all, _ = similar_svc.similar_page(db, engine, movie_id, 0, 40)
        stored = [i for i in extra_all if i not in ai_ids]
        uid0 = user_id_from(request, db)
        if uid0 is not None:
            # Gemini only supplies candidates. What this person sees is filtered and ordered by their own taste:
            # nothing they disliked or rated low, no genres they dislike, taste score blended with Gemini's order.
            pool = ai_ids[:30] + stored
            st = rec.user_state(db, uid0, engine)
            keep, fit, has_taste = engine.personal_fit(st, [engine.cat.row_of[i] for i in pool])
            kept = {i for i, k in zip(pool, keep) if k}
            seen = getattr(st, "watched", set())      # watched titles never show just because Gemini named them
            kept -= {i for i in pool[:len(ai_ids[:30])] if engine.cat.row_of[i] in seen}
            if kind == "movie":
                # Films: a disliked genre is a hard rule (personal_fit only bends it). The one exception is a genre the
                # page's own film is in: someone who opened a Drama still gets a list although they dislike Drama.
                bad = set(getattr(st, "disliked_genres", ())) - set(engine.cat.genres[row])
                if bad:
                    kept -= {i for i in pool if bad & set(engine.cat.genres[engine.cat.row_of[i]])}
            n_ai = len(ai_ids[:30])
            score = {i: 0.4 * (1 - n / max(n_ai, 1)) + 0.6 * fit[n] for n, i in enumerate(pool[:n_ai])}
            ai_ids = sorted((i for i in pool[:n_ai] if i in kept), key=lambda i: -score[i])
            stored = [i for i in stored if i in kept]
        order = ai_ids[:30] + stored
        total = len(order)
        ids = order[offset:offset + limit]
        extra = {i: extra_all.get(i, {"score": 0.0}) | ({"reasons": [{"code": "ai_similar", "text": "Similar film, picked with Google Gemini" if kind == "movie" else "Similar series, picked with Google Gemini",
                                                                       "source": "more_like_this", "share": 0.0, "anchor_movie_id": None}]} if i in ai_ids else {})
                 for i in ids}
    else:
        page, extra, total = similar_svc.similar_page(db, engine, movie_id, offset, limit)
        ids = list(extra)
    uid = user_id_from(request, db)
    # Match % only where the models that the calibrator was fitted on can score the title (MovieLens films);
    # a number for the others would not mean what it says.
    known = [i for i in ids if engine.cat.universe_of_row[engine.cat.row_of[i]] >= 0]
    match = rec.match_for(db, uid, known)
    for i in ids:
        if i in match:
            extra[i]["match_pct"] = match[i]["match_pct"]
    out = {"items": cards(db, ids, uid, extra), "total": total, "offset": offset}
    if cross_ids and offset == 0:
        if uid is not None:
            st = rec.user_state(db, uid, engine)
            rows = [engine.cat.row_of[i] for i in cross_ids]
            keep, _, _ = engine.personal_fit(st, rows)
            gone = set(st.ratings) | st.watched | st.dislikes | st.likes | st.picks | st.in_list    # nothing they already rated, liked, picked, saved, watched or disliked
            cross_ids = [i for i, r, k in zip(cross_ids, rows, keep) if k and r not in gone]
        cross_ids = cross_ids[:12]
        if cross_ids:
            out["cross_kind"] = {"title": "Live-action series in a similar vein" if kind == "anime" else "Anime in a similar vein",
                                 "items": cards(db, cross_ids, uid)}
    return out


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
             provider: int | None = None, min_match: int | None = None, vibe: str | None = None,
             anime_tags: str | None = None, anime_avoid: str | None = None,
             db: Session = Depends(get_db)) -> dict:
    """Browse the catalog. `type` is movie (the default), series, anime or all. Extra filters: `year_min`/`year_max`
    (release period), `min_imdb` (IMDb score), `provider` (a TMDB provider id that streams it for free or on subscription
    in the stored region) and `min_match` (Match %, needs a personal sort and a signed-in user)."""
    where, p = ["true"], {}
    kinds = media_kinds(type, genre)
    where.append("m.title_type = ANY(:kinds)"); p["kinds"] = kinds
    if genre == ANIME_SLUG:
        where.append(f"m.original_language = 'ja' AND {ANIMATION_IDS}")
    elif genre:
        where.append("m.id IN (SELECT mg.movie_id FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE g.slug = :genre)")
        p["genre"] = genre
        if genre == ANIMATION_SLUG:
            where.append("m.original_language IS DISTINCT FROM 'ja'")  # Japanese animation is Anime, not Animation
    vw, vp = vibe_where(vibe)
    if vw:
        where.append(vw); p.update(vp)
    if genre == ANIME_SLUG:
        # Anime genres, themes and avoided tags: any chosen tag (OR), none of the avoided ones; AND with everything else.
        aw, ap = anime_tags_mod.where(anime_tags_mod.parse(anime_tags), anime_tags_mod.parse(anime_avoid))
        where.extend(aw); p.update(ap)
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
    personal = sort in PERSONAL_SORTS and uid is not None and rec.artifacts_ready()
    if personal and any(k != "movie" for k in kinds):
        # Shows (series and anime) have no ratings: they are ranked by taste similarity plus popularity (kind_rank).
        # Films are ranked by the hybrid. When both are asked for, the two lists are woven together by relative position.
        ranked, extra = mixed_order(db, uid, " AND ".join(where), p, order, sort, kinds, min_match)
        start = (max(page, 1) - 1) * 40
        shown = ranked[start:start + 40]
        return {"items": cards(db, shown, uid, {i: extra[i] for i in shown if i in extra}),
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
# "Recommended for you" on Discover: list length at which the novelty and Tune bonuses keep their full size (personal_order).
BONUS_REFERENCE_LIST = 1000

# `type` on /movies: movie (default), show (TV series and anime TV), series, anime, all (films and shows).
MEDIA_KINDS = {"movie": ["movie"], "series": ["series"], "anime": ["anime"], "show": ["series", "anime"],
               "all": ["movie", "series", "anime"]}


VIBES = {"feelgood", "romance"}
FEEL_GOOD_GENRES = ["Comedy", "Romance", "Family", "Animation", "Music"]
DARK_GENRES = ["Horror", "Crime", "War", "Thriller", "War & Politics", "Mystery"]


def vibe_where(vibe: str | None) -> tuple[str | None, dict]:
    """SQL for a mood chip that works on any genre page or Discover list, for films AND shows.
    feelgood: a light genre (comedy, romance, family, animation, music) and no dark one, decently rated.
    romance: the Romance genre, or (TV has no Romance genre) a romance/love keyword or the Soap genre."""
    if vibe == "feelgood":
        return ("EXISTS (SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id AND g.name = ANY(:vg)) "
                "AND NOT EXISTS (SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id AND g.name = ANY(:vdark)) "
                "AND m.popularity_score >= 6.5", {"vg": FEEL_GOOD_GENRES, "vdark": DARK_GENRES})
    if vibe == "romance":
        return ("(EXISTS (SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id AND g.name IN ('Romance', 'Soap')) "
                "OR EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id "
                "WHERE mk.movie_id = m.id AND (k.name ILIKE '%romance%' OR k.name = 'love')))", {})
    return None, {}


def media_kinds(type: str | None, genre: str | None) -> list[str]:
    """Which title_type values a request covers. Anime TV is stored as 'anime', other TV as 'series'; both are Shows."""
    kinds = MEDIA_KINDS.get(type or "movie", ["movie"])
    if genre == ANIME_SLUG:
        return [k for k in kinds if k != "series"] or ["anime"]   # anime = films plus title_type 'anime' (TV anime), never plain series
    return kinds


def mixed_order(db: Session, uid: int, where: str, p: dict, order: str, sort: str, kinds: list[str], min_match: int | None):
    """Ids best first for a request that includes shows, plus per-id score extras (Match % only for films)."""
    rows = db.execute(text(f"SELECT m.id, m.title_type FROM movies m WHERE {where} ORDER BY {order}"), p).all()
    film_ids = [r[0] for r in rows if r[1] == "movie"]
    show_ids = [r[0] for r in rows if r[1] != "movie"]
    lists: list[list[int]] = []
    extra: dict[int, dict] = {}
    if film_ids:
        ranked, scores, engine, stage = personal_order(db, uid, film_ids, sort)
        if min_match:
            ranked = [i for i in ranked if i in scores and engine.match(stage, scores[i]) >= min_match]
        for i in ranked:
            if i in scores:
                extra[i] = {"score": scores[i], "match_pct": engine.match(stage, scores[i])}
        lists.append(ranked)
    if show_ids and not min_match:
        engine = rec.load_engine(db)
        st = rec.user_state(db, uid, engine)
        allowed, pairs = set(show_ids), []
        for kind in sorted({k for k in kinds if k != "movie"}):
            r, sc = engine.kind_rank(st, kind)
            pairs += [(int(engine.cat.movie_ids[x]), float(y)) for x, y in zip(r, sc) if int(engine.cat.movie_ids[x]) in allowed]
        pairs.sort(key=lambda t: -t[1])
        seen = {i for i, _ in pairs}
        for i, sc in pairs:
            extra[i] = {"score": sc}
        lists.append([i for i, _ in pairs] + [i for i in show_ids if i not in seen])
    keyed = sorted(((j + 0.5) / len(lst), n, i) for n, lst in enumerate(lists) for j, i in enumerate(lst))
    return [i for _, _, i in keyed], extra


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
    recommended: hybrid percentile, re-ranked with the user's Tune sliders (novelty and the slider boosts), whose
    reach is capped at what it is on a 1,000-film list (BONUS_REFERENCE_LIST) so on long lists taste still leads;
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
        bonus = (0.05 + 0.15 * tuning.shift("hidden")) * engine.cat.novelty[r] + engine._tuning_boost(r, tuning)
        # The bonus is on the percentile scale, so its reach grows with the list: +0.05 is 60 places on a 1,200-film
        # genre list but 1,350 places over all 27,000 films, where it beat taste and filled the top with little-known
        # (mostly non-MovieLens, often Hindi) films. Keep its reach in places as on a 1,000-film list.
        key = pct + bonus * min(1.0, BONUS_REFERENCE_LIST / max(int(ok.sum()), 1))
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
def genre_movies(slug: str, request: Request, page: int = 1, type: str = "all", vibe: str | None = None,
                 anime_tags: str | None = None, anime_avoid: str | None = None, db: Session = Depends(get_db)) -> dict:
    """A genre page lists films AND shows (type=all, the default), only films (movie) or only shows (show), ranked for
    this user: films by the hybrid, shows by taste similarity, woven together by relative position. Anime is Japanese
    animation (TV anime and animated films); Animation is the rest."""
    if slug == ANIME_SLUG:
        name = "Anime"
    else:
        g = db.execute(text("SELECT id, name FROM genres WHERE slug = :s"), {"s": slug}).first()
        if g is None:
            raise HTTPException(404, "Unknown genre")
        name = g[1]
    if type not in ("all", "movie", "show"):
        type = "all"
    return discover(request, genre=slug, sort="recommended", page=page, type=type, vibe=vibe,
                    anime_tags=anime_tags, anime_avoid=anime_avoid, db=db) | {"genre": name}


@router.get("/genres/anime/tags")
def anime_tag_options(db: Session = Depends(get_db)) -> dict:
    """The anime genre, theme and mature filters that have enough titles in the catalog, with live counts."""
    return {"tags": anime_tags_mod.counts(db, ANIMATION_IDS), "min_titles": anime_tags_mod.MIN_TITLES}
