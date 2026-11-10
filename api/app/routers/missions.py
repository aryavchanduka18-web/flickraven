"""Your Discovery Journey: missions with live progress, why each was picked, dismissals and completion dates.

Progress is read from real activity (watched, rated, liked) every time; only dismissals and the completion date of
a personal genre mission are stored (mission_state). The rules live in app/services/missions.py."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.services import missions as ms
from app.services.movies import cards

router = APIRouter(tags=["missions"])
CORE = ("world", "languages", "classics", "decades", "mini_series")
TASTE_MIN_TITLES = 5            # below this, Taste DNA has too little evidence to order ideas
CANDIDATES = 30
IDEAS = 8

SUGGESTIONS = {
    "world": "m.title_type = 'movie' AND NOT (m.countries && ARRAY['US','IN']::text[])",
    "languages": "m.original_language <> :main_lang",
    "classics": "m.title_type = 'movie' AND m.year < 1980",
    "decades": "m.title_type = 'movie' AND m.year IS NOT NULL AND NOT (m.year / 10 = ANY(CAST(:decades AS int[])))",
    "mini_series": "m.title_type = 'series' AND m.episodes BETWEEN 1 AND 8 AND m.series_status IN ('Ended', 'Canceled')",
    "genre": "m.title_type = 'movie' AND EXISTS (SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id "
             "WHERE mg.movie_id = m.id AND g.name = :genre)",
}
SEEN_SQL = """SELECT movie_id FROM watched WHERE user_id = :u UNION SELECT movie_id FROM ratings WHERE user_id = :u
              UNION SELECT movie_id FROM reactions WHERE user_id = :u AND value > 0"""


def _titles(db: Session, uid: int) -> list[dict]:
    """What the user watched, rated or liked, with when they first did it."""
    return [dict(r) for r in db.execute(text(f"""
        SELECT m.id, m.countries, m.original_language AS lang, m.year, m.title_type, m.episodes,
               ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres,
               (SELECT min(t) FROM (
                   SELECT marked_at AS t FROM watched WHERE user_id = :u AND movie_id = m.id
                   UNION ALL SELECT created_at FROM ratings WHERE user_id = :u AND movie_id = m.id
                   UNION ALL SELECT updated_at FROM reactions WHERE user_id = :u AND movie_id = m.id AND value > 0) x) AS at
        FROM movies m WHERE m.id IN ({SEEN_SQL})"""), {"u": uid}).mappings()]


def build(db: Session, uid: int) -> tuple[list[dict], list[ms.Mission], list[dict]]:
    """(missions as dicts with tab/why/dates, the Mission objects, the user's titles). Records which personal genre
    missions the user has started or finished, so they stay on the page."""
    titles = _titles(db, uid)
    state = {r[0]: (r[1], r[2]) for r in db.execute(
        text("SELECT mission_key, dismissed_at, completed_at FROM mission_state WHERE user_id = :u"), {"u": uid})}
    state_genres = [k[6:] for k in state if k.startswith("genre:")]
    by_size = [r[0] for r in db.execute(text("""SELECT g.name FROM genres g JOIN movie_genres mg ON g.id = mg.genre_id
        GROUP BY g.name ORDER BY count(*) DESC"""))]
    picks = ms.pick_new_genres(titles, by_size, set(state_genres), 1 + ms.ALT_GENRES)
    all_missions = ms.progress(titles, picks + sorted(state_genres))
    by_key = {m.key: m for m in all_missions}
    # a genre we assigned earlier and the user has not touched is still their pick; otherwise the first new one is
    pending = [g for g in state_genres if state[f"genre:{g}"][0] is None and not by_key[f"genre:{g}"].done
               and by_key[f"genre:{g}"].progress == 0]
    primary_genres = set(pending) if pending else set(picks[:1])
    writes = []
    for m in all_missions:
        if not m.key.startswith("genre:"):
            continue
        g = m.key[6:]
        stored = state.get(m.key)
        if stored and stored[1] and m.done:
            m.completed_at = stored[1]                      # keep the date we first recorded
        if g in primary_genres or m.progress > 0:           # remember the genre so it stays after it is finished
            if stored is None or (m.done and stored[1] is None):
                writes.append((m.key, m.completed_at if m.done else None))
    for key, done_at in writes:
        db.execute(text("""INSERT INTO mission_state (user_id, mission_key, completed_at) VALUES (:u, :k, :c)
            ON CONFLICT (user_id, mission_key) DO UPDATE SET completed_at = coalesce(mission_state.completed_at, EXCLUDED.completed_at)"""),
                   {"u": uid, "k": key, "c": done_at})
    if writes:
        db.commit()
    out = []
    for m in all_missions:
        dismissed = state.get(m.key, (None, None))[0] is not None
        primary = m.key in CORE or m.key[6:] in primary_genres
        out.append({"key": m.key, "title": m.title, "description": m.description, "why": m.why, "goal": m.goal,
                    "progress": m.progress, "done": m.done, "dismissed": dismissed, "relevance": m.relevance,
                    "completed_at": m.completed_at.isoformat() if m.completed_at else None,
                    "tab": ms.tab(m, dismissed, primary)})
    order = {"active": 0, "recommended": 1, "completed": 2, "explore": 3}
    out.sort(key=lambda d: (order[d["tab"]], -d["relevance"], d["key"]))
    return out, all_missions, titles


def _ideas(db: Session, uid: int, key: str, titles: list[dict], profile, hidden_sql: str) -> tuple[list[dict], bool]:
    """A few well-known titles the user has not seen for one mission. When Taste DNA has enough evidence they are
    re-ordered by how well they fit it (and the page says so); otherwise by popularity."""
    kind = "genre" if key.startswith("genre:") else key
    decades = sorted({t["year"] // 10 for t in titles if t["title_type"] == "movie" and t["year"]})
    params = {"u": uid, "main_lang": ms.main_language(titles) or "en", "genre": key[6:] if key.startswith("genre:") else None,
              "decades": decades}
    ids = [r[0] for r in db.execute(text(f"""
        SELECT m.id FROM movies m WHERE {SUGGESTIONS[kind]} AND m.backdrop_path IS NOT NULL
          AND m.id NOT IN ({hidden_sql}) AND coalesce(m.popularity_score, 0) >= 6.5
        ORDER BY m.tmdb_vote_count DESC NULLS LAST LIMIT {CANDIDATES if profile else IDEAS}"""), params)]
    ranked = False
    if profile and ids:
        from app.services import taste_dna as dna
        vectors = dna.title_vectors(db, ids)
        scores = {i: dna.fit(profile, vectors.get(i))[0] for i in ids}
        if any(s is not None for s in scores.values()):
            ids = sorted(ids, key=lambda i: (scores[i] is None, -(scores[i] or 0)))      # stable: ties keep popularity order
            ranked = True
        ids = ids[:IDEAS]
    return cards(db, ids, uid), ranked


@router.get("/me/missions")
def missions(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Your Discovery Journey: every mission with its tab (recommended, active, completed, explore), why it was
    picked, progress from real activity, the completion date, and ideas for the open ones."""
    uid = user["id"]
    out, _, titles = build(db, uid)
    profile = None
    try:
        from app.routers.taste import profile_for
        p, _ = profile_for(db, uid)
        profile = p if p.titles >= TASTE_MIN_TITLES else None
    except Exception:                                       # Taste DNA is an extra; the missions work without it
        profile = None
    hidden_sql = f"{SEEN_SQL} UNION SELECT movie_id FROM reactions WHERE user_id = :u AND value < 0"
    for m in out:
        if m["done"] or m["tab"] == "explore" and m["dismissed"]:
            m["suggestions"], m["ranked_by_taste"] = [], False
        else:
            m["suggestions"], m["ranked_by_taste"] = _ideas(db, uid, m["key"], titles, profile, hidden_sql)
    counts = {t: sum(1 for m in out if m["tab"] == t) for t in ("recommended", "active", "completed", "explore")}
    return {"missions": out, "counts": counts}


def _known(db: Session, uid: int, key: str) -> None:
    out, _, _ = build(db, uid)
    if key not in {m["key"] for m in out}:
        raise HTTPException(404, "Unknown mission")


@router.put("/me/missions/{key}/dismiss")
def dismiss(key: str, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Hide a mission you do not want. It moves to Explore, where you can bring it back."""
    _known(db, user["id"], key)
    db.execute(text("""INSERT INTO mission_state (user_id, mission_key, dismissed_at) VALUES (:u, :k, now())
        ON CONFLICT (user_id, mission_key) DO UPDATE SET dismissed_at = now()"""), {"u": user["id"], "k": key})
    db.commit()
    return {"key": key, "dismissed": True}


@router.delete("/me/missions/{key}/dismiss")
def restore(key: str, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _known(db, user["id"], key)
    db.execute(text("UPDATE mission_state SET dismissed_at = NULL WHERE user_id = :u AND mission_key = :k"),
               {"u": user["id"], "k": key})
    db.commit()
    return {"key": key, "dismissed": False}
