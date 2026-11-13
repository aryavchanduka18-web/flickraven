"""Wraps cinematch_engine for API requests.

At startup (first use) it loads the offline artifacts (fitted models, tuned content features,
stage weights, Match % calibrator) and the catalog from Postgres, and builds one OnlineEngine.
Per request, it reads the user's current state from Postgres (ratings, reactions, list, watched,
onboarding, events) and asks the engine. Nothing personal is cached (spec 6.12 freshness).
"""
import ctypes
import gc
import json
import logging
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy.sparse as sp
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from cinematch_engine import ai_graph
from cinematch_engine.availability import AvailabilityMap
from cinematch_engine.online import Catalog, OnlineEngine, Tuning, UserState
from cinematch_engine.profile import BEHAVIORAL_EVENTS
from cinematch_engine.sources import SourceModels

from app.services import artifact_store

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "artifacts" / "models"
_lock = threading.Lock()
_engine: OnlineEngine | None = None


REQUIRED = ("fitted.npz", "content_matrix.npz", "content_rows.parquet", "hybrid_weights.json", "calibration.joblib",
            "train_ratings.npz")


def artifacts_ready() -> bool:
    if all((MODELS / f).exists() for f in REQUIRED):
        return True
    artifact_store.try_sync()      # hosted copy: the bundle may have been uploaded after start-up
    return all((MODELS / f).exists() for f in REQUIRED)


def _settings(name: str) -> dict:
    return json.loads((MODELS / f"{name}.json").read_text(encoding="utf-8"))["settings"]


LEARNED_FILES = ("drama_neighbors.json", "anime_neighbors.json")


def _series_similarities(tmdb_ids: list[int]) -> sp.csr_matrix | None:
    """Learned series and anime similarities (artifacts/models/drama_neighbors.json from MyDramaList and
    anime_neighbors.json from the Kaggle anime lists, made by pipeline/drama_cf.py and pipeline/anime_cf.py; only
    the similarities are kept) as one n x n matrix over the catalog rows, or None when no file exists."""
    files = [MODELS / f for f in LEARNED_FILES if (MODELS / f).exists()]
    if not files:
        return None
    row_of = {t: i for i, t in enumerate(tmdb_ids)}
    rows, cols, vals = [], [], []
    for path in files:
        for a, nbs in json.loads(path.read_text(encoding="utf-8"))["neighbors"].items():
            for b, v in nbs:
                if int(a) in row_of and b in row_of:
                    rows.append(row_of[int(a)]); cols.append(row_of[b]); vals.append(v)
    n = len(tmdb_ids)
    sim = sp.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=np.float32)
    return sim.maximum(sim.T).tocsr()            # symmetric: a similar-to b means b similar-to a


def _gemini_similarities(movies: pd.DataFrame) -> sp.csr_matrix | None:
    """Series and anime that Gemini names as similar (artifacts/models/ai_similar.json, pipeline/ai_similar.py) as a
    catalog-row matrix (engine ai_graph.py), or None when the file is missing or unreadable."""
    path = MODELS / "ai_similar.json"
    if not path.exists():
        return None
    try:
        named = json.loads(path.read_text(encoding="utf-8")).get("titles", {})
    except (OSError, ValueError):
        log.warning("ai_similar.json could not be read; series ranking runs without it")
        return None
    return ai_graph.build(movies["tmdb_id"].tolist(), movies["title"].tolist(), movies["year"].astype(float).tolist(),
                          movies["title_type"].tolist(), named)


def _similar_table(tmdb_ids: list[int]) -> dict | None:
    """More Like This neighbours (artifacts/models/similar_titles.npz, made by pipeline/similar_titles.py), re-indexed
    to the catalog rows. Titles the file does not know (added later) have rows -1 and use the fallback formula.
    About 15 MB in memory for 33,000 titles x 40 neighbours."""
    path = MODELS / "similar_titles.npz"
    if not path.exists():
        return None
    f = np.load(path)
    row_of = {int(t): i for i, t in enumerate(tmdb_ids)}
    src = np.array([row_of.get(int(t), -1) for t in f["tmdb_ids"]], dtype=np.int64)    # file row -> catalog row
    f_rows, f_comps = f["rows"], f["comps"]             # read once: each npz access decompresses a new full copy
    n, k = len(tmdb_ids), f_rows.shape[1]
    rows = np.full((n, k), -1, dtype=np.int32)
    scores = np.zeros((n, k), dtype=np.float16)
    comps = np.zeros((f_comps.shape[0], n, k), dtype=np.uint8)
    have = src >= 0
    nb = f_rows[have]
    mapped = np.where(nb >= 0, src[np.maximum(nb, 0)], -1)
    # a neighbour that left the catalog is dropped and the rest move up, keeping their order
    order = np.argsort(mapped < 0, axis=1, kind="stable")
    take = lambda a: np.take_along_axis(a, order, axis=1)
    rows[src[have]] = take(mapped)
    scores[src[have]] = take(f["scores"][have])
    for i in range(comps.shape[0]):
        comps[i, src[have]] = take(f_comps[i][have])
    return {"rows": rows, "scores": scores, "comps": comps, "stored": [str(s) for s in f["stored"]]}


SNAPSHOT = "catalog_snapshot.parquet"
SNAPSHOT_COLUMNS = ["tmdb_id", "title", "original_language", "runtime_min", "year", "catalog_part", "title_type",
                    "genres", "keywords", "has_award"]


def _catalog_from_sql(db: Session) -> pd.DataFrame:
    """The whole catalogue from the database: one big query, about 7 MB over the wire."""
    return pd.DataFrame(db.execute(text("""
        SELECT m.id, m.tmdb_id, m.title, m.original_language, m.runtime_min, m.year, m.catalog_part, m.title_type,
               coalesce(m.popularity_score, 0) AS popularity, coalesce(m.tmdb_vote_count, 0) AS votes,
               coalesce(array_agg(DISTINCT g.name) FILTER (WHERE g.name IS NOT NULL), '{}') AS genres,
               coalesce(array_agg(DISTINCT k.name) FILTER (WHERE k.name IS NOT NULL), '{}') AS keywords,
               bool_or(a.id IS NOT NULL AND a.award NOT ILIKE 'Golden Raspberry%') AS has_award
        FROM movies m
        LEFT JOIN movie_genres mg ON mg.movie_id = m.id LEFT JOIN genres g ON g.id = mg.genre_id
        LEFT JOIN movie_keywords mk ON mk.movie_id = m.id LEFT JOIN keywords k ON k.id = mk.keyword_id
        LEFT JOIN movie_awards a ON a.movie_id = m.id
        GROUP BY m.id
    """)).mappings().all())


def _catalog_frame(db: Session) -> pd.DataFrame:
    """Catalogue rows for the engine. When the model bundle carries a snapshot (scripts/deploy_data.py export writes
    artifacts/models/catalog_snapshot.parquet) only ids and the two moving counts are read from the database, a small
    fraction of the big query, so every start and wake costs the hosted database far less network transfer. The
    snapshot is used only when its title set is exactly the database's; otherwise (catalogue refreshed without a
    new bundle) the full query runs, so the engine never mixes old text with new rows."""
    path = MODELS / SNAPSHOT
    if path.exists():
        try:
            snap = pd.read_parquet(path)
            light = pd.DataFrame(db.execute(text("""
                SELECT id, tmdb_id, coalesce(popularity_score, 0) AS popularity, coalesce(tmdb_vote_count, 0) AS votes
                FROM movies""")).mappings().all())
            if set(snap["tmdb_id"]) == set(light["tmdb_id"]) and len(snap) == len(light):
                return light.merge(snap[SNAPSHOT_COLUMNS], on="tmdb_id", how="inner")
            log.warning("catalog snapshot does not match the database (%d vs %d titles); using the full query",
                        len(snap), len(light))
        except Exception:
            log.exception("catalog snapshot could not be used; using the full query")
    return _catalog_from_sql(db)


def build_snapshot(db: Session, path: Path) -> int:
    """Write the snapshot from the database in `db` (used by scripts/deploy_data.py export). Returns the row count."""
    df = _catalog_from_sql(db)[["tmdb_id", "title", "original_language", "runtime_min", "year", "catalog_part",
                                 "title_type", "genres", "keywords", "has_award"]].copy()
    df["genres"] = df["genres"].map(list)
    df["keywords"] = df["keywords"].map(list)
    df["has_award"] = df["has_award"].fillna(False).astype(bool)
    df.to_parquet(path, index=False)
    return len(df)


def load_engine(db: Session) -> OnlineEngine:
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        rows = pd.read_parquet(MODELS / "content_rows.parquet")
        content = sp.load_npz(MODELS / "content_matrix.npz").tocsr()
        movies = _catalog_frame(db)
        movies = rows.merge(movies, on="tmdb_id", how="inner").sort_values("row")
        if movies.empty:   # a hosted database before the catalog is restored: do not cache an empty engine
            raise HTTPException(503, "The film catalog is not loaded yet")
        content = content[movies["row"].to_numpy()]
        f = np.load(MODELS / "fitted.npz")
        tmdb_to_row = {t: i for i, t in enumerate(movies["tmdb_id"])}
        universe_rows = np.array([tmdb_to_row[t] for t in f["item_tmdb"]])
        series_sim = _series_similarities(movies["tmdb_id"].tolist())
        gemini_sim = _gemini_similarities(movies)
        # Genres, keywords and languages repeat across titles: interning keeps one string object per distinct value
        # instead of one per occurrence (same values, less memory).
        catalog = Catalog(
            movie_ids=movies["id"].to_numpy(), titles=movies["title"].tolist(),
            genres=[[sys.intern(str(x)) for x in g] for g in movies["genres"]],
            keywords=[[sys.intern(str(x)) for x in k] for k in movies["keywords"]],
            language=[sys.intern(x) for x in movies["original_language"].fillna("").tolist()],
            runtime=movies["runtime_min"].astype(float).to_numpy(), year=movies["year"].astype(float).to_numpy(),
            part=movies["catalog_part"].to_numpy(), popularity=movies["popularity"].astype(float).to_numpy(),
            votes=movies["votes"].astype(float).to_numpy(), has_award=movies["has_award"].fillna(False).to_numpy(),
            content=content, universe_rows=universe_rows, recent=(movies["catalog_part"] == "C").to_numpy(),
            kind=movies["title_type"].to_numpy(dtype=object), series_sim=series_sim, gemini_sim=gemini_sim)
        train = sp.load_npz(MODELS / "train_ratings.npz").tocsr()
        uc, ic, sv, al = _settings("user_cf"), _settings("item_cf"), _settings("svd"), _settings("als")
        nb = (f["item_nb_idx"], f["item_nb_vals"])     # read once: every npz access decompresses a new copy
        sources = SourceModels(
            train=train, popularity=f["popularity"], content_sim=np.zeros((1, 1), dtype=np.float32),
            item_neighbors=nb, item_k=ic["neighbors"], item_beta=ic["beta"],
            user_cf={"k": uc["k"], "min_overlap": uc["min_overlap"], "beta": uc["beta"]},
            svd={"mu": float(f["svd_mu"]), "bi": f["svd_bi"], "Q": f["svd_Q"], "reg": sv["reg_all"]},
            als={"Y": f["als_Y"], "alpha": al["alpha"], "reg": al["regularization"]})
        weights = json.loads((MODELS / "hybrid_weights.json").read_text(encoding="utf-8"))
        calibrator = joblib.load(MODELS / "calibration.joblib")
        engine = OnlineEngine(catalog, sources, weights, calibrator, nb, train)
        engine.similar_table = _similar_table(movies["tmdb_id"].tolist())
        engine.availability = AvailabilityMap.load(MODELS / "availability_calibration.json")   # None = old zero rule
        _engine = engine
        del movies, rows, content, f, train
        _release_memory()
        return _engine


def _release_memory() -> None:
    """After the one-off load: collect the temporaries and hand freed heap pages back to the OS (glibc only), so the
    resident size the host counts drops to what the engine really keeps."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass                                        # not glibc (Windows, macOS): nothing to trim


def user_state(db: Session, user_id: int, engine: OnlineEngine) -> UserState:
    row_of = engine.cat.row_of
    q = lambda sql: db.execute(text(sql), {"u": user_id}).all()
    st = UserState()
    st.ratings = {row_of[m]: float(r) for m, r in q("SELECT movie_id, rating FROM ratings WHERE user_id = :u") if m in row_of}
    for m, v in q("SELECT movie_id, value FROM reactions WHERE user_id = :u"):
        if m in row_of:
            (st.likes if v > 0 else st.dislikes).add(row_of[m])
    st.picks = {row_of[m] for (m,) in q("SELECT movie_id FROM onboarding_picks WHERE user_id = :u") if m in row_of}
    st.in_list = {row_of[m] for (m,) in q("SELECT movie_id FROM user_movie_list WHERE user_id = :u") if m in row_of}
    st.watched = {row_of[m] for (m,) in q("SELECT movie_id FROM watched WHERE user_id = :u") if m in row_of}
    events = q("SELECT event_type, movie_id, created_at FROM interactions WHERE user_id = :u ORDER BY created_at")
    st.events = [(e, row_of[m]) for e, m, _ in events if m in row_of]
    st.behavioral_count = len({m for e, m, _ in events if e in BEHAVIORAL_EVENTS and m is not None})
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    views = [row_of[m] for e, m, t in reversed(events) if e in ("detail_view", "quick_view") and m in row_of and t >= cutoff]
    st.recent_views = list(dict.fromkeys(views))
    pref = db.execute(text("SELECT languages, liked_genre_ids, disliked_genre_ids FROM user_preferences WHERE user_id = :u"),
                      {"u": user_id}).first()
    if pref:
        names = dict(db.execute(text("SELECT id, name FROM genres")).all())
        st.languages = list(pref[0] or [])
        st.liked_genres = [names[g] for g in (pref[1] or []) if g in names]
        st.disliked_genres = [names[g] for g in (pref[2] or []) if g in names]
    return st

def match_for(db: Session, user_id: int | None, movie_ids: list[int]) -> dict[int, dict]:
    """Match % (and the hybrid score) for each film the engine can score for this user. Films it cannot
    score (already rated, or no signal) are left out: the page then shows no number for them."""
    if user_id is None or not movie_ids or not artifacts_ready():
        return {}
    try:
        engine = load_engine(db)
    except HTTPException:           # catalog not loaded yet: the lists still show, just without Match %
        return {}
    st = user_state(db, user_id, engine)
    scores = engine.rail_scores(st)
    out = {}
    for mid in movie_ids:
        row = engine.cat.row_of.get(mid)
        if row is not None and np.isfinite(scores[row]):
            out[mid] = {"score": float(scores[row]), "match_pct": engine.match(st.stage, float(scores[row]))}
    return out


TUNING_KEYS = ("adventurous", "hidden", "international", "length")
PHASE_DAYS = 21


def user_tuning(db: Session, user_id: int) -> Tuning:
    raw = db.execute(text("SELECT tuning FROM user_preferences WHERE user_id = :u"), {"u": user_id}).scalar() or {}
    return Tuning(**{k: int(raw[k]) for k in TUNING_KEYS if k in raw})


def recent_positive_rows(db: Session, user_id: int, engine: OnlineEngine) -> list[int]:
    """Films liked, rated 7+, saved or marked watched in the last PHASE_DAYS days, newest first."""
    rows = db.execute(text(f"""SELECT movie_id FROM interactions WHERE user_id = :u AND movie_id IS NOT NULL
        AND created_at >= now() - interval '{PHASE_DAYS} days'
        AND (event_type IN ('like', 'list_add', 'watched') OR (event_type = 'rate' AND value >= 7))
        ORDER BY created_at DESC"""), {"u": user_id}).scalars().all()
    row_of = engine.cat.row_of
    return list(dict.fromkeys(row_of[m] for m in rows if m in row_of))
