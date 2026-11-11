"""Step 9 (Phase 3 part): tune and evaluate the baseline models on VALIDATION only.

Models: bias baseline (MAE/RMSE reference), popularity, content-based, user CF, item CF.
Each model's settings are tuned on validation NDCG@10 (RMSE for the bias baseline); the tuned
model then gets the full evaluation (spec 12): accuracy with 95% bootstrap CIs, MAE/RMSE where the
model predicts ratings, coverage, diversity, novelty, long-tail share, popularity percentile.
The test split is not touched. Outputs: artifacts/models/*.json, artifacts/metrics/validation_baselines.json.
"""
import itertools
import json
import time

import numpy as np
import pandas as pd
import psutil
import scipy.sparse as sp

from cinematch_engine.data.splits import load_split
from cinematch_engine.eval import metrics as M
from cinematch_engine.eval.protocol import (
    evaluate_ranking, evaluate_ratings, rank_users, relevant_sets, sample_eval_users, top_k,
)
from cinematch_engine.models.bias import BiasBaseline
from cinematch_engine.models.content import BLOCKS, ContentModel, build_blocks, combine
from cinematch_engine.models.item_cf import ItemCF
from cinematch_engine.models.popularity import PopularityModel
from cinematch_engine.models.user_cf import UserCF
from pipeline.catalog import original_gate_mask
from pipeline.common import ARTIFACTS, PROCESSED, SEED, get_logger, write_json

log = get_logger("09_train")
MODELS, METRICS = ARTIFACTS / "models", ARTIFACTS / "metrics"
N_EVAL_USERS, K, BATCH = 5000, 10, 500
PROC = psutil.Process()


def peak_mb() -> float:
    info = PROC.memory_info()
    return round(getattr(info, "peak_wset", info.rss) / 2 ** 20)


class Ctx:
    """Everything shared by the models: data, evaluated users, relevant sets, reference similarity."""

    def __init__(self):
        self.data = load_split(PROCESSED, "val")
        self.users = sample_eval_users(self.data, N_EVAL_USERS, SEED)
        self.rel = relevant_sets(self.data, self.users)
        self.means = self.data.user_means()
        feats = sp.load_npz(ARTIFACTS / "features" / "content.npz")
        index = pd.read_parquet(ARTIFACTS / "features" / "content_index.parquet")
        row_of = dict(zip(index["tmdb_id"], index["row"]))
        self.content_rows = np.array([row_of[t] for t in self.data.item_tmdb])
        x = feats[self.content_rows]
        # Reference similarity for intra-list diversity: the fixed step-8 features (all blocks equal),
        # so every model's diversity is measured with the same ruler.
        self.item_sim = (x @ x.T).toarray().astype(np.float32)
        self.seen = {u: self.data.train.indices[self.data.train.indptr[u]:self.data.train.indptr[u + 1]]
                     for u in self.users}
        ev = self.data.eval_df[self.data.eval_df["u"].isin(self.users)]
        self.rating_pairs = (ev["u"].to_numpy(), ev["i"].to_numpy(), ev["rating"].to_numpy())

    def quick_ndcg(self, recs: np.ndarray) -> float:
        return float(np.mean([M.ndcg_at_k(l.tolist(), self.rel.get(u, set()), K) for u, l in zip(self.users, recs)]))

    def topk_batch(self, users, scores) -> np.ndarray:
        return top_k(scores, [self.seen[u] for u in users], K)


def batches(users):
    for s in range(0, len(users), BATCH):
        yield users[s:s + BATCH]


# ---------------------------------------------------------------- bias baseline
def run_bias(ctx: Ctx) -> tuple[dict, BiasBaseline]:
    u, i, r = ctx.rating_pairs
    grid = []
    for reg_i, reg_u in [(5, 2), (10, 5), (25, 10), (50, 25), (100, 50)]:
        m = BiasBaseline(reg_i, reg_u).fit(ctx.data.train)
        grid.append({"reg_item": reg_i, "reg_user": reg_u, "rmse": M.rmse(m.predict(u, i), r)})
    best = min(grid, key=lambda g: g["rmse"])
    model = BiasBaseline(best["reg_item"], best["reg_user"]).fit(ctx.data.train)
    result = {"settings": {k: best[k] for k in ("reg_item", "reg_user")}, "grid": grid,
              "ratings": evaluate_ratings(model.predict(u, i), r, u)}
    return result, model


# ---------------------------------------------------------------- popularity
def run_popularity(ctx: Ctx) -> dict:
    grid = []
    for m in [10, 100, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 1000000]:
        model = PopularityModel(m).fit(ctx.data.train)
        recs = rank_users(model.score, ctx.data, ctx.users, K, BATCH)
        grid.append({"m": m, "ndcg": ctx.quick_ndcg(recs)})
    best = max(grid, key=lambda g: g["ndcg"])
    model = PopularityModel(best["m"]).fit(ctx.data.train)
    recs = rank_users(model.score, ctx.data, ctx.users, K, BATCH)
    return {"settings": {"m": best["m"]}, "grid": grid,
            "ranking": evaluate_ranking(recs, ctx.users, ctx.data, ctx.item_sim, K)}


# ---------------------------------------------------------------- content
WEIGHT_PRESETS = {
    "equal": {},
    "text_heavy": {"text": 2.0},
    "structured_heavy": {"text": 0.5},
    "genre_director": {"genres": 2.0, "director": 2.0},
    "cast_director": {"cast": 2.0, "director": 2.0},
    "genres_heavy": {"genres": 3.0},
    "no_studio": {"studio": 0.0},
    "people_light": {"cast": 0.5, "studio": 0.5},
}


def run_content(ctx: Ctx) -> dict:
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
    credits = pd.read_parquet(PROCESSED / "credits_clean.parquet")
    row_of = {t: r for r, t in enumerate(movies["tmdb_id"])}
    rows = np.array([row_of[t] for t in ctx.data.item_tmdb])
    thin = movies["thin_text"].to_numpy()[rows]

    def evaluate(cb, weights, thin_scale) -> float:
        feats = combine(cb, weights)
        x = feats.matrix[rows]
        if thin_scale != 1.0:
            # Thin-text rule (spec 4.2): films with little text lean on their structured blocks.
            lo, hi = feats.block_columns["text"]
            x = apply_thin(x, thin, lo, hi, thin_scale)
        model = ContentModel(x).fit(ctx.data.train)
        recs = rank_users(model.score, ctx.data, ctx.users, K, BATCH)
        return ctx.quick_ndcg(recs), model, recs

    grid = []
    blocks = {n: build_blocks(movies, credits, ngram_max=n, fit_mask=original_gate_mask(movies)) for n in (1, 2)}
    for ngram, (name, w) in itertools.product((1, 2), WEIGHT_PRESETS.items()):
        ndcg, _, _ = evaluate(blocks[ngram], w, 1.0)
        grid.append({"ngram_max": ngram, "weights": name, "thin_text_scale": 1.0, "ndcg": ndcg})
        log.info("content %s", grid[-1])
    best = max(grid, key=lambda g: g["ndcg"])
    for scale in (0.5, 0.25):
        ndcg, _, _ = evaluate(blocks[best["ngram_max"]], WEIGHT_PRESETS[best["weights"]], scale)
        grid.append({**best, "thin_text_scale": scale, "ndcg": ndcg})
        log.info("content %s", grid[-1])
    best = max(grid, key=lambda g: g["ndcg"])
    _, model, recs = evaluate(blocks[best["ngram_max"]], WEIGHT_PRESETS[best["weights"]], best["thin_text_scale"])
    weights = {b: WEIGHT_PRESETS[best["weights"]].get(b, 1.0) for b in BLOCKS}
    return {"settings": {"ngram_max": best["ngram_max"], "weights_preset": best["weights"], "block_weights": weights,
                         "thin_text_scale": best["thin_text_scale"], "like_min": 7, "dislike_max": 5},
            "grid": grid, "ranking": evaluate_ranking(recs, ctx.users, ctx.data, ctx.item_sim, K)}


def apply_thin(x: sp.csr_matrix, thin: np.ndarray, lo: int, hi: int, scale: float) -> sp.csr_matrix:
    """Scale the text block of thin-text films, then re-normalize rows."""
    from sklearn.preprocessing import normalize
    x = x.tocsr(copy=True)
    for r in np.nonzero(thin)[0]:
        start, end = x.indptr[r], x.indptr[r + 1]
        cols = x.indices[start:end]
        mask = (cols >= lo) & (cols < hi)
        x.data[start:end][mask] *= scale
    return normalize(x, norm="l2").astype(np.float32)


# ---------------------------------------------------------------- user CF
def run_user_cf(ctx: Ctx, bias: BiasBaseline) -> dict:
    model = UserCF(max_neighbors=200).fit(ctx.data.train, ctx.means)
    overlaps, ks, betas = (2, 3, 5), (20, 50, 100, 200), (5.0, 10.0, 20.0, 50.0)
    recs = {c: [] for c in itertools.product(overlaps, ks, betas)}
    for ub in batches(ctx.users):
        cached = model.similarities(ub)
        for ov in overlaps:
            idx, vals = model.neighbors(ub, ov, max(ks), cached=cached)
            for k, beta in itertools.product(ks, betas):
                recs[(ov, k, beta)].append(ctx.topk_batch(ub, model.score_from(ub, idx, vals, k, beta)))
    grid = [{"min_overlap": ov, "k": k, "beta": b, "ndcg": ctx.quick_ndcg(np.vstack(recs[(ov, k, b)]))}
            for ov, k, b in recs]
    best = max(grid, key=lambda g: g["ndcg"])
    best_recs = np.vstack(recs[(best["min_overlap"], best["k"], best["beta"])])

    # Rating predictions on the evaluated users' validation ratings: standard kNN over the users
    # who rated each film; pairs with no positively similar rater use the bias baseline.
    u, i, r = ctx.rating_pairs
    pred = np.empty(len(r), dtype=np.float32)
    for ub in batches(ctx.users):
        sims = model.weighted(model.similarities(ub), best["min_overlap"])
        sel = np.nonzero(np.isin(u, ub))[0]
        rows = np.searchsorted(ub, u[sel])
        pred[sel] = model.predict_pairs(ub, sims, rows, i[sel], best["k"], bias.predict(u[sel], i[sel]))
    return {"settings": {k: best[k] for k in ("min_overlap", "k", "beta")} | {"significance": 50}, "grid": grid,
            "ranking": evaluate_ranking(best_recs, ctx.users, ctx.data, ctx.item_sim, K),
            "ratings": evaluate_ratings(pred, r, u)}


# ---------------------------------------------------------------- item CF
def run_item_cf(ctx: Ctx, bias: BiasBaseline) -> dict:
    shrinkages, neighbors, betas = (100, 400, 800, 1600, 3200), (10, 20, 50), (2.0, 10.0, 20.0, 50.0)
    model = ItemCF(shrinkages=shrinkages, max_neighbors=300).fit(ctx.data.train, ctx.means)
    log.info("item CF similarities done (peak %d MB)", peak_mb())
    grid, recs_of = [], {}
    for lam, n, beta in itertools.product(shrinkages, neighbors, betas):
        model.configure(lam, n, beta)
        recs = rank_users(model.score, ctx.data, ctx.users, K, BATCH)
        grid.append({"shrinkage": lam, "neighbors": n, "beta": beta, "ndcg": ctx.quick_ndcg(recs)})
        recs_of[(lam, n, beta)] = recs
    best = max(grid, key=lambda g: g["ndcg"])
    model.configure(best["shrinkage"], best["neighbors"], best["beta"])
    u, i, r = ctx.rating_pairs
    pred = model.predict(u, i, bias.predict(u, i), k=best["neighbors"])
    # Spec: "top-50 neighbors per film stored offline" - the served list keeps the tuned count (<= 50).
    return {"settings": {k: best[k] for k in ("shrinkage", "neighbors", "beta")}, "grid": grid,
            "ranking": evaluate_ranking(recs_of[(best["shrinkage"], best["neighbors"], best["beta"])],
                                        ctx.users, ctx.data, ctx.item_sim, K),
            "ratings": evaluate_ratings(pred, r, u)}


# ---------------------------------------------------------------- Funk SVD (Phase 4)
def fold_in_users(ctx: Ctx, n: int = 20) -> np.ndarray:
    """A few evaluated users with plenty of training ratings, for the fold-in vs retraining check."""
    counts = np.diff(ctx.data.train.indptr)[ctx.users]
    pool = ctx.users[counts >= 30]
    return np.sort(np.random.default_rng(SEED).choice(pool, size=min(n, len(pool)), replace=False))


def without_users(train: sp.csr_matrix, users: np.ndarray) -> sp.csr_matrix:
    keep = np.ones(train.shape[0], dtype=bool)
    keep[users] = False
    return sp.csr_matrix(train.multiply(keep[:, None]))


def fold_in_check(ctx: Ctx, users: np.ndarray, full_scores: np.ndarray, fold_scores: np.ndarray,
                  full_pred, fold_pred) -> dict:
    """Compare a model trained WITH these users against one trained WITHOUT them plus fold-in."""
    seen = [ctx.seen[u] for u in users]
    a, b = top_k(full_scores, seen, K), top_k(fold_scores, seen, K)
    overlap = float(np.mean([len(set(x) & set(y)) / K for x, y in zip(a, b)]))
    out = {"users": int(len(users)), "top10_overlap": overlap,
           "ndcg_full_training": float(np.mean([M.ndcg_at_k(x.tolist(), ctx.rel.get(u, set()), K) for u, x in zip(users, a)])),
           "ndcg_fold_in": float(np.mean([M.ndcg_at_k(x.tolist(), ctx.rel.get(u, set()), K) for u, x in zip(users, b)]))}
    if full_pred is not None:
        out["rmse_full_training"], out["rmse_fold_in"] = full_pred, fold_pred
    return out


def run_svd(ctx: Ctx) -> dict:
    from cinematch_engine.models.svd import FunkSVD
    u, i, r = ctx.rating_pairs
    grid = []

    def trial(**params):
        m = FunkSVD(**params).fit(ctx.data.train)
        recs = rank_users(m.score, ctx.data, ctx.users, K, BATCH)
        grid.append({**params, "ndcg": ctx.quick_ndcg(recs), "rmse": M.rmse(m.predict(u, i), r)})
        log.info("svd %s", grid[-1])
        return m

    for f, reg in itertools.product((50, 100), (0.02, 0.05, 0.1)):
        trial(n_factors=f, n_epochs=30, lr_all=0.005, reg_all=reg)
    b = max(grid, key=lambda g: g["ndcg"])
    for epochs, lr in ((20, 0.01), (50, 0.005)):
        trial(n_factors=b["n_factors"], n_epochs=epochs, lr_all=lr, reg_all=b["reg_all"])
    best = max(grid, key=lambda g: g["ndcg"])
    params = {k: best[k] for k in ("n_factors", "n_epochs", "lr_all", "reg_all")}
    model = FunkSVD(**params).fit(ctx.data.train)
    recs = rank_users(model.score, ctx.data, ctx.users, K, BATCH)

    # Fold-in check: retrain without a few users, fold them back in, compare with full training.
    fu = fold_in_users(ctx)
    partial = FunkSVD(**params).fit(without_users(ctx.data.train, fu))
    fold_scores, fold_pred, full_pred = [], [], []
    for user in fu:
        row = ctx.data.train[user]
        p, bu = partial.fold_in(row.indices, row.data, reg=params["reg_all"] * len(row.data))
        fold_scores.append(partial.score_vector(p, bu))
        sel = u == user
        fold_pred.append(np.clip(partial.score_vector(p, bu)[i[sel]], 1, 10))
        full_pred.append(model.predict(u[sel], i[sel]))
    true = np.concatenate([r[u == x] for x in fu])
    check = fold_in_check(ctx, fu, model.score(fu), np.vstack(fold_scores),
                          M.rmse(np.concatenate(full_pred), true), M.rmse(np.concatenate(fold_pred), true))
    log.info("svd fold-in check %s", check)
    return {"settings": params | {"fold_in_reg": "reg_all x number of the user's ratings"}, "grid": grid,
            "ranking": evaluate_ranking(recs, ctx.users, ctx.data, ctx.item_sim, K),
            "ratings": evaluate_ratings(model.predict(u, i), r, u), "fold_in_check": check}


# ---------------------------------------------------------------- implicit ALS (Phase 4)
def run_als(ctx: Ctx) -> dict:
    from cinematch_engine.models.als_implicit import ImplicitALS, implicit_strength
    strength = implicit_strength(ctx.data.train)
    grid = []
    for f, reg, alpha in itertools.product((32, 64, 128), (0.1, 0.3, 1.0), (0.1, 0.25, 0.5, 1.0, 2.0)):
        m = ImplicitALS(factors=f, regularization=reg, alpha=alpha, iterations=15).fit(strength)
        grid.append({"factors": f, "regularization": reg, "alpha": alpha, "iterations": 15,
                     "ndcg": ctx.quick_ndcg(rank_users(m.score, ctx.data, ctx.users, K, BATCH))})
        log.info("als %s", grid[-1])
    best = max(grid, key=lambda g: g["ndcg"])
    params = {k: best[k] for k in ("factors", "regularization", "alpha", "iterations")}
    model = ImplicitALS(**params).fit(strength)
    recs = rank_users(model.score, ctx.data, ctx.users, K, BATCH)

    fu = fold_in_users(ctx)
    partial = ImplicitALS(**params).fit(without_users(strength, fu))
    fold = []
    for user in fu:
        row = strength[user]
        fold.append(partial.Y @ partial.fold_in(row.indices, row.data))
    check = fold_in_check(ctx, fu, model.score(fu), np.vstack(fold), None, None)
    log.info("als fold-in check %s", check)
    return {"settings": params | {"signal": "rating - 6 for ratings >= 7", "confidence": "1 + alpha * signal"},
            "grid": grid, "ranking": evaluate_ranking(recs, ctx.users, ctx.data, ctx.item_sim, K),
            "fold_in_check": check}

# ---------------------------------------------------------------- display popularity
def popularity_scores(ctx: Ctx, m: float) -> pd.DataFrame:
    """movies.popularity_score for display: part A from train ratings (Bayesian average, tuned m);
    parts B/C/D and the new-movie holdout films from TMDB vote_count / vote_average, same formula."""
    from pipeline.common import TMDB_DIR, read_json
    from cinematch_engine.models.popularity import bayesian_average
    counts = ctx.data.item_counts()
    # Display score: same Bayesian formula with m = the median part-A rating count. The ranking model
    # tunes m very high (see decisions-log), which would squash every displayed score to the mean.
    m = float(np.median(counts[counts > 0]))
    pop = PopularityModel(m).fit(ctx.data.train)
    a = pd.DataFrame({"tmdb_id": ctx.data.item_tmdb, "popularity_score": pop.scores, "source": "movielens_train"})
    a = a[counts > 0]
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id"])
    rest = movies[~movies["tmdb_id"].isin(a["tmdb_id"])].copy()
    va = [read_json(TMDB_DIR / f"{t}.json") for t in rest["tmdb_id"]]
    votes = np.array([d.get("vote_count") or 0 for d in va], dtype=float)
    avg = np.array([d.get("vote_average") or 0 for d in va], dtype=float)
    m_tmdb = float(np.median(votes[votes > 0]))
    c_tmdb = float(np.average(avg[votes > 0], weights=votes[votes > 0]))
    rest["popularity_score"] = bayesian_average(avg * votes, votes, c_tmdb, m_tmdb)
    rest["source"] = "tmdb"
    out = pd.concat([a, rest], ignore_index=True)
    write_json(MODELS / "popularity_display.json", {"m_movielens_display": m, "m_tmdb": m_tmdb, "c_tmdb": c_tmdb,
                                                    "films": out["source"].value_counts().to_dict()})
    return out


def write_popularity_to_db(scores: pd.DataFrame) -> int:
    from sqlalchemy import create_engine, text
    from pipeline.common import env
    engine = create_engine(env("DATABASE_URL"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TEMP TABLE pop (tmdb_id int PRIMARY KEY, score real) ON COMMIT DROP"))
        rows = [{"t": int(t), "s": float(s)} for t, s in zip(scores["tmdb_id"], scores["popularity_score"])]
        conn.execute(text("INSERT INTO pop VALUES (:t, :s)"), rows)
        n = conn.execute(text("UPDATE movies m SET popularity_score = p.score FROM pop p WHERE p.tmdb_id = m.tmdb_id")).rowcount
    engine.dispose()
    return n


PHASE3 = ("bias", "popularity", "content", "item_cf", "user_cf")
PHASE4 = ("svd", "als")


def assemble(ctx_meta: dict) -> None:
    """validation_baselines.json (Phase 3 models) and validation_mf.json (Phase 4) from per-model files."""
    per = METRICS / "validation"
    for out_name, names in (("validation_baselines.json", PHASE3), ("validation_mf.json", PHASE4)):
        models = {n: json.loads((per / f"{n}.json").read_text(encoding="utf-8")) for n in names if (per / f"{n}.json").exists()}
        if models:
            write_json(METRICS / out_name, {**ctx_meta, "models": models})


def main(only: list[str] | None = None) -> None:
    import sys
    if only is None:
        args = [a for a in sys.argv[1:] if a.startswith("--models=")]
        only = args[0].split("=", 1)[1].split(",") if args else list(PHASE3 + PHASE4)
    MODELS.mkdir(parents=True, exist_ok=True)
    (METRICS / "validation").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ctx = Ctx()
    write_json(METRICS / "eval_users_val.json", {"seed": SEED, "n": int(len(ctx.users)), "users": ctx.users.tolist()})
    log.info("data: %d users x %d films; %d evaluated users; setup %.0fs, peak %d MB",
             ctx.data.n_users, ctx.data.n_items, len(ctx.users), time.time() - t0, peak_mb())
    bias = BiasBaseline(**json.loads((MODELS / "bias.json").read_text(encoding="utf-8"))["settings"]).fit(ctx.data.train) \
        if "bias" not in only and (MODELS / "bias.json").exists() else None
    runners = {"bias": run_bias, "popularity": run_popularity, "content": run_content,
               "item_cf": run_item_cf, "user_cf": run_user_cf, "svd": run_svd, "als": run_als}
    for name in [n for n in PHASE3 + PHASE4 if n in only]:
        start = time.time()
        args = (ctx, bias) if name in ("item_cf", "user_cf") else (ctx,)
        out = runners[name](*args)
        if name == "bias":
            out, bias = out
        out["runtime_seconds"] = round(time.time() - start, 1)
        out["peak_memory_mb_so_far"] = peak_mb()
        (MODELS / f"{name}.json").write_text(json.dumps({"settings": out["settings"], "grid": out["grid"]}, indent=2), encoding="utf-8")
        write_json(METRICS / "validation" / f"{name}.json", {k: v for k, v in out.items() if k != "grid"})
        log.info("%s tuned: %s (%.0fs, peak %d MB)", name, out["settings"], out["runtime_seconds"], peak_mb())
        if name == "popularity":
            n = write_popularity_to_db(popularity_scores(ctx, out["settings"]["m"]))
            log.info("popularity_score written for %d films", n)
    assemble({"split": "val", "evaluated_users": int(len(ctx.users)), "k": K, "relevant_threshold": M.RELEVANT,
              "universe_films": int(ctx.data.n_items), "train_users": int(ctx.data.n_users),
              "peak_memory_mb": peak_mb()})
    log.info("done in %.0fs, peak %d MB", time.time() - t0, peak_mb())


if __name__ == "__main__":
    main()