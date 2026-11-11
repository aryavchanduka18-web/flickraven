"""Step 10: hybrid blend weights per user stage, Match % calibration, Discovery Mode metrics.

Simulated users match the live definition (spec 6.6): each evaluated validation user gets simulated
onboarding (their 5 earliest films rated >= 8/10, counted as onboarding, not behavior), then
- cold        = onboarding + 0-2 further ratings,
- warming     = onboarding + 3-10 further ratings,
- established = the full training history.
Weights are tuned per stage by grid search on NDCG@10 over validation; then a one-feature logistic
regression per stage maps the blend score to P(rating >= 7) for Match %.
"""
import itertools
import json
import time

import joblib
import numpy as np
import scipy.sparse as sp

from cinematch_engine.blend import blend, candidate_pool, contributions, ranked
from cinematch_engine.calibrate import MatchCalibrator, calibration_table
from cinematch_engine.data.splits import load_split
from cinematch_engine.eval import metrics as M
from cinematch_engine.eval.protocol import evaluate_ranking, relevant_sets
from cinematch_engine.profile import STAGES
from cinematch_engine.rerank import MODES, TOP_N, mmr, scaled_novelty
from cinematch_engine.sources import SOURCES, Profiles
from pipeline.common import ARTIFACTS, PROCESSED, SEED, get_logger, write_json
from pipeline.models_io import MODELS, load_sources, save_models, universe_content_sim

log = get_logger("10_hybrid")
METRICS = ARTIFACTS / "metrics"
K, BATCH, ONBOARD = 10, 500, 5
GRID_STEP = 0.1


def simulate_profiles(data, users: np.ndarray, rng) -> dict[str, Profiles]:
    """Per stage, a Profiles batch for `users` (same order)."""
    ratings, likes = {s: [] for s in STAGES}, {s: [] for s in STAGES}
    ts = data.train_times
    for u in users:
        start, end = data.train.indptr[u], data.train.indptr[u + 1]
        items, vals, times = data.train.indices[start:end], data.train.data[start:end], ts[start:end]
        order = np.lexsort((items, times))                       # oldest first
        items, vals = items[order], vals[order]
        picks = items[vals >= 8][:ONBOARD]
        rest = np.array([i for i in range(len(items)) if items[i] not in set(picks)], dtype=int)
        n_cold, n_warm = rng.integers(0, 3), rng.integers(3, 11)
        for stage, n in (("cold", n_cold), ("warming", n_warm)):
            sel = rest[:n]
            ratings[stage].append((items[sel], vals[sel]))
            likes[stage].append(picks)
        ratings["established"].append((items, vals))
        likes["established"].append(np.array([], dtype=int))

    def to_csr(rows, binary=False):
        indptr, ind, dat = [0], [], []
        for row in rows:
            i, v = (row, np.ones(len(row))) if binary else row
            ind.extend(i.tolist())
            dat.extend(np.asarray(v, dtype=np.float32).tolist())
            indptr.append(len(ind))
        return sp.csr_matrix((np.array(dat, dtype=np.float32), np.array(ind, dtype=np.int64), np.array(indptr)),
                             shape=(len(rows), data.n_items))

    return {s: Profiles(to_csr(ratings[s]), to_csr(likes[s], binary=True), train_rows=users) for s in STAGES}


def pools_for(sources, prof: Profiles, data, users) -> tuple[np.ndarray, np.ndarray]:
    pools, norms = [], []
    for start in range(0, len(users), BATCH):
        sl = slice(start, start + BATCH)
        sub = Profiles(prof.ratings[sl], prof.likes[sl], train_rows=prof.train_rows[sl])
        scores = sources.score_all(sub)
        # Exclude the user's whole training history (known films), as in every other model.
        excluded = [data.train.indices[data.train.indptr[u]:data.train.indptr[u + 1]] for u in users[sl]]
        p, n = candidate_pool(scores, excluded)
        pools.append(p)
        norms.append(n)
    width = max(p.shape[1] for p in pools)
    pool = np.vstack([np.pad(p, ((0, 0), (0, width - p.shape[1])), constant_values=-1) for p in pools])
    norm = np.concatenate([np.pad(n, ((0, 0), (0, 0), (0, width - n.shape[2]))) for n in norms], axis=1)
    return pool, norm


def ndcg_fast(recs: np.ndarray, rel_mask_fn) -> float:
    hits = rel_mask_fn(recs)
    disc = 1.0 / np.log2(np.arange(2, K + 2))
    dcg = (hits * disc).sum(axis=1)
    return float(np.mean(dcg / IDCG))


def weight_grid(step: float = GRID_STEP):
    n = int(round(1 / step))
    for combo in itertools.product(range(n + 1), repeat=len(SOURCES) - 1):
        if sum(combo) <= n:
            yield dict(zip(SOURCES, [c * step for c in combo] + [(n - sum(combo)) * step]))


def main() -> None:
    global IDCG
    t0 = time.time()
    data = load_split(PROCESSED, "val")
    import pandas as pd
    tr = pd.read_parquet(PROCESSED / "splits" / "train.parquet")
    # timestamps aligned with the CSR layout, for "earliest" films
    times = sp.csr_matrix(data.train.shape, dtype=np.float64)
    user_index = pd.Series(np.arange(data.n_users), index=data.user_ids)
    item_index = pd.Series(np.arange(data.n_items), index=data.item_ids)
    tr = tr[tr["ml_movie_id"].isin(item_index.index) & tr["user_id"].isin(user_index.index)]
    times = sp.csr_matrix((tr["timestamp"].to_numpy(np.float64),
                           (user_index.loc[tr["user_id"]].to_numpy(), item_index.loc[tr["ml_movie_id"]].to_numpy())),
                          shape=data.train.shape)
    times.sort_indices()
    data.train.sort_indices()
    data.train_times = times.data

    import sys
    if "--refit" in sys.argv or not (MODELS / "fitted.npz").exists():
        save_models(data)
    content_sim = universe_content_sim(data)
    sources = load_sources(data, content_sim)
    eval_users = np.array(json.loads((METRICS / "eval_users_val.json").read_text(encoding="utf-8"))["users"])
    counts8 = np.asarray((data.train >= 8).sum(axis=1)).ravel()
    users = eval_users[counts8[eval_users] >= ONBOARD]
    rel = relevant_sets(data, users)
    log.info("%d evaluated users with >= %d films rated 8+ (of %d)", len(users), ONBOARD, len(eval_users))

    profiles = simulate_profiles(data, users, np.random.default_rng(SEED))
    novelty = scaled_novelty(data.item_counts(), data.n_users)
    stage_out, calibrator, weights_out = {}, MatchCalibrator(), {}
    for stage in STAGES:
        ts = time.time()
        pool, norm = pools_for(sources, profiles[stage], data, users)
        relmask = np.zeros(pool.shape, dtype=bool)
        for r, u in enumerate(users):
            relmask[r] = np.isin(pool[r], list(rel.get(u, ())))
        n_rel = np.array([len(rel.get(u, ())) for u in users])
        IDCG = np.array([np.sum(1.0 / np.log2(np.arange(2, min(n, K) + 2))) for n in n_rel])

        def mask_fn(recs, _pool=pool, _rel=relmask):
            # recs are pool positions here
            return np.take_along_axis(_rel, recs, axis=1)

        best_w, best = None, -1.0
        for w in weight_grid():
            final = blend(norm, w)
            f = np.where(pool >= 0, final, -np.inf)
            pos = np.argpartition(-f, K, axis=1)[:, :K]
            pos = np.take_along_axis(pos, np.argsort(-np.take_along_axis(f, pos, axis=1), axis=1), axis=1)
            score = ndcg_fast(pos, mask_fn)
            if score > best:
                best, best_w = score, w
        weights_out[stage] = {k: round(v, 2) for k, v in best_w.items()}
        final = blend(norm, best_w)
        recs = ranked(pool, final, K)

        # Calibration: blend score -> P(rating >= 7), fitted on pool films the user rated in validation.
        ev = data.eval_df[data.eval_df["u"].isin(users)]
        val_rating = {(u, i): r for u, i, r in ev[["u", "i", "rating"]].itertuples(index=False)}
        xs, ys = [], []
        for r, u in enumerate(users):
            for j, item in enumerate(pool[r]):
                if item >= 0 and (u, item) in val_rating:
                    xs.append(final[r, j])
                    ys.append(val_rating[(u, item)] >= M.RELEVANT)
        xs, ys = np.array(xs), np.array(ys)
        calibrator.fit(stage, xs, ys)
        prob = calibrator.probability(stage, xs)
        table = calibration_table(prob, ys)
        ece = float(sum(abs(t["predicted"] - t["observed"]) * t["n"] for t in table) / len(xs))
        stage_out[stage] = {"weights": weights_out[stage], "ndcg_at_10_tuning": best,
                            "pool_width_mean": float((pool >= 0).sum(axis=1).mean()),
                            "calibration": {"pairs": int(len(xs)), "base_rate": float(ys.mean()),
                                            "ece": ece, "passes": bool(ece < 0.03), "bins": table,
                                            "match_pct_range": [int(calibrator.match_pct(stage, [xs.min()])[0]),
                                                                int(calibrator.match_pct(stage, [xs.max()])[0])]},
                            "ranking_no_rerank": evaluate_ranking(recs, users, data, content_sim, K)}
        if stage == "established":
            for mode, cfg in MODES.items():
                mm = []
                for r in range(len(users)):
                    order = np.argsort(-np.where(pool[r] >= 0, final[r], -np.inf))[:TOP_N]
                    order = order[pool[r][order] >= 0]
                    mm.append(mmr(pool[r][order], final[r][order], content_sim, novelty, K,
                                  cfg["lambda"], cfg["beta"]))
                stage_out[stage][f"ranking_{mode}"] = evaluate_ranking(np.vstack(mm), users, data, content_sim, K)
        log.info("%s: weights %s, NDCG@10 %.4f, calibration ECE %.4f (%.0fs)", stage, weights_out[stage], best, ece,
                 time.time() - ts)

    write_json(MODELS / "hybrid_weights.json", weights_out)
    joblib.dump(calibrator, MODELS / "calibration.joblib")
    write_json(MODELS / "calibration.json", calibrator.params())
    write_json(METRICS / "validation_hybrid.json", {"split": "val", "users": int(len(users)), "k": K,
                                                    "grid_step": GRID_STEP, "stages": stage_out,
                                                    "seconds": round(time.time() - t0, 1)})
    log.info("done in %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()