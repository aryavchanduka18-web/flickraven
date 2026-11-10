"""Recommendations: home page plan, rails, For Tonight, Surprise Me, explanations."""
import uuid

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.services import recommender as rec
from app.services import series_fit as fit
from app.services import series_rails as series_rails_service
from app.services.confidence import agreement_all, confidence
from app.services.movies import cards
from cinematch_engine.tonight import Request as TonightRequest

router = APIRouter(prefix="/recs", tags=["recs"])


def engine_or_503(db):
    if not rec.artifacts_ready():
        raise HTTPException(503, "Recommendation models are not built yet (run the pipeline)")
    return rec.load_engine(db)


def mode_of(db, uid, mode):
    if mode in ("familiar", "balanced", "discover"):
        return mode
    return db.execute(text("SELECT discovery_mode FROM user_preferences WHERE user_id = :u"), {"u": uid}).scalar() or "balanced"


def log_shown(db, uid, request_id, page_id, surface, mode, items):
    for rank, it in enumerate(items):
        db.execute(text("""INSERT INTO recommendation_logs (request_id, user_id, surface, movie_id, rank, final_score,
            match_pct, components, reason_code, mode, page_id) VALUES (:r, :u, :s, :m, :k, :f, :p, CAST(:c AS jsonb), :rc, :mo, :pg)"""),
                   {"r": request_id, "u": uid, "s": surface, "m": it["movie"]["id"], "k": rank, "f": it.get("score"),
                    "p": it.get("match_pct"), "c": __import__("json").dumps(it.get("components") or {}),
                    "rc": it["reasons"][0]["code"] if it.get("reasons") else None, "mo": mode, "pg": page_id})


@router.get("/kind/{kind}")
def kind_rail(kind: str, limit: int = 24, offset: int = 0, user=Depends(current_user),
              db: Session = Depends(get_db)) -> dict:
    """Series or anime for this user (Home rows). No ratings exist for them: content similarity to the user's
    taste plus TMDB popularity, so there is no Match %."""
    if kind not in ("series", "anime"):
        raise HTTPException(404, "Unknown kind")
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    rows, scores = engine.kind_rank(st, kind)
    page = slice(max(offset, 0), max(offset, 0) + min(limit, 60))
    extra = {int(engine.cat.movie_ids[r]): {"score": float(s)} for r, s in zip(rows[page], scores[page])}
    items = cards(db, list(extra), user["id"], extra)
    log_shown(db, user["id"], str(uuid.uuid4()), None, f"kind_{kind}", None, items)   # so the report counts series too
    db.commit()
    return {"items": items, "total": int(len(rows))}


@router.get("/series-rails")
def series_rails(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Themed series rows for Home (see app/services/series_rails.py), a "because you liked ..." row from the series
    the user liked or rated 7+, and one row that mixes films and series. Ordered for this user like the Series row.
    There is no Match % on any of them (series have no ratings here)."""
    engine = engine_or_503(db)
    uid = user["id"]
    st = rec.user_state(db, uid, engine)
    cat = engine.cat
    rows, scores = engine.kind_rank(st, "series")
    ranked = [int(cat.movie_ids[r]) for r in rows]
    series = [{"id": r["id"], "lang": r["original_language"], "countries": r["countries"] or [], "seasons": r["seasons"],
               "episodes": r["episodes"], "runtime": r["runtime_min"], "status": r["series_status"],
               "genres": list(r["genres"]), "popularity": float(r["popularity_score"] or 0), "votes": r["tmdb_vote_count"] or 0,
               "has_art": r["backdrop_path"] is not None}
              for r in db.execute(text("""
                SELECT m.id, m.original_language, m.countries, m.seasons, m.episodes, m.runtime_min, m.series_status,
                       m.popularity_score, m.tmdb_vote_count, m.backdrop_path,
                       ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres
                FROM movies m WHERE m.title_type = 'series'""")).mappings()]
    rails = [{"key": t["key"], "title": t["title"], "subtitle": t["subtitle"], "ids": t["ids"]}
             for t in series_rails_service.build(series, ranked)]

    # "Because you liked X": the series most like the one the user liked or rated highest.
    liked = {r: 1.0 for r in st.likes | st.picks}
    liked.update({r: (v - 6) / 4 for r, v in st.ratings.items() if v >= 7})
    liked = {r: w for r, w in liked.items() if cat.kind[r] == "series"}
    if liked:
        base = min(liked, key=lambda r: (-liked[r], r))
        seen = set(rows.tolist())
        similar = [int(cat.movie_ids[r]) for r in engine.similar(base, k=120) if cat.kind[r] == "series" and r in seen][:20]
        if len(similar) >= series_rails_service.MIN_ROW:
            rails.insert(0, {"key": "because", "title": f"Because you liked {cat.titles[base]}",
                             "subtitle": "Series with a similar feel.", "ids": similar})

    # Films and series, alternating.
    film_scores = engine.rail_scores(st)
    films = [int(cat.movie_ids[r]) for r in np.argsort(-film_scores)[:30] if np.isfinite(film_scores[r])][:12]
    mixed = series_rails_service.interleave(films, ranked[:12])
    if len(mixed) >= series_rails_service.MIN_ROW:
        rails.append({"key": "mix", "title": "Films and series picked for you", "subtitle": "A mix of both.", "ids": mixed})

    out = []
    request_id = str(uuid.uuid4())
    for r in rails:
        items = cards(db, r["ids"], uid)
        if len(items) >= series_rails_service.MIN_ROW:
            out.append({"key": r["key"], "title": r["title"], "subtitle": r["subtitle"], "items": items})
            log_shown(db, uid, request_id, None, f"series_{r['key']}", None, items)   # the report counts series too
    db.commit()
    return {"rails": out}


NEXT_BUDGET = {"3": "5", "5": "10", "10": "20", "20": "long"}


@router.get("/series-fit")
def series_fit(budget: str = "", status: str = "", episode_length: str = "", series_type: str = "", genre: str = "",
               language: str = "", sort: str = "best", per_day: int = 2, user=Depends(current_user),
               db: Session = Depends(get_db)) -> dict:
    """Series that fit the time the user has (see app/services/series_fit.py), each with seasons, episodes, total
    hours and days to finish at `per_day` episodes a day (0 = flexible: no schedule). "best" is the user's own series
    ranking (series have no Match %: there are no ratings for them). Series without an episode count or episode
    length are left out and counted in `unknown_length`; nothing is guessed."""
    if (budget not in ("", *fit.BUDGETS) or status not in ("", *fit.STATUS) or episode_length not in ("", *fit.EPISODE_LENGTHS)
            or series_type not in ("", *fit.SERIES_TYPES) or sort not in fit.SORTS):
        raise HTTPException(422, "Unknown filter value")
    per_day = max(0, min(per_day, 10))
    from app.config import get_settings
    show_imdb = get_settings().imdb_ratings
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    rows, _ = engine.kind_rank(st, "series")
    rank = {int(engine.cat.movie_ids[r]): n for n, r in enumerate(rows)}
    info = {r["id"]: dict(r) for r in db.execute(text("""SELECT m.id, m.episodes, m.seasons, m.runtime_min AS runtime,
        m.series_status AS status, m.original_language AS lang, m.imdb_rating AS rating,
        ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres
        FROM movies m WHERE m.title_type = 'series' AND m.backdrop_path IS NOT NULL""")).mappings()}
    pool = [i for i in rank if i in info]
    unknown = sum(1 for i in pool if fit.hours(info[i]["episodes"], info[i]["runtime"]) is None)
    matching = [i for i in pool if fit.fits(info[i], budget, status, episode_length, series_type, genre, language)]
    more = None
    if budget in NEXT_BUDGET:
        wider = sum(1 for i in pool if fit.fits(info[i], NEXT_BUDGET[budget], status, episode_length, series_type, genre, language))
        more = {"budget": NEXT_BUDGET[budget], "extra": wider - len(matching)}
    ordered = fit.order([{"id": i, "hours": fit.hours(info[i]["episodes"], info[i]["runtime"]), "status": info[i]["status"],
                          "rating": info[i]["rating"] if show_imdb else None, "rank": rank[i]} for i in matching], sort)
    ids = [o["id"] for o in ordered[:40]]
    items = cards(db, ids, user["id"])
    for it in items:
        s = info[it["movie"]["id"]]
        it["plan"] = fit.plan(s["episodes"], s["runtime"], per_day)
        it["series"] = {"seasons": s["seasons"], "episodes": s["episodes"], "runtime": s["runtime"], "status": s["status"],
                        "hours": fit.hours(s["episodes"], s["runtime"])}
    languages = sorted({info[i]["lang"] for i in pool if info[i]["lang"]})
    genres = sorted({g for i in pool for g in info[i]["genres"]})
    return {"items": items, "total": len(matching), "unknown_length": unknown, "more_with_next_budget": more,
            "options": {"languages": languages, "genres": genres}}


@router.get("/home")
def home(mode: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    uid = user["id"]
    mode = mode_of(db, uid, mode)
    st = rec.user_state(db, uid, engine)
    scores = engine.scores(st)            # scored once: Home and the agreement numbers share it
    plan = engine.home(st, mode, tuning=rec.user_tuning(db, uid), recent_rows=rec.recent_positive_rows(db, uid, engine),
                       scores=scores)
    cat = engine.cat
    agree = agreement_all(engine, st, scores)
    request_id, page_id = str(uuid.uuid4()), str(uuid.uuid4())

    def agreement(row):
        return None if np.isnan(agree[row]) else int(agree[row])

    def scored_items(entries):
        extra = {}
        for e in entries:
            mid = int(cat.movie_ids[e["row"]])
            extra[mid] = {"score": e["score"], "match_pct": e["match_pct"], "components": e["shares"],
                          "reasons": engine.reasons(st, e["row"], e["shares"], e.get("reranked", False)),
                          "agreement": agreement(e["row"])}
        return cards(db, list(extra), uid, extra)

    hero = scored_items(plan["hero"])
    rails = []
    for r in plan["rails"]:
        if r["scored"]:
            items = scored_items([r["scored"][row] for row in r["rows"]])
        else:
            extra = {}
            for row in r["rows"]:
                s = float(plan["rail_scores"][row])
                extra[int(cat.movie_ids[row])] = {"score": s, "match_pct": engine.match(st.stage, s) if np.isfinite(s) else None,
                                                  "reasons": [r["reason"]] if r.get("reason") else [],
                                                  "agreement": agreement(row)}
            items = cards(db, list(extra), uid, extra)
        subtitle = None
        if r["key"] == "current_phase" and r["reason"].get("genre"):
            subtitle = (f"You've been into {r['reason']['genre'].lower()} films lately. "
                        "Recent likes, ratings and saves count more here than your older history.")
        rails.append({"key": r["key"], "title": r["title"], "subtitle": subtitle, "source": r["source"], "items": items})
        log_shown(db, uid, request_id, page_id, r["key"], mode, items)
    log_shown(db, uid, request_id, page_id, "hero", mode, hero)
    db.commit()
    return {"stage": plan["stage"], "mode": mode, "hero": hero, "rails": rails, "page_id": page_id}


class TonightBody(BaseModel):
    mood: str
    runtime: str | None = None
    languages: list[str] = []
    genres: list[str] = []


@router.post("/tonight")
def tonight(body: TonightBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    from cinematch_engine.tonight import moods
    if body.mood not in moods():
        raise HTTPException(422, f"mood must be one of {sorted(moods())}")
    st = rec.user_state(db, user["id"], engine)
    req = TonightRequest(body.mood, body.runtime, body.languages[0] if body.languages else None, body.genres)
    rows, relaxed, note = engine.tonight(st, req)
    scores = engine.rail_scores(st)
    extra = {int(engine.cat.movie_ids[r]): {"score": float(scores[r]), "match_pct": engine.match(st.stage, float(scores[r]))}
             for r in rows}
    items = cards(db, list(extra), user["id"], extra)
    log_shown(db, user["id"], str(uuid.uuid4()), None, "tonight", None, items)
    db.commit()
    return {"items": items, "relaxed": relaxed, "message": note}


@router.get("/surprise")
def surprise(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    pick = engine.surprise(st, np.random.default_rng())
    if pick is None:
        return {"item": None, "message": "Rate a few more films first, so we can surprise you well."}
    mid = int(engine.cat.movie_ids[pick["row"]])
    items = cards(db, [mid], user["id"], {mid: pick})
    log_shown(db, user["id"], str(uuid.uuid4()), None, "surprise_me", None, items)
    db.commit()
    return {"item": items[0]}


@router.get("/explain/{movie_id}")
def explain(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    row = engine.cat.row_of.get(movie_id)
    if row is None:
        raise HTTPException(404, "Unknown movie")
    from app.routers.catalog import _shares
    shares = _shares(engine, st, row)
    s = float(engine.rail_scores(st)[row])
    return {"movie_id": movie_id, "stage": st.stage, "behavioral_count": st.behavioral_count,
            "onboarding_count": len(st.picks), "shares": shares,
            "match_pct": engine.match(st.stage, s) if np.isfinite(s) else None,
            "reasons": engine.reasons(st, row, shares), "weights": engine.weights[st.stage],
            "confidence": confidence(engine, st, row, engine.match(st.stage, s) if np.isfinite(s) else None)}