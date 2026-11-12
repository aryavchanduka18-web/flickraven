"""Per-source scoring of user profiles (spec sections 6.1 and 6.3).

A *profile* is what the engine knows about a user right now:
- explicit ratings (1-10) on films,
- onboarding picks (and, live, likes): preference signals that feed the content profile and ALS
  with the weight of a like, but never the explicit models (user CF, item CF, SVD),
- implicit signal strengths per film (live: event weights; offline: derived from ratings >= 7).

The same code scores a live site user and a simulated offline user, so the model that is
evaluated is the model that is served. Sources: popularity, content, item_cf, user_cf, svd, als.
"""
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from cinematch_engine.models._cf import center_by_user, dense, indicator, neighbor_matrix, squared, top_positive
from cinematch_engine.models.content import profile_weights
from cinematch_engine.models.user_cf import SIGNIFICANCE

SOURCES = ("popularity", "content", "item_cf", "user_cf", "svd", "als")
LIKE_AS_RATING = 10      # a like / onboarding pick counts like a 10/10 for content and ALS (strength 4)
LIKE_STRENGTH = 4.0


@dataclass
class Profiles:
    """A batch of user profiles over the item index space."""
    ratings: sp.csr_matrix               # explicit ratings, 0 = none
    likes: sp.csr_matrix                 # 1 where the user picked / liked the film
    strength: sp.csr_matrix | None = None   # implicit strengths; None = derive from ratings and likes
    train_rows: np.ndarray | None = None    # offline: the user's own row in the CF training matrix

    def __len__(self) -> int:
        return self.ratings.shape[0]

    def implicit(self) -> sp.csr_matrix:
        if self.strength is not None:
            return self.strength
        r = self.ratings.copy().astype(np.float32)
        r.data = np.where(r.data >= 7, r.data - 6, 0).astype(np.float32)
        likes = self.likes.astype(np.float32) * LIKE_STRENGTH
        out = r.maximum(likes).tocsr()
        out.eliminate_zeros()
        return out

    def content_ratings(self) -> sp.csr_matrix:
        """Ratings with liked/picked films counted as 10/10 (spec 6.1)."""
        return self.ratings.maximum(self.likes.astype(np.float32) * LIKE_AS_RATING).tocsr()


def _same_structure(m: sp.csr_matrix, data: np.ndarray) -> sp.csr_matrix:
    """A CSR matrix with new values on m's sparsity pattern, sharing m's index arrays (no copy)."""
    out = sp.csr_matrix((data, m.indices, m.indptr), shape=m.shape, copy=False)
    out.has_sorted_indices = m.has_sorted_indices        # never re-sort: the indices are shared
    return out


class SourceModels:
    """Fitted source models over one item index space."""

    def __init__(self, train: sp.csr_matrix, popularity: np.ndarray, content_sim: np.ndarray,
                 item_neighbors: tuple[np.ndarray, np.ndarray], item_k: int, item_beta: float,
                 user_cf: dict, svd: dict, als: dict):
        self.n_items = train.shape[1]
        self.popularity = popularity.astype(np.float32)
        self.content_sim = content_sim
        idx, vals = item_neighbors
        self.item_sim_t = neighbor_matrix(idx, vals, item_k, self.n_items).T.tocsr()
        self.item_beta = item_beta
        # user CF neighbors come from the training users
        means = np.asarray(train.sum(axis=1)).ravel() / np.maximum(np.diff(train.indptr), 1)
        self.cf_means = means.astype(np.float32)
        # Five matrices over the same ratings: centered, who-rated-what, and their transposes. They share
        # two sparsity structures, so the index arrays (and the all-ones data) are stored once. The values
        # are exactly those of indicator(), squared() and .T.tocsr(); this only saves memory (hosting has 512 MB).
        self.cf_rc = center_by_user(train, self.cf_means)
        self.cf_rc_t = self.cf_rc.T.tocsr()
        ones = np.ones(self.cf_rc.nnz, dtype=np.float32)
        self.cf_ind = _same_structure(self.cf_rc, ones)
        self.cf_ind_t = _same_structure(self.cf_rc_t, ones)
        self.cf_sq_t = _same_structure(self.cf_rc_t, self.cf_rc_t.data ** 2)
        self.user_cf = user_cf                 # {"k", "min_overlap", "beta"}
        self.svd = svd                         # {"mu", "bi", "Q", "reg"}
        self.als = als                         # {"Y", "alpha", "reg"}
        self.als["YtY"] = als["Y"].T @ als["Y"]

    # ------------------------------------------------------------------ sources
    def score_all(self, prof: Profiles) -> dict[str, np.ndarray]:
        return {"popularity": np.broadcast_to(self.popularity, (len(prof), self.n_items)).copy(),
                "content": self.content(prof), "item_cf": self.item_cf(prof), "user_cf": self.user_cf_scores(prof),
                "svd": self.svd_scores(prof), "als": self.als_scores(prof)}

    def content(self, prof: Profiles) -> np.ndarray:
        return np.asarray(profile_weights(prof.content_ratings()) @ self.content_sim, dtype=np.float32)

    @staticmethod
    def _means(r: sp.csr_matrix) -> np.ndarray:
        n = np.diff(r.indptr)
        return (np.asarray(r.sum(axis=1)).ravel() / np.maximum(n, 1)).astype(np.float32)

    def item_cf(self, prof: Profiles) -> np.ndarray:
        r = prof.ratings
        means = self._means(r)
        if r.nnz == 0:
            return np.zeros((len(prof), self.n_items), dtype=np.float32)
        rc = center_by_user(r, means)
        num, den = dense(rc @ self.item_sim_t), dense(indicator(rc) @ self.item_sim_t)
        return (means[:, None] + num / (den + self.item_beta + 1e-9)).astype(np.float32)

    def user_cf_scores(self, prof: Profiles) -> np.ndarray:
        r = prof.ratings
        means = self._means(r)
        out = np.zeros((len(prof), self.n_items), dtype=np.float32)
        if r.nnz == 0:
            return out
        rc = center_by_user(r, means)
        ind, sq = indicator(rc), squared(rc)
        num = dense(rc @ self.cf_rc_t)
        sq_u = dense(sq @ self.cf_ind_t)
        sq_v = dense(ind @ self.cf_sq_t)
        n = dense(ind @ self.cf_ind_t)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.nan_to_num(num / np.sqrt(sq_u * sq_v)).astype(np.float32)
        sim = corr * (np.minimum(n, SIGNIFICANCE) / SIGNIFICANCE)
        sim[n < self.user_cf["min_overlap"]] = 0
        if prof.train_rows is not None:                       # never use yourself as a neighbor
            sim[np.arange(len(prof)), prof.train_rows] = 0
        idx, vals = top_positive(sim, self.user_cf["k"])
        self.last_neighbors = (idx, vals)                     # kept for explanations (neighbor votes)
        nb = neighbor_matrix(idx, vals, self.user_cf["k"], sim.shape[1])
        num, den = dense(nb @ self.cf_rc), dense(nb @ self.cf_ind)
        return (means[:, None] + num / (den + self.user_cf["beta"] + 1e-9)).astype(np.float32)

    def svd_scores(self, prof: Profiles) -> np.ndarray:
        s = self.svd
        out = np.empty((len(prof), self.n_items), dtype=np.float32)
        base = s["mu"] + s["bi"]
        for row in range(len(prof)):
            r = prof.ratings[row]
            if r.nnz == 0:
                out[row] = base
                continue
            X = np.hstack([s["Q"][r.indices], np.ones((r.nnz, 1), dtype=np.float32)]).astype(np.float64)
            y = r.data - s["mu"] - s["bi"][r.indices]
            sol = np.linalg.solve(X.T @ X + s["reg"] * r.nnz * np.eye(X.shape[1]), X.T @ y)
            out[row] = base + sol[-1] + s["Q"] @ sol[:-1]
        return out

    def als_scores(self, prof: Profiles) -> np.ndarray:
        a = self.als
        strength = prof.implicit()
        out = np.zeros((len(prof), self.n_items), dtype=np.float32)
        f = a["Y"].shape[1]
        for row in range(len(prof)):
            w = strength[row]
            if w.nnz == 0:
                continue
            c = 1.0 + a["alpha"] * w.data.astype(np.float64)
            Yu = a["Y"][w.indices].astype(np.float64)
            A = a["YtY"] + (Yu.T * (c - 1.0)) @ Yu + a["reg"] * np.eye(f)
            x = np.linalg.solve(A, Yu.T @ c)
            out[row] = a["Y"] @ x
        return out