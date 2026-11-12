"""Evaluation metrics (spec section 12.3). Binary relevance: relevant = rating >= 7/10."""
import numpy as np

RELEVANT = 7


def precision_at_k(recs, relevant: set, k: int = 10) -> float:
    return sum(1 for r in recs[:k] if r in relevant) / k


def recall_at_k(recs, relevant: set, k: int = 10) -> float:
    if not relevant:
        return 0.0
    return sum(1 for r in recs[:k] if r in relevant) / len(relevant)


def average_precision_at_k(recs, relevant: set, k: int = 10) -> float:
    """AP@k = sum over hit positions i of P@i, divided by min(|relevant|, k)."""
    if not relevant:
        return 0.0
    hits, total = 0, 0.0
    for pos, r in enumerate(recs[:k], start=1):
        if r in relevant:
            hits += 1
            total += hits / pos
    return total / min(len(relevant), k)


def ndcg_at_k(recs, relevant: set, k: int = 10) -> float:
    """Binary gains: DCG = sum 1/log2(pos + 1) over hits; IDCG puts min(|relevant|, k) hits first."""
    if not relevant:
        return 0.0
    dcg = sum(1.0 / np.log2(pos + 1) for pos, r in enumerate(recs[:k], start=1) if r in relevant)
    idcg = sum(1.0 / np.log2(pos + 1) for pos in range(1, min(len(relevant), k) + 1))
    return dcg / idcg


def rmse(pred, true) -> float:
    pred, true = np.asarray(pred, float), np.asarray(true, float)
    return float(np.sqrt(np.mean((pred - true) ** 2)))


def mae(pred, true) -> float:
    pred, true = np.asarray(pred, float), np.asarray(true, float)
    return float(np.mean(np.abs(pred - true)))


def intra_list_diversity(recs, item_sim: np.ndarray) -> float:
    """1 - mean pairwise content similarity of the list."""
    recs = np.asarray(recs)
    if len(recs) < 2:
        return 0.0
    sub = item_sim[np.ix_(recs, recs)]
    n = len(recs)
    return float(1 - (sub.sum() - np.trace(sub)) / (n * (n - 1)))


def novelty(recs, pop_share: np.ndarray) -> float:
    """Mean -log2(share of users who rated the film)."""
    share = np.clip(pop_share[np.asarray(recs)], 1e-12, None)
    return float(np.mean(-np.log2(share)))


def bootstrap_ci(values, n_boot: int = 1000, seed: int = 42, alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean and 95% bootstrap confidence interval over users."""
    values = np.asarray(values, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    return float(values.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))