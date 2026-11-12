"""Candidates, normalization and the stage-weighted blend (spec sections 6.3, 6.5, 6.6).

1. Candidates: the top `per_source` films from each source, merged into one pool.
2. Normalization: within the user's pool, each source's scores become a 0-1 percentile rank among the
   films THAT SOURCE proposed; a source that did not propose a film gives it 0. Raw scores from
   different models are never added directly.
3. Blend: final = sum over sources of weight[stage][source] x normalized score.
This is a switching hybrid (weights change with the stage) inside a weighted hybrid (the blend)
inside a cascade (candidates, then blend, then rerank).
"""
import numpy as np

from cinematch_engine.sources import SOURCES

PER_SOURCE = 50


def candidate_pool(scores: dict[str, np.ndarray], excluded: list[np.ndarray], per_source: int = PER_SOURCE):
    """Returns (pool, norm): pool = (users x P) item indices padded with -1, norm = (S x users x P) in [0, 1]."""
    n_users = next(iter(scores.values())).shape[0]
    pools, norms = [], []
    for u in range(n_users):
        proposed = {}
        for s in SOURCES:
            sc = scores[s][u].copy()
            finite = sc[np.isfinite(sc)]
            if finite.size == 0 or finite.max() - finite.min() < 1e-9:
                proposed[s] = np.array([], dtype=np.int64)   # no information about this user: propose nothing
                continue
            sc[excluded[u]] = -np.inf
            top = np.argpartition(-sc, per_source)[:per_source]
            top = top[np.isfinite(sc[top])]
            proposed[s] = top
        pool = np.unique(np.concatenate(list(proposed.values())))
        norm = np.zeros((len(SOURCES), len(pool)), dtype=np.float32)
        pos = {item: j for j, item in enumerate(pool)}
        for si, s in enumerate(SOURCES):
            items = proposed[s]
            if len(items) == 0:
                continue
            order = np.argsort(np.argsort(scores[s][u][items]))       # 0 = lowest
            pct = (order + 1) / len(items)                            # best = 1.0
            norm[si, [pos[i] for i in items]] = pct
        pools.append(pool)
        norms.append(norm)
    width = max(len(p) for p in pools)
    pool_arr = np.full((n_users, width), -1, dtype=np.int64)
    norm_arr = np.zeros((len(SOURCES), n_users, width), dtype=np.float32)
    for u, (p, n) in enumerate(zip(pools, norms)):
        pool_arr[u, :len(p)] = p
        norm_arr[:, u, :len(p)] = n
    return pool_arr, norm_arr


def blend(norm: np.ndarray, weights: dict[str, float]) -> np.ndarray:
    """final[u, j] = sum_s w_s * norm[s, u, j]."""
    w = np.array([weights.get(s, 0.0) for s in SOURCES], dtype=np.float32)
    return np.tensordot(w, norm, axes=1)


def ranked(pool: np.ndarray, final: np.ndarray, k: int) -> np.ndarray:
    """Top-k item indices per user from the pool by final score (padding never wins)."""
    f = np.where(pool >= 0, final, -np.inf)
    order = np.argsort(-f, axis=1)[:, :k]
    return np.take_along_axis(pool, order, axis=1)


def contributions(norm_u: np.ndarray, weights: dict[str, float]) -> np.ndarray:
    """Per-source share of each pool film's final score (S x P), used by the explanations."""
    w = np.array([weights.get(s, 0.0) for s in SOURCES], dtype=np.float32)[:, None]
    parts = w * norm_u
    total = parts.sum(axis=0, keepdims=True)
    return np.divide(parts, total, out=np.zeros_like(parts), where=total > 0)