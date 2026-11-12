"""Evaluation protocol (spec section 12.1).

- A fixed sample of evaluated users (seed 42), the same for every model.
- Full ranking: every universe film the user has not rated in training is a candidate.
  No sampled negatives (Krichene and Rendle, 2020).
- Accuracy metrics per user, beyond-accuracy metrics over the top-10 lists, 95% bootstrap CIs.
"""
from collections.abc import Callable

import numpy as np
import pandas as pd

from cinematch_engine.data.splits import SplitData
from cinematch_engine.eval import metrics as M

ScoreFn = Callable[[np.ndarray], np.ndarray]   # user indices -> dense scores (len(users) x n_items)


def sample_eval_users(data: SplitData, n: int = 5000, seed: int = 42) -> np.ndarray:
    """Users with at least one relevant film in the evaluated split, sampled once with a fixed seed."""
    eligible = np.sort(data.eval_df.loc[data.eval_df["rating"] >= M.RELEVANT, "u"].unique())
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(eligible, size=min(n, len(eligible)), replace=False))


def relevant_sets(data: SplitData, users: np.ndarray) -> dict[int, set]:
    rel = data.eval_df[(data.eval_df["rating"] >= M.RELEVANT) & data.eval_df["u"].isin(users)]
    return {u: set(g["i"].tolist()) for u, g in rel.groupby("u")}


def top_k(scores: np.ndarray, train_rows, k: int) -> np.ndarray:
    """Top-k item indices per row after removing each user's training films."""
    scores = scores.astype(np.float32, copy=True)
    for r, seen in enumerate(train_rows):
        scores[r, seen] = -np.inf
    part = np.argpartition(-scores, k, axis=1)[:, :k]
    order = np.take_along_axis(scores, part, axis=1).argsort(axis=1)[:, ::-1]
    return np.take_along_axis(part, order, axis=1)


def rank_users(score_fn: ScoreFn, data: SplitData, users: np.ndarray, k: int = 10, batch: int = 500) -> np.ndarray:
    lists = []
    for start in range(0, len(users), batch):
        ub = users[start:start + batch]
        scores = score_fn(ub)
        seen = [data.train.indices[data.train.indptr[u]:data.train.indptr[u + 1]] for u in ub]
        lists.append(top_k(scores, seen, k))
    return np.vstack(lists)


def evaluate_ranking(recs: np.ndarray, users: np.ndarray, data: SplitData, item_sim: np.ndarray,
                     k: int = 10, n_boot: int = 1000) -> dict:
    """Accuracy (per user, with CIs) and beyond-accuracy metrics for the users' top-k lists."""
    rel = relevant_sets(data, users)
    per_user = {"precision": [], "recall": [], "map": [], "ndcg": [], "diversity": [], "novelty": []}
    counts = data.item_counts()
    pop_share = counts / data.n_users
    for u, lst in zip(users, recs):
        r = rel.get(u, set())
        lst = lst.tolist()
        per_user["precision"].append(M.precision_at_k(lst, r, k))
        per_user["recall"].append(M.recall_at_k(lst, r, k))
        per_user["map"].append(M.average_precision_at_k(lst, r, k))
        per_user["ndcg"].append(M.ndcg_at_k(lst, r, k))
        per_user["diversity"].append(M.intra_list_diversity(lst, item_sim))
        per_user["novelty"].append(M.novelty(lst, pop_share))

    out = {name: dict(zip(("mean", "ci_low", "ci_high"), M.bootstrap_ci(v, n_boot))) for name, v in per_user.items()}
    flat = recs.ravel()
    # Popularity rank by training count: percentile 100 = most rated film.
    pct = pd.Series(counts).rank(pct=True).to_numpy() * 100
    head = counts >= np.quantile(counts, 0.80)            # the most popular 20% of the universe
    out["coverage"] = float(len(np.unique(flat)) / data.n_items)
    out["long_tail_share"] = float(100 * (~head[flat]).mean())
    out["mean_popularity_percentile"] = float(pct[flat].mean())
    out["users"] = int(len(users))
    return out


def evaluate_ratings(pred: np.ndarray, true: np.ndarray, user_of_rating: np.ndarray,
                     n_boot: int = 1000, seed: int = 42) -> dict:
    """MAE/RMSE over held-out ratings, with 95% CIs from a bootstrap over users (spec 12.2).

    Each bootstrap sample redraws users and recomputes the rating-weighted error over all their
    ratings, so the interval is about the same quantity as the reported value.
    """
    df = pd.DataFrame({"u": user_of_rating, "se": (pred - true) ** 2, "ae": np.abs(pred - true)})
    g = df.groupby("u").agg(se=("se", "sum"), ae=("ae", "sum"), n=("se", "size"))
    se, ae, n = g["se"].to_numpy(), g["ae"].to_numpy(), g["n"].to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(g), size=(n_boot, len(g)))
    rmse_b = np.sqrt(se[idx].sum(axis=1) / n[idx].sum(axis=1))
    mae_b = ae[idx].sum(axis=1) / n[idx].sum(axis=1)
    return {
        "rmse": {"mean": M.rmse(pred, true), "ci_low": float(np.quantile(rmse_b, 0.025)),
                 "ci_high": float(np.quantile(rmse_b, 0.975))},
        "mae": {"mean": M.mae(pred, true), "ci_low": float(np.quantile(mae_b, 0.025)),
                "ci_high": float(np.quantile(mae_b, 0.975))},
        "ratings": int(len(true)),
    }