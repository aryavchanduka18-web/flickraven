"""Item-based CF (spec section 5, model 4).

Adjusted cosine: ratings are centered on each user's mean, then for films i and j, over the users
who rated both:  sim(i, j) = sum(r'_ui r'_uj) / (sqrt(sum r'_ui^2) sqrt(sum r'_uj^2)).
Shrinkage: sim * n / (n + lambda), where n = number of users who rated both, so similarities
built on a handful of shared users count for less. Only the top neighbors of each film are kept.

Prediction for user u and film i: u's mean + sum_j sim(i, j) r'_uj / sum_j |sim(i, j)| over the
neighbors j of i that u rated.
"""
import numpy as np
import scipy.sparse as sp

from cinematch_engine.models._cf import (
    center_by_user, dense, indicator, neighbor_matrix, predict_from, squared, top_positive,
)


class ItemCF:
    def __init__(self, shrinkages=(0, 10, 25, 50, 100), max_neighbors: int = 100, block: int = 1000):
        self.shrinkages, self.max_neighbors, self.block = tuple(shrinkages), max_neighbors, block

    def fit(self, train: sp.csr_matrix, means: np.ndarray) -> "ItemCF":
        self.means = means
        self.rc = center_by_user(train, means)
        self.ind = indicator(self.rc)
        sq = squared(self.rc)
        rc_t, ind_t, sq_t = self.rc.T.tocsr(), self.ind.T.tocsr(), sq.T.tocsr()
        n_items = train.shape[1]
        lists = {lam: ([], []) for lam in self.shrinkages}
        for start in range(0, n_items, self.block):
            rows = slice(start, min(start + self.block, n_items))
            num = dense(rc_t[rows] @ self.rc)                        # sum r'_ui r'_uj
            sq_i = dense(sq_t[rows] @ self.ind)                      # sum r'_ui^2 over co-raters
            sq_j = dense(ind_t[rows] @ sq)                           # sum r'_uj^2 over co-raters
            n = dense(ind_t[rows] @ self.ind)                        # co-raters
            with np.errstate(divide="ignore", invalid="ignore"):
                base = np.nan_to_num(num / np.sqrt(sq_i * sq_j)).astype(np.float32)
            base[np.arange(base.shape[0]), np.arange(rows.start, rows.stop)] = 0   # no self-similarity
            for lam in self.shrinkages:
                sim = base * (n / (n + lam)) if lam else base
                idx, vals = top_positive(sim, self.max_neighbors)
                lists[lam][0].append(idx)
                lists[lam][1].append(vals)
        self.neighbors = {lam: (np.vstack(i), np.vstack(v)) for lam, (i, v) in lists.items()}
        return self

    def configure(self, shrinkage: float, neighbors: int, beta: float = 0.0) -> "ItemCF":
        self.shrinkage = shrinkage
        idx, vals = self.neighbors[shrinkage]
        self.sim = neighbor_matrix(idx, vals, neighbors, idx.shape[0])   # rows = target film i
        self.sim_t = self.sim.T.tocsr()
        self.beta = beta
        return self

    def _num_den(self, users: np.ndarray):
        return dense(self.rc[users] @ self.sim_t), dense(self.ind[users] @ self.sim_t)

    def score(self, users: np.ndarray) -> np.ndarray:
        num, den = self._num_den(users)
        return predict_from(num, den, self.means[users], self.beta).astype(np.float32)

    def predict(self, users: np.ndarray, items: np.ndarray, fallback: np.ndarray, k: int,
                shrinkage: float | None = None) -> np.ndarray:
        """Standard kNN rating prediction for (user, film) pairs.

        For film i, take the k films most similar to i AMONG THE FILMS THIS USER RATED (searched in
        i's stored neighbor list), and average the user's centered ratings of them, weighted by
        similarity. Pairs where the user rated none of i's neighbors use `fallback`.
        """
        idx_all, vals_all = self.neighbors[self.shrinkage if shrinkage is None else shrinkage]
        rc, out = self.rc, np.empty(len(users), dtype=np.float32)
        for n, (u, i) in enumerate(zip(users, items)):
            start, end = rc.indptr[u], rc.indptr[u + 1]
            rated, centered = rc.indices[start:end], rc.data[start:end]
            nb, sims = idx_all[i], vals_all[i]
            pos = np.searchsorted(rated, nb)
            pos[pos >= len(rated)] = 0
            hit = (rated[pos] == nb) & (sims > 0)
            if not hit.any():
                out[n] = fallback[n]
                continue
            s, r = sims[hit][:k], centered[pos[hit]][:k]      # lists are sorted by similarity
            out[n] = self.means[u] + float(s @ r) / float(np.abs(s).sum())
        return np.clip(out, 1, 10)