"""New-user ranking experiments: what does each change do to NDCG@10 for people with 0-6 signals?

    python -m pipeline.cold_eval --users 700 --only baseline

Held-out users are the same as pipeline/availability_calibration.py (their later ratings of 7+, on MovieLens films and
the 500 hold-out films, are the targets). Three regimes:
    cold2     2 random ratings
    picks5    no ratings, 5 films rated 8+ used as onboarding picks (what the onboarding screen would give)
    warming6  6 random ratings
Result (2026-11-10, 700 users, repeated on 1000 fresh users): no change to the blend was worth shipping. Plain popularity beats
the hybrid for all three regimes (cold2 0.072 vs 0.043); more popularity weight raises NDCG but collapses variety (1000 cold
users got 18 distinct films at 80% popularity, 221 today); the title-similarity table as a taste source changes NDCG by about
+/-0.002; a popular-first-then-personalise design is worse than popularity alone. See docs/report/report.md section 5.7.

Each variant is a function (engine, state, scores) -> ranked catalog rows; every user is run through every variant, so
differences are paired (same users, same targets) and come with a standard error. Series/anime, session signals and
onboarding genres/languages cannot be measured here: MovieLens has no such data.
"""
import argparse
import json
import time

import numpy as np
import scipy.sparse as sp

from cinematch_engine import rerank
from cinematch_engine.online import UserState
from pipeline.availability_calibration import build_engine, sample
from pipeline.common import ARTIFACTS, get_logger, write_json

log = get_logger("cold_eval")
K = 10
DISC = 1 / np.log2(np.arange(2, K + 2))
REGIMES = {"cold2": (2, 0), "picks5": (0, 5), "warming6": (6, 0)}      # (random ratings, onboarding picks)
VARIANTS: dict = {}
ROWS_INFO: dict = {}


def variant(name):
    def wrap(fn):
        VARIANTS[name] = fn
        return fn
    return wrap


def make_state(engine, ml2row, r, n_ratings, n_picks, seed=1):
    st = UserState()
    r = r.sample(frac=1, random_state=seed)
    if n_picks:
        liked = r[r.rating >= 8].head(n_picks)
        st.picks = {ml2row[int(a)] for a in liked.ml_movie_id if int(a) in ml2row}
        r = r.drop(liked.index)
    if n_ratings:
        sub = r.head(n_ratings)
        st.ratings = {ml2row[int(a)]: float(b) for a, b in zip(sub.ml_movie_id, sub.rating) if int(a) in ml2row}
        st.behavioral_count = len(st.ratings)
    return st


def top_by(engine, st, v):
    v = np.array(v, dtype=np.float64)
    v[~np.isfinite(v)] = -np.inf
    v[engine.excluded(st)] = -np.inf
    return np.argsort(-v, kind="stable")[:K]


def hybrid(engine, st, scores, weights=None):
    saved = engine.weights[st.stage]
    if weights is not None:
        engine.weights[st.stage] = weights
    saved_modes = rerank.MODES["familiar"]["tail_share"]
    rerank.MODES["familiar"]["tail_share"] = 0.0
    try:
        return np.array([p["row"] for p in engine.top_picks(st, "familiar", k=K, scores=scores)])
    finally:
        engine.weights[st.stage] = saved
        rerank.MODES["familiar"]["tail_share"] = saved_modes


@variant("baseline")
def _baseline(engine, st, scores):
    return hybrid(engine, st, scores)


@variant("popularity_only")
def _pop(engine, st, scores):
    return top_by(engine, st, scores["popularity"])


@variant("content_only")
def _content(engine, st, scores):
    return top_by(engine, st, scores["content"])


@variant("als_only")
def _als(engine, st, scores):
    return top_by(engine, st, scores["als"])


@variant("user_cf_only")
def _ucf(engine, st, scores):
    return top_by(engine, st, scores["user_cf"])


@variant("item_cf_only")
def _icf(engine, st, scores):
    return top_by(engine, st, scores["item_cf"])


GRID = {
    "pop6_als2_ucf2": {"popularity": .6, "als": .2, "user_cf": .2},
    "pop6_even": {"popularity": .6, "als": .1, "user_cf": .1, "content": .1, "item_cf": .1},
    "pop8_ucf1_als1": {"popularity": .8, "user_cf": .1, "als": .1},
    "pop5_ucf25_icf25": {"popularity": .5, "user_cf": .25, "item_cf": .25},
    "pop4_ucf3_icf3": {"popularity": .4, "user_cf": .3, "item_cf": .3},
    "pop3_ucf35_icf35": {"popularity": .3, "user_cf": .35, "item_cf": .35},
    "pop5_ucf5": {"popularity": .5, "user_cf": .5},
    "pop7_ucf3": {"popularity": .7, "user_cf": .3},
}


def _grid(w):
    def fn(engine, st, scores):
        return hybrid(engine, st, scores, w)
    return fn


def _rail(w):
    def fn(engine, st, scores):
        saved = engine.weights[st.stage]
        if w is not None:
            engine.weights[st.stage] = w
        try:
            return top_by(engine, st, engine.rail_scores(st, scores))
        finally:
            engine.weights[st.stage] = saved
    return fn


for _n, _w in GRID.items():
    VARIANTS["pool_" + _n] = _grid(_w)
    VARIANTS["rail_" + _n] = _rail(_w)
VARIANTS["rail_baseline"] = _rail(None)


_SIM = {}


def title_similarity(engine) -> sp.csr_matrix:
    """The More Like This neighbour table as a sparse catalog x catalog matrix (row = title, columns = its 40 neighbours)."""
    if "S" not in _SIM:
        z = np.load(ARTIFACTS / "models" / "similar_titles.npz")
        row_of = engine.cat.row_of
        src = np.array([row_of.get(int(t), -1) for t in z["tmdb_ids"]])
        nb, sc = z["rows"], z["scores"].astype(np.float32)
        r, c = np.nonzero((nb >= 0) & (src[:, None] >= 0))
        cols = src[nb[r, c]]
        keep = cols >= 0
        _SIM["S"] = sp.csr_matrix((sc[r, c][keep], (src[r[keep]], cols[keep])), shape=(engine.cat.n, engine.cat.n))
    return _SIM["S"]


def sim_scores(engine, st) -> np.ndarray:
    S = title_similarity(engine)
    w = {r: (v - 6) / 4 for r, v in st.ratings.items() if v >= 7}
    w.update({r: 1.0 for r in st.likes | st.picks})
    if not w:
        return np.full(engine.cat.n, -np.inf)
    v = sp.csr_matrix((list(w.values()), ([0] * len(w), list(w))), shape=(1, engine.cat.n))
    out = np.asarray((v @ S).todense()).ravel()
    return out


@variant("sim_only")
def _sim_only(engine, st, scores):
    return top_by(engine, st, sim_scores(engine, st))


def _with_sim(lam):
    def fn(engine, st, scores):
        sim = sim_scores(engine, st)
        pct = lambda v, ok: (np.argsort(np.argsort(v[ok])) + 1) / max(ok.sum(), 1)
        c = scores["content"].copy()
        out = dict(scores)
        mix = np.full(engine.cat.n, -np.inf, dtype=np.float32)
        okc = np.isfinite(c)
        base = np.zeros(engine.cat.n, np.float32)
        if okc.any():
            base[okc] = pct(c, okc)
        ok = sim > 0
        add = np.zeros(engine.cat.n, np.float32)
        if ok.any():
            add[ok] = lam * pct(sim, ok)
        mix = np.where(okc | ok, base + add, -np.inf).astype(np.float32)
        out["content"] = mix
        return hybrid(engine, st, out)
    return fn


VARIANTS["content_plus_sim_05"] = _with_sim(0.5)
VARIANTS["content_plus_sim_10"] = _with_sim(1.0)


def _popular_first(n_cand, w):
    """Candidates = the n_cand most popular unseen films; inside them every source becomes a percentile among the
    candidates (a source that cannot score a film gives it the middle, 0.5), then the stage weights blend them."""
    def fn(engine, st, scores):
        pop = np.array(scores["popularity"], dtype=np.float64)
        pop[engine.excluded(st)] = -np.inf
        cand = np.argsort(-pop, kind="stable")[:n_cand]
        total = np.zeros(len(cand))
        wsum = 0.0
        for name, weight in w.items():
            v = np.array(scores[name], dtype=np.float64)[cand]
            ok = np.isfinite(v)
            if name != "popularity" and (not ok.any() or np.ptp(v[ok]) < 1e-9):
                continue                         # the source knows nothing about this user: leave it out
            pct = np.full(len(cand), 0.5)
            pct[ok] = (np.argsort(np.argsort(v[ok])) + 1) / ok.sum()
            total += weight * pct
            wsum += weight
        return cand[np.argsort(-total, kind="stable")[:K]]
    return fn


for _n in (100, 300, 1000):
    for _tag, _w in {"p6": {"popularity": .6, "user_cf": .2, "als": .2}, "p5": {"popularity": .5, "user_cf": .25, "als": .25},
                     "p7": {"popularity": .7, "user_cf": .15, "als": .15}, "p5i": {"popularity": .5, "user_cf": .2, "als": .15, "item_cf": .15}}.items():
        VARIANTS[f"pf{_n}_{_tag}"] = _popular_first(_n, _w)


@variant("no_availability")
def _no_avail(engine, st, scores):
    saved, engine.availability = engine.availability, None
    try:
        return hybrid(engine, st, scores)
    finally:
        engine.availability = saved


def run(engine, ml2row, users, groups, regime, names, seed=1):
    n_ratings, n_picks = REGIMES[regime]
    rows = {n: [] for n in names}
    seen = {n: [] for n in names}
    t = time.time()
    for u in users:
        st = make_state(engine, ml2row, groups["train"].get_group(u), n_ratings, n_picks, seed)
        if len(st.ratings) + len(st.picks) < 2:
            continue
        lab = set()
        for part in ("test", "new"):
            g = groups[part].get_group(u)
            lab |= {ml2row[int(a)] for a, b in zip(g.ml_movie_id, g.rating) if b >= 7 and int(a) in ml2row}
        lab -= set(st.ratings) | st.picks
        if not lab:
            continue
        scores = engine.scores(st)
        for n in names:
            rec = np.asarray(VARIANTS[n](engine, st, scores))[:K]
            rel = np.array([x in lab for x in rec], float)
            rows[n].append((rel * DISC[:len(rec)]).sum() / DISC[:min(len(lab), K)].sum())
            seen[n].append(rec)
    log.info("%s: %d users in %.0fs", regime, len(rows[names[0]]), time.time() - t)
    for n, recs in seen.items():
        flat = np.concatenate(recs)
        ROWS_INFO[n] = {"distinct_films": int(len(np.unique(flat))), "mean_fame_percentile": round(float(engine.cat.fame_pct[flat].mean()), 1)}
    return {n: np.array(v) for n, v in rows.items()}


def summarise(res, base="baseline") -> dict:
    out = {}
    for n, v in res.items():
        d = v - res[base]
        out[n] = {"ndcg@10": round(float(v.mean()), 4), "vs_baseline": round(float(d.mean()), 4),
                  "se": round(float(d.std(ddof=1) / np.sqrt(len(d))), 4) if len(d) > 1 and n != base else 0.0, "users": len(v),
                  **ROWS_INFO.get(n, {})}
    return out


def production_like(engine) -> None:
    """Make the harness engine behave like the served one: availability-aware scoring on (the artifact the API loads), and
    the stored popularity score. Universe films use the trained Bayesian popularity (artifacts/models/fitted.npz). The
    TMDB-based score of the other films lives in the database and is not available here, so each of them gets the
    universe score of the film with the same fame rank (a proxy; the offline targets are MovieLens films anyway)."""
    from cinematch_engine.availability import AvailabilityMap
    f = np.load(ARTIFACTS / "models" / "fitted.npz")
    cat = engine.cat
    uni = cat.universe_rows
    pop = np.zeros(cat.n)
    pop[uni] = f["popularity"]
    rest = np.setdiff1d(np.arange(cat.n), uni)
    order = np.sort(cat.votes[uni])
    q = np.searchsorted(order, cat.votes[rest]) / len(order)
    pop[rest] = np.quantile(f["popularity"], np.clip(q, 0, 1))
    cat.popularity = pop.astype(np.float32)
    engine.availability = AvailabilityMap.load(ARTIFACTS / "models" / "availability_calibration.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=700)
    ap.add_argument("--only", default="", help="comma list of variants (baseline is always included)")
    ap.add_argument("--regimes", default="cold2,picks5,warming6")
    ap.add_argument("--out", default="cold_start.json")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    engine, movies, f = build_engine()
    production_like(engine)
    ml2row, _, users, groups = sample(engine, movies, f, a.users, a.seed)
    names = ["baseline"] + [n for n in (a.only.split(",") if a.only else VARIANTS) if n and n != "baseline"]
    report = {}
    for regime in a.regimes.split(","):
        report[regime] = summarise(run(engine, ml2row, users, groups, regime, names), "baseline")
        print(regime, json.dumps(report[regime], indent=0))
    write_json(ARTIFACTS / "metrics" / a.out, report)


if __name__ == "__main__":
    main()
