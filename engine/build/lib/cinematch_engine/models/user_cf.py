"""User-based CF (spec section 5, model 3).

Pearson correlation on co-rated films: ratings are centered on each user's mean, then for users u
and v, over the films both rated:  corr = sum(r'_ui r'_vi) / (sqrt(sum r'_ui^2) sqrt(sum r'_vi^2)).
Significance weighting: corr * min(n, 50) / 50, where n = films in common, so a correlation from
3 shared films counts for much less than one from 50. Pairs with fewer than `min_overlap` shared
films are ignored. Only the k most similar users with positive similarity are kept.

Prediction for user u and film i: u's mean + sum_v sim(u, v) r'_vi / sum_v |sim(u, v)| over the
neighbors v who rated i. Neighbors are found in batches of users, never as a full user-user matrix.
"""
import numpy as np
import scipy.sparse as sp

from cinematch_engine.models._cf import (
    center_by_user, dense, indicator, neighbor_matrix, predict_from, squared, top_positive,
)

SIGNIFICANCE = 50


class UserCF:
    def __init__(self, max_neighbors: int = 100):
        self.max_neighbors = max_neighbors

    def fit(self, train: sp.csr_matrix, means: np.ndarray) -> "UserCF":
        self.means = means
        self.rc = center_by_user(train, means)
        self.ind = indicator(self.rc)
        self.sq = squared(self.rc)
        self.rc_t, self.ind_t, self.sq_t = self.rc.T.tocsr(), self.ind.T.tocsr(), self.sq.T.tocsr()
        return self

    def similarities(self, users: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Raw Pearson (before overlap filtering) and co-rated counts, users x all users."""
        num = dense(self.rc[users] @ self.rc_t)
        sq_u = dense(self.sq[users] @ self.ind_t)
        sq_v = dense(self.ind[users] @ self.sq_t)
        n = dense(self.ind[users] @ self.ind_t)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.nan_to_num(num / np.sqrt(sq_u * sq_v)).astype(np.float32)
        corr[np.arange(len(users)), users] = 0                       # no self-similarity
        return corr, n.astype(np.float32)

    def neighbors(self, users: np.ndarray, min_overlap: int, k_max: int | None = None,
                  cached=None) -> tuple[np.ndarray, np.ndarray]:
        corr, n = cached if cached is not None else self.similarities(users)
        sim = corr * (np.minimum(n, SIGNIFICANCE) / SIGNIFICANCE)
        sim[n < min_overlap] = 0
        return top_positive(sim, k_max or self.max_neighbors)

    def score_from(self, users: np.ndarray, idx: np.ndarray, vals: np.ndarray, k: int,
                   beta: float = 0.0) -> np.ndarray:
        num, den = self._num_den(idx, vals, k)
        return predict_from(num, den, self.means[users], beta).astype(np.float32)

    def _num_den(self, idx, vals, k):
        nb = neighbor_matrix(idx, vals, k, self.rc.shape[0])
        return dense(nb @ self.rc), dense(nb @ self.ind)

    def predict_pairs(self, users: np.ndarray, sims: np.ndarray, pair_rows: np.ndarray,
                      pair_items: np.ndarray, k: int, fallback: np.ndarray) -> np.ndarray:
        """Standard kNN rating prediction: for (u, i), the k users most similar to u AMONG THOSE WHO
        RATED i, averaging their centered ratings of i weighted by similarity. `sims` holds the
        (overlap-filtered, significance-weighted) similarities of `users` to every user."""
        rc_csc = self._rc_csc if hasattr(self, "_rc_csc") else self.rc.tocsc()
        self._rc_csc = rc_csc
        out = np.empty(len(pair_rows), dtype=np.float32)
        for n, (row, i) in enumerate(zip(pair_rows, pair_items)):
            raters = rc_csc.indices[rc_csc.indptr[i]:rc_csc.indptr[i + 1]]
            centered = rc_csc.data[rc_csc.indptr[i]:rc_csc.indptr[i + 1]]
            s = sims[row, raters]
            pos = s > 0
            if not pos.any():
                out[n] = fallback[n]
                continue
            s, r = s[pos], centered[pos]
            if len(s) > k:
                top = np.argpartition(-s, k - 1)[:k]
                s, r = s[top], r[top]
            out[n] = self.means[users[row]] + float(s @ r) / float(s.sum())
        return np.clip(out, 1, 10)

    def weighted(self, cached, min_overlap: int) -> np.ndarray:
        corr, n = cached
        sim = corr * (np.minimum(n, SIGNIFICANCE) / SIGNIFICANCE)
        sim[n < min_overlap] = 0
        return sim