"""Shilling attacks and a simple detector (spec section 14.1). Lab only: nothing here touches the site.

Attacks (each fake profile rates the target 10/10 and about 5% of the catalog as filler):
- average attack: filler films get roughly their own mean rating, so the fake user looks ordinary;
- bandwagon attack: a few very popular films get 10/10 (to look like many real users), the rest of the
  filler gets around the global mean.
Detector: three classic profile features, combined into one anomaly score:
- RDMA (rating deviation from mean agreement): average |rating - film mean| / film's rating count;
- degree of similarity: mean similarity to the profile's 10 nearest neighbors (fake profiles copy
  each other, so they are unusually similar);
- rating variance: fake profiles rate in a narrow, mechanical way.
"""
import numpy as np
import scipy.sparse as sp


def item_stats(train: sp.csr_matrix):
    csc = train.tocsc()
    counts = np.diff(csc.indptr)
    sums = np.asarray(csc.sum(axis=0)).ravel()
    sq = np.asarray(csc.multiply(csc).sum(axis=0)).ravel()
    mean = np.divide(sums, counts, out=np.zeros_like(sums, dtype=float), where=counts > 0)
    var = np.divide(sq, counts, out=np.zeros_like(sq, dtype=float), where=counts > 0) - mean ** 2
    return counts, mean, np.sqrt(np.maximum(var, 0))


def make_attack(train: sp.csr_matrix, kind: str, n_profiles: int, targets: np.ndarray, filler_frac: float,
                rng: np.random.Generator, n_bandwagon: int = 10) -> sp.csr_matrix:
    counts, mean, std = item_stats(train)
    n_items = train.shape[1]
    global_mean = float(train.data.mean())
    candidates = np.setdiff1d(np.nonzero(counts > 0)[0], targets)
    popular = np.argsort(-counts)[:n_bandwagon]
    n_filler = int(filler_frac * n_items)
    rows, cols, vals = [], [], []
    for p in range(n_profiles):
        filler = rng.choice(candidates, size=n_filler, replace=False)
        if kind == "average":
            r = rng.normal(mean[filler], np.maximum(std[filler], 0.5))
        elif kind == "bandwagon":
            r = rng.normal(global_mean, 1.5, size=len(filler))
            filler = np.concatenate([filler, popular])
            r = np.concatenate([r, np.full(len(popular), 10.0)])
        else:
            raise ValueError(kind)
        items = np.concatenate([filler, targets])
        r = np.concatenate([np.clip(np.round(r), 1, 10), np.full(len(targets), 10.0)])
        items, idx = np.unique(items, return_index=True)
        rows.append(np.full(len(items), p)), cols.append(items), vals.append(r[idx])
    return sp.csr_matrix((np.concatenate(vals).astype(np.float32), (np.concatenate(rows), np.concatenate(cols))),
                         shape=(n_profiles, n_items))


def detection_features(ratings: sp.csr_matrix, k: int = 10, batch: int = 2000) -> np.ndarray:
    """Columns: RDMA, degree of similarity (cosine on centered ratings), rating variance."""
    counts, mean, _ = item_stats(ratings)
    coo = ratings.tocoo()
    dev = np.abs(coo.data - mean[coo.col]) / np.maximum(counts[coo.col], 1)
    n = np.diff(ratings.indptr)
    rdma = np.bincount(coo.row, weights=dev, minlength=ratings.shape[0]) / np.maximum(n, 1)
    s1 = np.asarray(ratings.sum(axis=1)).ravel()
    s2 = np.asarray(ratings.multiply(ratings).sum(axis=1)).ravel()
    var = s2 / np.maximum(n, 1) - (s1 / np.maximum(n, 1)) ** 2
    centered = ratings.copy().astype(np.float32)
    centered.data -= np.repeat((s1 / np.maximum(n, 1)).astype(np.float32), n)
    norms = np.sqrt(np.asarray(centered.multiply(centered).sum(axis=1)).ravel()) + 1e-9
    unit = sp.diags(1 / norms) @ centered
    degsim = np.zeros(ratings.shape[0])
    for start in range(0, ratings.shape[0], batch):
        sims = (unit[start:start + batch] @ unit.T).toarray()
        sims[np.arange(sims.shape[0]), np.arange(start, start + sims.shape[0])] = -np.inf
        top = np.partition(sims, -k, axis=1)[:, -k:]
        degsim[start:start + batch] = top.mean(axis=1)
    return np.column_stack([rdma, degsim, var])


def anomaly_score(features: np.ndarray) -> np.ndarray:
    """High RDMA, high similarity to neighbors and LOW variance are suspicious."""
    z = (features - features.mean(axis=0)) / (features.std(axis=0) + 1e-9)
    return z[:, 0] + z[:, 1] - z[:, 2]