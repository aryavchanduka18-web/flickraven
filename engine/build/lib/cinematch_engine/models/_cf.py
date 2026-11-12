"""Shared helpers for the neighborhood (CF) models."""
import numpy as np
import scipy.sparse as sp


def center_by_user(train: sp.csr_matrix, means: np.ndarray) -> sp.csr_matrix:
    """Subtract each user's mean rating from their ratings (only where they rated)."""
    rc = train.copy().astype(np.float32)
    rc.sort_indices()                      # kNN prediction binary-searches each user's films
    counts = np.diff(rc.indptr)
    rc.data -= np.repeat(means, counts)
    # A rating exactly equal to the user's mean becomes 0; keep it as a tiny value so the
    # indicator (who rated what) and the centered matrix share the same structure.
    rc.data[rc.data == 0] = 1e-6
    return rc


def indicator(m: sp.csr_matrix) -> sp.csr_matrix:
    ind = m.copy()
    ind.data = np.ones_like(ind.data, dtype=np.float32)
    return ind


def squared(m: sp.csr_matrix) -> sp.csr_matrix:
    sq = m.copy()
    sq.data = sq.data ** 2
    return sq


def dense(x) -> np.ndarray:
    return x.toarray() if sp.issparse(x) else np.asarray(x)


def top_positive(sim: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Per row: indices and values of the k largest positive similarities, sorted descending."""
    k = min(k, sim.shape[1])
    part = np.argpartition(-sim, k - 1, axis=1)[:, :k]
    vals = np.take_along_axis(sim, part, axis=1)
    order = np.argsort(-vals, axis=1)
    idx = np.take_along_axis(part, order, axis=1)
    vals = np.take_along_axis(vals, order, axis=1)
    vals = np.where(vals > 0, vals, 0).astype(np.float32)
    return idx.astype(np.int32), vals


def neighbor_matrix(idx: np.ndarray, vals: np.ndarray, k: int, n_cols: int) -> sp.csr_matrix:
    """Sparse rows keeping the first k neighbors of each row."""
    idx, vals = idx[:, :k], vals[:, :k]
    rows = np.repeat(np.arange(idx.shape[0]), idx.shape[1])
    m = sp.csr_matrix((vals.ravel(), (rows, idx.ravel())), shape=(idx.shape[0], n_cols), dtype=np.float32)
    m.eliminate_zeros()
    return m


def predict_from(num: np.ndarray, den: np.ndarray, means: np.ndarray, beta: float) -> np.ndarray:
    """mean + weighted average of centered neighbor ratings; beta shrinks thin support toward the mean."""
    return means[:, None] + num / (den + beta + 1e-9)