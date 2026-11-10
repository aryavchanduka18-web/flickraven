"""Taste DNA: optional "what did you enjoy" tags, the user's trait profile, Refine My Taste, and the Taste DNA row.

The maths and the provenance rules live in app/services/taste_dna.py. Nothing here changes the hybrid score."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.services import events as ev
from app.services import taste_dna as dna
from app.services.movies import cards

router = APIRouter(tags=["taste"])
RECENT_DAYS = 30
MAX_TAGS = 12


def signals(db: Session, uid: int, since: datetime | None = None) -> dna.Signals:
    """Weights per title from stored activity (see taste_dna). `since`: only titles acted on after that time."""
    p = {"u": uid}
    w: dict[int, float] = {}
    for mid, r in db.execute(text("SELECT movie_id, rating FROM ratings WHERE user_id = :u"), p):
        w[mid] = (r - 6) / 4 if r >= 7 else -(5 - r) / 4 if r <= 4 else 0.0
    for mid, v in db.execute(text("SELECT movie_id, value FROM reactions WHERE user_id = :u"), p):
        if mid not in w or w[mid] == 0:
            w[mid] = 1.0 if v > 0 else -1.0
    for (mid,) in db.execute(text("SELECT movie_id FROM onboarding_picks WHERE user_id = :u"), p):
        w.setdefault(mid, 0.5)
    for (mid,) in db.execute(text("SELECT movie_id FROM watched WHERE user_id = :u"), p):
        w.setdefault(mid, 0.3)
    tags = [(m, t) for m, t in db.execute(text("SELECT movie_id, tag FROM title_feedback_tags WHERE user_id = :u"), p)]
    if since is not None:
        recent = {m for (m,) in db.execute(text("""SELECT DISTINCT movie_id FROM interactions WHERE user_id = :u
            AND created_at >= :s AND movie_id IS NOT NULL AND event_type IN ('rate', 'like', 'dislike', 'watched', 'taste_tags')"""),
                                           {**p, "s": since})}
        w = {m: x for m, x in w.items() if m in recent}
        tags = [(m, t) for m, t in tags if m in recent]
    over = db.execute(text("SELECT taste_overrides FROM user_preferences WHERE user_id = :u"), p).scalar() or {}
    return dna.Signals(weights={m: x for m, x in w.items() if x}, tags=tags, overrides=over)


def profile_for(db: Session, uid: int, since: datetime | None = None) -> tuple[dna.Profile, dna.Signals]:
    sig = signals(db, uid, since)
    mean, _ = dna.catalog_mean(db)
    vectors = dna.title_vectors(db, list(sig.weights))
    return dna.build_profile(sig, vectors, mean), sig


# ------------------------------------------------------------------ tags after rating
class TagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


def tag_options() -> dict:
    return {"liked": [{"key": k, "label": l} for k, (l, _) in dna.LIKED_TAGS.items()],
            "disliked": [{"key": k, "label": l} for k, (l, _, _) in dna.DISLIKED_TAGS.items()]}


@router.get("/feedback/tags/{movie_id}")
def get_tags(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    mine = [t for (t,) in db.execute(text("SELECT tag FROM title_feedback_tags WHERE user_id = :u AND movie_id = :m ORDER BY tag"),
                                     {"u": user["id"], "m": movie_id})]
    return {"tags": mine, "options": tag_options()}


@router.put("/feedback/tags/{movie_id}")
def put_tags(movie_id: int, body: TagsBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Replace your tags for one title. Only for titles you rated, liked, disliked or marked watched: a tag is an
    opinion about something you saw."""
    tags = list(dict.fromkeys(body.tags))
    bad = [t for t in tags if t not in dna.LIKED_TAGS and t not in dna.DISLIKED_TAGS]
    if bad:
        raise HTTPException(422, f"Unknown tags: {', '.join(sorted(bad)[:5])}")
    uid = user["id"]
    p = {"u": uid, "m": movie_id}
    if not db.execute(text("SELECT 1 FROM movies WHERE id = :m"), p).first():
        raise HTTPException(404, "Title not found")
    seen = db.execute(text("""SELECT 1 FROM ratings WHERE user_id = :u AND movie_id = :m
        UNION ALL SELECT 1 FROM reactions WHERE user_id = :u AND movie_id = :m
        UNION ALL SELECT 1 FROM watched WHERE user_id = :u AND movie_id = :m LIMIT 1"""), p).first()
    if not seen:
        raise HTTPException(409, "Rate this title (or mark it watched) before saying what you liked about it")
    db.execute(text("DELETE FROM title_feedback_tags WHERE user_id = :u AND movie_id = :m"), p)
    for t in tags:
        db.execute(text("INSERT INTO title_feedback_tags (user_id, movie_id, tag) VALUES (:u, :m, :t)"), {**p, "t": t})
    ev.log(db, uid, movie_id, "taste_tags", float(len(tags)), ",".join(tags)[:200] or None)
    db.commit()
    return {"tags": tags}


# ------------------------------------------------------------------ the profile page
def _trait_rows(prof: dna.Profile, coverage: dict[str, float]) -> list[dict]:
    out = []
    for t in dna.TRAITS:
        k = t.key
        out.append({
            "key": k, "label": t.label,
            "you": round(100 * prof.liking[k]), "catalog": round(100 * prof.mean[k]),
            "avoid": round(100 * prof.aversion[k]),
            "evidence": int(prof.n_like[k]), "evidence_against": int(prof.n_dislike[k]),
            "override": prof.overrides.get(k),
            "source": "viewers" if k == "dialogue" else "keywords",
            "catalog_coverage": round(100 * coverage.get(k, 0)),
        })
    return out


@router.get("/me/taste-dna")
def taste_dna(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    uid = user["id"]
    prof, sig = profile_for(db, uid)
    _, coverage = dna.catalog_mean(db)
    recent, _ = profile_for(db, uid, datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS))
    liked_ids = [m for m, w in sig.weights.items() if w > 0]
    p = {"ids": liked_ids or [-1]}
    genres = [g for g, _ in db.execute(text("""SELECT g.name, count(*) n FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = ANY(:ids) GROUP BY g.name ORDER BY n DESC, g.name LIMIT 6"""), p)]
    langs = [l for l, _ in db.execute(text("""SELECT original_language, count(*) n FROM movies WHERE id = ANY(:ids)
        AND original_language IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT 4"""), p)]
    countries = [c for c, _ in db.execute(text("""SELECT c, count(*) n FROM movies, unnest(countries) c WHERE id = ANY(:ids)
        GROUP BY c ORDER BY n DESC, c LIMIT 5"""), p)]
    from cinematch_engine.online import LANGUAGE_NAMES
    lang_names = [LANGUAGE_NAMES.get(l, l) for l in langs]
    rising = [k for k in recent.preferred()
              if recent.n_like[k] >= 2 and recent.liking[k] - prof.liking[k] >= 0.05 and k not in prof.preferred()[:2]]
    tagged = len({m for m, _ in sig.tags})
    return {
        "ready": prof.titles >= 3,
        "titles_used": prof.titles, "titles_tagged": tagged,
        "traits": _trait_rows(prof, coverage),
        "radar": dna.RADAR,
        "preferred": prof.preferred()[:6],
        "avoided": prof.avoided()[:4],
        "rising": rising[:3],
        "top_genres": genres, "top_languages": lang_names, "top_countries": countries,
        "pacing": _pacing(prof), "complexity": _level(prof, "complexity"),
        "personality": dna.personality(prof, genres, lang_names),
        "tag_options": tag_options(),
    }


def _pacing(prof: dna.Profile) -> str | None:
    if prof.titles < 3:
        return None
    fast, slow = prof.lean("fast"), prof.lean("slow_burn")
    if fast >= dna.MIN_LEAN and fast > slow:
        return "Leans fast"
    if slow >= dna.MIN_LEAN and slow > fast:
        return "Leans slow-burn"
    return "No clear lean"


def _level(prof: dna.Profile, k: str) -> str | None:
    if prof.titles < 3:
        return None
    lean = prof.lean(k)
    return "Higher than average" if lean >= dna.MIN_LEAN else "Lower than average" if lean <= -dna.MIN_LEAN else "About average"


class OverridesBody(BaseModel):
    overrides: dict[str, str | None]


@router.put("/me/taste-dna/overrides")
def put_overrides(body: OverridesBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Refine My Taste: set traits to "more" or "less", or null to go back to what your activity says."""
    for k, v in body.overrides.items():
        if k not in dna.TRAIT or v not in (*dna.OVERRIDES, None):
            raise HTTPException(422, f"Unknown trait or value: {k}={v}")
    uid = user["id"]
    cur = db.execute(text("SELECT taste_overrides FROM user_preferences WHERE user_id = :u"), {"u": uid}).scalar() or {}
    new = {**cur, **body.overrides}
    new = {k: v for k, v in new.items() if v}
    db.execute(text("""INSERT INTO user_preferences (user_id, taste_overrides) VALUES (:u, CAST(:o AS jsonb))
        ON CONFLICT (user_id) DO UPDATE SET taste_overrides = CAST(:o AS jsonb), updated_at = now()"""),
               {"u": uid, "o": json.dumps(new)})
    db.commit()
    return {"overrides": new}


# ------------------------------------------------------------------ the Taste DNA row and per-title explanation
POOL = 300


@router.get("/recs/taste-dna")
def taste_picks(limit: int = 20, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The recommender's own top POOL films for you (hybrid candidates, unchanged), re-ordered by Taste DNA fit.
    A separate row: the hybrid ranking elsewhere is untouched. Empty until the profile has 3 titles."""
    from app.routers.recs import engine_or_503, log_shown
    from app.services import recommender as rec
    import uuid
    uid = user["id"]
    prof, _ = profile_for(db, uid)
    if prof.titles < 3 and not prof.overrides:
        return {"items": [], "ready": False}
    engine = engine_or_503(db)
    st = rec.user_state(db, uid, engine)
    scores = engine.rail_scores(st)
    finite = np.where(np.isfinite(scores))[0]
    top = finite[np.argsort(-scores[finite])][:POOL]
    ids = [int(engine.cat.movie_ids[r]) for r in top]
    hybrid = {int(engine.cat.movie_ids[r]): float(scores[r]) for r in top}
    vecs = dna.title_vectors(db, ids)
    scored = []
    for i in ids:
        s, because = dna.fit(prof, vecs.get(i))
        if s is not None and because:
            scored.append((s, i, because))
    scored.sort(key=lambda x: -x[0])
    chosen = scored[:max(1, min(limit, 40))]
    extra = {i: {"score": hybrid[i], "match_pct": engine.match(st.stage, hybrid[i]),
                 "reasons": [{"code": "taste_dna", "source": "taste_dna", "text": dna.reason(b), "share": 1.0}]} for _, i, b in chosen}
    items = cards(db, [i for _, i, _ in chosen], uid, extra)
    log_shown(db, uid, str(uuid.uuid4()), None, "taste_dna", None, items)
    db.commit()
    return {"items": items, "ready": True}


@router.get("/movies/{movie_id}/taste-dna")
def title_fit(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Which of your Taste DNA traits this title has (only traits backed by your activity), with the source."""
    prof, _ = profile_for(db, user["id"])
    v = dna.title_vectors(db, [movie_id]).get(movie_id)
    if prof.titles < 3 or not v:
        return {"reason": None, "traits": [], "known": v is not None}
    _, because = dna.fit(prof, v)
    clash = [k for k in prof.avoided() if v.get(k, 0) >= 0.5]
    return {"reason": dna.reason(because), "traits": [dna.TRAIT[k].label for k in because],
            "clash": [dna.TRAIT[k].label for k in clash], "known": True}


@router.get("/me/taste-evolution")
def taste_evolution(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Genres of the titles the person liked or rated 7+, by month (last 6 months with activity), and what rose or fell
    between the earlier months and the latest two. Counts only; see app/services/taste_evolution.py."""
    from app.services import taste_evolution as ev
    rows = db.execute(text("""SELECT to_char(t.at, 'YYYY-MM') AS month,
            ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = t.movie_id) AS genres
        FROM (SELECT movie_id, created_at AS at FROM ratings WHERE user_id = :u AND rating >= 7
              UNION SELECT movie_id, updated_at FROM reactions WHERE user_id = :u AND value = 1) t"""), {"u": user["id"]}).all()
    events = [(r[0], list(r[1])) for r in rows]
    return {"months": ev.by_month(events), "shift": ev.shift(events), "titles": len(events)}
