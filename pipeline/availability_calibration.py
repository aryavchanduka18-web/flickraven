"""Evaluate and calibrate how films without collaborative factors are ranked ("unavailable" is not "low").

    python -m pipeline.availability_calibration            # evaluate on held-out users, write the curves
    python -m pipeline.availability_calibration --users 600

The 500 hold-out films (spec section 4: removed from train, validation and test, ratings kept in
splits/newmovie_test.parquet) are exactly films the collaborative models never saw. Candidates for each user are
the MovieLens films plus these 500; targets are the user's later ratings of 7+ on either kind. Four rankings:

    zero     the old rule: an unavailable source adds 0 to the blend
    renorm   weighted average of the sources that can score the film (no calibration)
    mapped   renorm, then mapped onto the MovieLens films' scale by matching P(rating >= 7)   <- served
    (iso_p   rank by calibrated probability only: reported for reference)

Users are split in halves by order: the first half fits the curves, the second half is only reported. The curves
written to artifacts/models/availability_calibration.json are then refitted on all users. cold = 2 ratings,
warming = 6, established = the user's whole training history. Popularity is a vote-count proxy for every film
(production uses the stored popularity score), which matters little except for cold users.

Limits: the hold-out films are well-known films (they had to pass the catalog's rating-count rule), so the curves
say how a well-known film without MovieLens factors does; they cannot say how an obscure one does.
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.isotonic import IsotonicRegression

from cinematch_engine.availability import AvailabilityMap, isotonic_arrays, renormalized
from cinematch_engine.online import Catalog, OnlineEngine, UserState
from cinematch_engine.sources import SOURCES, SourceModels
from pipeline.common import ARTIFACTS, PROCESSED, get_logger, write_json

log = get_logger("availability")
MODELS = ARTIFACTS / "models"
SPLITS = PROCESSED / "splits"
REGIMES = {"cold": 2, "warming": 6, "established": None}      # ratings used for the user's profile (None = all)


def build_engine():
    """OnlineEngine over the whole catalog, from the saved artifacts (same wiring as api/app/services/recommender.py)."""
    import joblib
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
    rows = pd.read_parquet(MODELS / "content_rows.parquet")
    movies = rows.merge(movies, on="tmdb_id").sort_values("row").reset_index(drop=True)
    content = sp.load_npz(MODELS / "content_matrix.npz").tocsr()[movies["row"].to_numpy()]
    f = np.load(MODELS / "fitted.npz")
    row_of = {t: i for i, t in enumerate(movies["tmdb_id"])}
    universe = np.array([row_of[t] for t in f["item_tmdb"]])
    votes = movies["tmdb_vote_count"].fillna(0).to_numpy(dtype=float)
    cat = Catalog(
        movie_ids=movies["tmdb_id"].to_numpy(), titles=movies["title"].tolist(), genres=[list(g) for g in movies["genres"]],
        keywords=[list(k) for k in movies["keywords"]], language=movies["original_language"].fillna("").tolist(),
        runtime=movies["runtime_min"].astype(float).to_numpy(), year=movies["year"].astype(float).to_numpy(),
        part=movies["catalog_part"].to_numpy(), popularity=np.log1p(votes) / 2, votes=votes,
        has_award=np.zeros(len(movies), bool), content=content, universe_rows=universe,
        recent=(movies["catalog_part"] == "C").to_numpy(), kind=movies["title_type"].to_numpy(dtype=object))
    s = lambda n: json.loads((MODELS / f"{n}.json").read_text())["settings"]
    uc, ic, sv, al = s("user_cf"), s("item_cf"), s("svd"), s("als")
    train = sp.load_npz(MODELS / "train_ratings.npz").tocsr()
    src = SourceModels(
        train=train, popularity=f["popularity"], content_sim=np.zeros((1, 1), np.float32),
        item_neighbors=(f["item_nb_idx"], f["item_nb_vals"]), item_k=ic["neighbors"], item_beta=ic["beta"],
        user_cf={"k": uc["k"], "min_overlap": uc["min_overlap"], "beta": uc["beta"]},
        svd={"mu": float(f["svd_mu"]), "bi": f["svd_bi"], "Q": f["svd_Q"], "reg": sv["reg_all"]},
        als={"Y": f["als_Y"], "alpha": al["alpha"], "reg": al["regularization"]})
    engine = OnlineEngine(cat, src, json.loads((MODELS / "hybrid_weights.json").read_text()),
                          joblib.load(MODELS / "calibration.joblib"), (f["item_nb_idx"], f["item_nb_vals"]), train)
    return engine, movies, f


def percentiles(scores: dict) -> dict:
    out = {}
    for s in SOURCES:
        v = scores[s]
        ok = np.isfinite(v)
        p = np.full(len(v), np.nan, np.float32)
        if ok.any():
            p[ok] = (np.argsort(np.argsort(v[ok])) + 1) / ok.sum()
        out[s] = p
    return out


def blend_zero(p: dict, w: dict, rows: np.ndarray) -> np.ndarray:
    """The old rule: unavailable adds 0."""
    return sum(w.get(s, 0) * np.nan_to_num(p[s][rows], nan=0.0) for s in SOURCES).astype(np.float32)


def sample(engine, movies, f, users: int, seed: int = 11):
    ml2row = {int(x): i for i, x in enumerate(movies["ml_movie_id"]) if pd.notna(x)}
    holdout = pd.read_parquet(SPLITS / "holdout_films.parquet")["ml_movie_id"]
    hold_rows = np.array(sorted(ml2row[int(x)] for x in holdout if int(x) in ml2row))
    nm, te, tr = (pd.read_parquet(SPLITS / f"{n}.parquet") for n in ("newmovie_test", "test", "train"))
    ok = sorted(set(nm[nm.rating >= 7].user_id) & set(te[te.rating >= 7].user_id) & set(f["user_ids"].tolist()))
    chosen = np.random.default_rng(seed).choice(ok, size=min(users, len(ok)), replace=False)
    groups = {n: d[d.user_id.isin(chosen)].groupby("user_id") for n, d in (("train", tr), ("test", te), ("new", nm))}
    return ml2row, hold_rows, chosen, groups


def run_regime(engine, ml2row, hold_rows, users, groups, n_ratings, seed: int = 1):
    cand = np.union1d(engine.cat.universe_rows, hold_rows)
    is_new = np.isin(cand, hold_rows)
    recs = []
    for u in users:
        r = groups["train"].get_group(u)
        if n_ratings:
            r = r.sample(min(n_ratings, len(r)), random_state=seed)
        st = UserState()
        st.ratings = {ml2row[int(a)]: float(b) for a, b in zip(r.ml_movie_id, r.rating) if int(a) in ml2row}
        st.behavioral_count = len(st.ratings)
        if len(st.ratings) < 2:
            continue
        p = percentiles(engine.scores(st))
        w = engine.weights[st.stage]
        keep = ~np.isin(cand, list(st.ratings))
        rows, new = cand[keep], is_new[keep]
        labeled = {}
        for part in ("test", "new"):
            g = groups[part].get_group(u)
            labeled.update({ml2row[int(a)]: bool(b >= 7) for a, b in zip(g.ml_movie_id, g.rating) if int(a) in ml2row})
        recs.append({"rows": rows, "new": new, "labeled": labeled, "stage": st.stage,
                     "zero": blend_zero(p, w, rows), "renorm": renormalized(p, w, rows)})
    return recs


def fit(recs, key, flag):
    xs, ys = [], []
    for r in recs:
        for x, row, n in zip(r[key], r["rows"], r["new"]):
            if n == flag and row in r["labeled"]:
                xs.append(x)
                ys.append(r["labeled"][row])
    return IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(xs, ys)


def metrics(recs, key, hold_set, k: int = 10) -> dict:
    disc = 1 / np.log2(np.arange(2, k + 2))
    nd, nd_new, rec50, top10 = [], [], [], []
    for r in recs:
        targets = {row for row, y in r["labeled"].items() if y}
        new_t = targets & hold_set
        if not targets:
            continue
        top = r["rows"][np.lexsort((r["rows"], -np.round(r[key], 6)))]
        rel = np.array([x in targets for x in top[:k]], float)
        nd.append((rel * disc).sum() / disc[:min(len(targets), k)].sum())
        top10.append(np.mean([x in hold_set for x in top[:k]]))
        if new_t:
            rn = np.array([x in new_t for x in top[:k]], float)
            nd_new.append((rn * disc).sum() / disc[:min(len(new_t), k)].sum())
            rec50.append(len(set(top[:50].tolist()) & new_t) / min(len(new_t), 50))
    return {"ndcg@10": round(float(np.mean(nd)), 4), "ndcg@10_on_unavailable_targets": round(float(np.mean(nd_new)), 4),
            "recall@50_on_unavailable_targets": round(float(np.mean(rec50)), 4),
            "share_of_top10_without_factors": round(float(np.mean(top10)), 3), "users": len(nd)}


def apply_map(recs, ik, inew):
    levels, first = np.unique(ik.y_thresholds_, return_index=True)
    inverse = lambda p: np.interp(p, levels, np.asarray(ik.X_thresholds_)[first])
    for r in recs:
        m = r["zero"].copy()
        m[r["new"]] = inverse(inew.predict(r["renorm"][r["new"]]))
        r["mapped"] = m
        r["iso_p"] = np.where(r["new"], inew.predict(r["renorm"]), ik.predict(r["zero"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=600)
    a = ap.parse_args()
    engine, movies, f = build_engine()
    ml2row, hold_rows, users, groups = sample(engine, movies, f, a.users)
    hold_set = set(hold_rows.tolist())
    report, curves = {"users_sampled": int(len(users)), "holdout_films": len(hold_rows)}, {}
    for stage, n in REGIMES.items():
        t = time.time()
        recs = run_regime(engine, ml2row, hold_rows, users, groups, n)
        half = len(recs) // 2
        fit_half, test_half = recs[:half], recs[half:]
        apply_map(test_half, fit(fit_half, "zero", False), fit(fit_half, "renorm", True))
        report[stage] = {k: metrics(test_half, k, hold_set) for k in ("zero", "renorm", "mapped", "iso_p")}
        ik, inew = fit(recs, "zero", False), fit(recs, "renorm", True)         # final curves use every user
        curves[stage] = {"known": isotonic_arrays(ik), "new": isotonic_arrays(inew)}
        log.info("%s done in %.0fs: %s", stage, time.time() - t, json.dumps(report[stage]["mapped"]))
    write_json(MODELS / "availability_calibration.json", {"stages": curves, "note": __doc__.split("\n")[0]})
    write_json(ARTIFACTS / "metrics" / "availability.json", report)
    AvailabilityMap.load(MODELS / "availability_calibration.json")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
