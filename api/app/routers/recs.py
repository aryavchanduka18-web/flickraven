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
    return {"items": cards(db, list(extra), user["id"], extra), "total": int(len(rows))}


@router.get("/home")
def home(mode: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    uid = user["id"]
    mode = mode_of(db, uid, mode)
    st = rec.user_state(db, uid, engine)
    plan = engine.home(st, mode, tuning=rec.user_tuning(db, uid), recent_rows=rec.recent_positive_rows(db, uid, engine))
    cat = engine.cat
    agree = agreement_all(engine, st, engine.scores(st))
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