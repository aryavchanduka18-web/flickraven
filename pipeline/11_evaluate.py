"""Step 11: the final evaluation and every experiment in spec section 12.4.

Run once, after all tuning (Phases 3-5). Settings are read from artifacts/models; nothing is tuned here.
1. Model comparison on the TEST split (models retrained on train + validation).
2. Cold-start users: k = 0, 2, 5, 10, 20 behavioral ratings, with and without simulated onboarding.
3. New movies: hit rate@50 for the held-out films (no training ratings at all).
4. Diversity trade-off: lambda from 0.5 to 1.0 in steps of 0.05 (NDCG@10 vs intra-list diversity).
5. Calibration check: predicted Match % vs observed share of liked films, per stage.
6. Global-cutoff check: the model comparison rerun on the global time split.
All results go to artifacts/metrics/*.json (the Research Lab reads only these files).
"""
import json
import time

import joblib
import numpy as np
import pandas as pd
import scipy.sparse as sp

from cinematch_engine.blend import blend, candidate_pool, ranked
from cinematch_engine.calibrate import calibration_table
from cinematch_engine.data.splits import load_split
from cinematch_engine.eval import metrics as M
from cinematch_engine.eval.protocol import evaluate_ranking, relevant_sets, sample_eval_users, top_k
from cinematch_engine.profile import stage_of
from cinematch_engine.rerank import MODES, TOP_N, mmr, scaled_novelty
from cinematch_engine.sources import SOURCES, Profiles
from pipeline.common import ARTIFACTS, PROCESSED, SEED, get_logger, write_json
from pipeline.models_io import MODELS, content_sim_for, fit_sources

log = get_logger("11_evaluate")
METRICS = ARTIFACTS / "metrics"
K, BATCH, ONBOARD = 10, 500, 5
N_TEST_USERS = 5000


def weights() -> dict:
    return json.loads((MODELS / "hybrid_weights.json").read_text(encoding="utf-8"))


def known(data, u) -> np.ndarray:
    return data.train.indices[data.train.indptr[u]:data.train.indptr[u + 1]]


def full_profiles(data, users) -> Profiles:
    return Profiles(data.train[users], sp.csr_matrix((len(users), data.n_items), dtype=np.float32), train_rows=users)


def rank_everything(sources, prof: Profiles, data, users, stage_of_row, w_all, k=K, modes=("balanced",),
                    content_sim=None, novelty=None, keep_final=False):
    """Top-k lists for every source and for the hybrid (blend, then MMR per mode)."""
    out = {s: [] for s in SOURCES}
    out.update({f"hybrid_{m}": [] for m in modes})
    out["hybrid_blend"] = []
    finals = []
    for start in range(0, len(users), BATCH):
        sl = slice(start, start + BATCH)
        ub = users[sl]
        sub = Profiles(prof.ratings[sl], prof.likes[sl], train_rows=ub)
        scores = sources.score_all(sub)
        excluded = [known(data, u) for u in ub]
        for s in SOURCES:
            out[s].append(top_k(scores[s], excluded, k))
        pool, norm = candidate_pool(scores, excluded)
        for r in range(len(ub)):
            w = w_all[stage_of_row[start + r]]
            final = blend(norm[:, r:r + 1, :], w)[0]
            valid = pool[r] >= 0
            order = np.argsort(-np.where(valid, final, -np.inf))
            order = order[valid[order]]
            out["hybrid_blend"].append(pool[r][order[:k]][None, :])
            if keep_final:
                finals.append((pool[r][order], final[order]))
            top = order[:TOP_N]
            for m in modes:
                cfg = MODES[m]
                out[f"hybrid_{m}"].append(mmr(pool[r][top], final[top], content_sim, novelty, k,
                                              cfg["lambda"], cfg["beta"])[None, :])
    res = {name: np.vstack(v) for name, v in out.items()}
    return (res, finals) if keep_final else res


# ----------------------------------------------------------------------------- experiments
def model_comparison(train_parts, split, label) -> dict:
    t0 = time.time()
    data = load_split(PROCESSED, split, train_parts=train_parts)
    users = sample_eval_users(data, N_TEST_USERS, SEED)
    content_sim = content_sim_for(data)
    sources = fit_sources(data, content_sim)
    novelty = scaled_novelty(data.item_counts(), data.n_users)
    w_all = weights()
    stages = ["established"] * len(users)
    recs = rank_everything(sources, full_profiles(data, users), data, users, stages, w_all,
                           modes=tuple(MODES), content_sim=content_sim, novelty=novelty)
    result = {name: evaluate_ranking(r, users, data, content_sim, K) for name, r in recs.items()}

    # MAE / RMSE for the rating models on the evaluated users' held-out ratings.
    from cinematch_engine.models.bias import BiasBaseline
    from pipeline.models_io import settings
    ev = data.eval_df[data.eval_df["u"].isin(users)]
    u, i, r = ev["u"].to_numpy(), ev["i"].to_numpy(), ev["rating"].to_numpy()
    from cinematch_engine.eval.protocol import evaluate_ratings
    bias = BiasBaseline(**settings("bias")).fit(data.train)
    svd_pred = np.clip(sources.svd["mu"] + bias_free_svd(sources, data, u, i), 1, 10)
    ratings = {"bias": evaluate_ratings(bias.predict(u, i), r, u), "svd": evaluate_ratings(svd_pred, r, u)}
    log.info("%s comparison done in %.0fs", label, time.time() - t0)
    return {"split": split, "train": list(train_parts), "evaluated_users": int(len(users)),
            "universe_films": int(data.n_items), "ranking": result, "ratings": ratings}


def bias_free_svd(sources, data, u, i):
    """SVD predictions for (u, i) pairs via fold-in from each user's training ratings."""
    out = np.empty(len(u), dtype=np.float32)
    s = sources.svd
    for user in np.unique(u):
        row = data.train[user]
        X = np.hstack([s["Q"][row.indices], np.ones((row.nnz, 1), dtype=np.float32)]).astype(np.float64)
        y = row.data - s["mu"] - s["bi"][row.indices]
        sol = np.linalg.solve(X.T @ X + s["reg"] * row.nnz * np.eye(X.shape[1]), X.T @ y)
        sel = u == user
        out[sel] = s["bi"][i[sel]] + sol[-1] + s["Q"][i[sel]] @ sol[:-1]
    return out


def cold_start(data, sources, content_sim, novelty, users, times) -> dict:
    """NDCG@10 against k known behavioral ratings, with and without simulated onboarding."""
    w_all = weights()
    rel = relevant_sets(data, users)
    out = {}
    for k in (0, 2, 5, 10, 20):
        for onboarding in (False, True):
            r_rows, l_rows = [], []
            for u in users:
                start, end = data.train.indptr[u], data.train.indptr[u + 1]
                items, vals, ts = data.train.indices[start:end], data.train.data[start:end], times[start:end]
                order = np.lexsort((items, ts))
                items, vals = items[order], vals[order]
                if onboarding:
                    picks = items[vals >= 8][:ONBOARD]
                    rest = np.array([j for j in range(len(items)) if items[j] not in set(picks)], dtype=int)[:k]
                else:
                    picks, rest = np.array([], dtype=int), np.arange(min(k, len(items)))
                r_rows.append((items[rest], vals[rest]))
                l_rows.append(picks)
            prof = Profiles(_csr(r_rows, data.n_items), _csr([(p, np.ones(len(p))) for p in l_rows], data.n_items),
                            train_rows=users)
            stages = [stage_of(k)] * len(users)
            recs = rank_everything(sources, prof, data, users, stages, w_all, content_sim=content_sim, novelty=novelty)
            key = f"k{k}_{'with' if onboarding else 'without'}_onboarding"
            out[key] = {name: float(np.mean([M.ndcg_at_k(l.tolist(), rel.get(u, set()), K) for u, l in zip(users, rl)]))
                        for name, rl in recs.items()}
            log.info("cold start %s: hybrid %.4f, popularity %.4f, content %.4f", key,
                     out[key]["hybrid_balanced"], out[key]["popularity"], out[key]["content"])
    return {"users": int(len(users)), "k_values": [0, 2, 5, 10, 20], "results": out,
            "note": "k = behavioral ratings known; onboarding = 5 earliest films rated >= 8 as picks (not behavior)"}


def _csr(rows, n_items):
    indptr, ind, dat = [0], [], []
    for items, vals in rows:
        ind.extend(np.asarray(items).tolist())
        dat.extend(np.asarray(vals, dtype=np.float32).tolist())
        indptr.append(len(ind))
    return sp.csr_matrix((np.array(dat, dtype=np.float32), np.array(ind, dtype=np.int64), np.array(indptr)),
                         shape=(len(rows), n_items))


def new_movies(n_users: int = 2000) -> dict:
    """Hit rate@50 for held-out films the user rated >= 7: they have no training ratings at all."""
    data = load_split(PROCESSED, "test", train_parts=("train", "val"), include_holdout_items=True)
    holdout = set(pd.read_parquet(PROCESSED / "splits" / "holdout_films.parquet")["ml_movie_id"])
    nm = pd.read_parquet(PROCESSED / "splits" / "newmovie_test.parquet")
    nm = nm[nm["rating"] >= 7]
    user_index = pd.Series(np.arange(data.n_users), index=data.user_ids)
    item_index = pd.Series(np.arange(data.n_items), index=data.item_ids)
    nm = nm[nm["user_id"].isin(user_index.index)]
    liked = {}
    for uid, g in nm.groupby("user_id"):
        liked[int(user_index[uid])] = set(item_index.loc[g["ml_movie_id"]].tolist())
    users = np.sort(np.random.default_rng(SEED).choice(np.array(sorted(liked)), size=min(n_users, len(liked)), replace=False))
    content_sim = content_sim_for(data)
    sources = fit_sources(data, content_sim)
    novelty = scaled_novelty(data.item_counts(), data.n_users)
    recs = rank_everything(sources, full_profiles(data, users), data, users, ["established"] * len(users), weights(),
                           k=50, content_sim=content_sim, novelty=novelty)
    hold_idx = {int(item_index[m]) for m in holdout if m in item_index.index}
    out = {}
    for name, rl in recs.items():
        hits = sum(len(liked[u] & set(l.tolist())) for u, l in zip(users, rl))
        pairs = sum(len(liked[u]) for u in users)
        share = float(np.mean([np.isin(l, list(hold_idx)).mean() for l in rl]))
        out[name] = {"hit_rate_at_50": hits / pairs, "share_of_top50_that_are_new_films": share}
        log.info("new movies %s: hit rate@50 %.4f", name, hits / pairs)
    return {"users": int(len(users)), "liked_pairs": int(sum(len(liked[u]) for u in users)),
            "holdout_films": len(hold_idx), "results": out,
            "random_baseline_hit_rate": 50 / data.n_items}


def diversity_sweep(data, sources, content_sim, novelty, users) -> dict:
    rel = relevant_sets(data, users)
    w = weights()["established"]
    scores_cache = []
    for start in range(0, len(users), BATCH):
        ub = users[start:start + BATCH]
        sc = sources.score_all(full_profiles(data, ub))
        pool, norm = candidate_pool(sc, [known(data, u) for u in ub])
        final = blend(norm, w)
        for r in range(len(ub)):
            valid = pool[r] >= 0
            order = np.argsort(-np.where(valid, final[r], -np.inf))[:TOP_N]
            order = order[valid[order]]
            scores_cache.append((pool[r][order], final[r][order]))
    points = []
    for lam in np.round(np.arange(0.5, 1.0001, 0.05), 2):
        lists = [mmr(items, f, content_sim, novelty, K, float(lam), 0.0) for items, f in scores_cache]
        nd = float(np.mean([M.ndcg_at_k(l.tolist(), rel.get(u, set()), K) for u, l in zip(users, lists)]))
        div = float(np.mean([M.intra_list_diversity(l, content_sim) for l in lists]))
        points.append({"lambda": float(lam), "ndcg": nd, "diversity": div})
        log.info("diversity lambda %.2f: NDCG %.4f, ILD %.3f", lam, nd, div)
    modes = {}
    for m, cfg in MODES.items():
        lists = [mmr(items, f, content_sim, novelty, K, cfg["lambda"], cfg["beta"]) for items, f in scores_cache]
        modes[m] = {"lambda": cfg["lambda"], "beta": cfg["beta"],
                    "ndcg": float(np.mean([M.ndcg_at_k(l.tolist(), rel.get(u, set()), K) for u, l in zip(users, lists)])),
                    "diversity": float(np.mean([M.intra_list_diversity(l, content_sim) for l in lists]))}
    return {"users": int(len(users)), "sweep": points, "modes": modes, "note": "beta = 0 in the sweep; modes use their own beta"}


def calibration_check(data, sources, users, times) -> dict:
    """Match % (calibrator fitted on validation) against the observed share of liked TEST films."""
    cal = joblib.load(MODELS / "calibration.joblib")
    w_all = weights()
    ev = data.eval_df[data.eval_df["u"].isin(users)]
    val_rating = {(u, i): r for u, i, r in ev[["u", "i", "rating"]].itertuples(index=False)}
    out = {}
    for stage, k in (("cold", 2), ("warming", 6), ("established", None)):
        r_rows, l_rows = [], []
        for u in users:
            start, end = data.train.indptr[u], data.train.indptr[u + 1]
            items, vals, ts = data.train.indices[start:end], data.train.data[start:end], times[start:end]
            order = np.lexsort((items, ts))
            items, vals = items[order], vals[order]
            if k is None:
                r_rows.append((items, vals)), l_rows.append(np.array([], dtype=int))
                continue
            picks = items[vals >= 8][:ONBOARD]
            rest = np.array([j for j in range(len(items)) if items[j] not in set(picks)], dtype=int)[:k]
            r_rows.append((items[rest], vals[rest])), l_rows.append(picks)
        prof = Profiles(_csr(r_rows, data.n_items), _csr([(p, np.ones(len(p))) for p in l_rows], data.n_items),
                        train_rows=users)
        xs, ys = [], []
        for start in range(0, len(users), BATCH):
            sl = slice(start, start + BATCH)
            ub = users[sl]
            sc = sources.score_all(Profiles(prof.ratings[sl], prof.likes[sl], train_rows=ub))
            pool, norm = candidate_pool(sc, [known(data, u) for u in ub])
            final = blend(norm, w_all[stage])
            for r, u in enumerate(ub):
                for j, item in enumerate(pool[r]):
                    if item >= 0 and (u, item) in val_rating:
                        xs.append(final[r, j]), ys.append(val_rating[(u, item)] >= M.RELEVANT)
        xs, ys = np.array(xs), np.array(ys)
        prob = cal.probability(stage, xs)
        table = calibration_table(prob, ys)
        ece = float(sum(abs(t["predicted"] - t["observed"]) * t["n"] for t in table) / len(xs))
        out[stage] = {"pairs": int(len(xs)), "ece": ece, "passes": bool(ece < 0.05), "bins": table,
                      "mean_match_pct": float(np.mean(np.minimum(np.round(prob * 100), 99)))}
        log.info("calibration %s: ECE %.4f on %d pairs", stage, ece, len(xs))
    return {"users": int(len(users)), "stages": out, "pass_rule": "expected calibration error < 0.05 on test"}


def train_times(data, parts) -> np.ndarray:
    tr = pd.concat([pd.read_parquet(PROCESSED / "splits" / f"{p}.parquet") for p in parts], ignore_index=True)
    user_index = pd.Series(np.arange(data.n_users), index=data.user_ids)
    item_index = pd.Series(np.arange(data.n_items), index=data.item_ids)
    tr = tr[tr["ml_movie_id"].isin(item_index.index) & tr["user_id"].isin(user_index.index)]
    t = sp.csr_matrix((tr["timestamp"].to_numpy(np.float64),
                       (user_index.loc[tr["user_id"]].to_numpy(), item_index.loc[tr["ml_movie_id"]].to_numpy())),
                      shape=data.train.shape)
    t.sort_indices()
    data.train.sort_indices()
    return t.data


def main() -> None:
    import sys
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else \
        ["comparison", "cold_start", "new_movies", "diversity", "calibration", "global"]
    t0 = time.time()
    if "comparison" in only:
        write_json(METRICS / "test_comparison.json", model_comparison(("train", "val"), "test", "test"))
    if set(only) & {"cold_start", "diversity", "calibration"}:
        data = load_split(PROCESSED, "test", train_parts=("train", "val"))
        times = train_times(data, ("train", "val"))
        users = sample_eval_users(data, 2000, SEED)
        counts8 = np.asarray((data.train >= 8).sum(axis=1)).ravel()
        users = users[counts8[users] >= ONBOARD]
        content_sim = content_sim_for(data)
        sources = fit_sources(data, content_sim)
        novelty = scaled_novelty(data.item_counts(), data.n_users)
        if "cold_start" in only:
            write_json(METRICS / "cold_start.json", cold_start(data, sources, content_sim, novelty, users, times))
        if "diversity" in only:
            write_json(METRICS / "diversity.json", diversity_sweep(data, sources, content_sim, novelty, users))
        if "calibration" in only:
            write_json(METRICS / "calibration_check.json", calibration_check(data, sources, users, times))
    if "new_movies" in only:
        write_json(METRICS / "new_movies.json", new_movies())
    if "global" in only:
        write_json(METRICS / "global_cutoff.json", model_comparison(("global_train",), "global_test", "global"))
    log.info("step 11 done in %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()