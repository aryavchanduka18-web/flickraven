"""Funk SVD with biases (spec section 5, model 5), trained with scikit-surprise.

prediction = mu + b_user + b_film + p_user . q_film
Learned by stochastic gradient descent on the known ratings only, with L2 regularization.

Fold-in (new or changed users, no retraining): keep every film's q and b fixed and solve a small
regularized least-squares problem for the user's [p_user, b_user] from the user's own ratings:
    minimize  sum_i (r_ui - mu - b_i - p.q_i - b_u)^2 + lambda (|p|^2 + b_u^2)
which has the closed form  [p, b_u] = (X^T X + lambda I)^-1 X^T y,  X = [q_i, 1],  y = r_ui - mu - b_i.
"""
import numpy as np
import pandas as pd
import scipy.sparse as sp
from surprise import SVD, Dataset, Reader


class FunkSVD:
    def __init__(self, n_factors: int = 100, n_epochs: int = 30, lr_all: float = 0.005,
                 reg_all: float = 0.05, seed: int = 42):
        self.params = dict(n_factors=n_factors, n_epochs=n_epochs, lr_all=lr_all, reg_all=reg_all)
        self.seed = seed

    def fit(self, train: sp.csr_matrix) -> "FunkSVD":
        coo = train.tocoo()
        df = pd.DataFrame({"u": coo.row, "i": coo.col, "r": coo.data})
        trainset = Dataset.load_from_df(df, Reader(rating_scale=(1, 10))).build_full_trainset()
        algo = SVD(random_state=self.seed, **self.params)
        algo.fit(trainset)
        n_users, n_items = train.shape
        f = self.params["n_factors"]
        # Map surprise's inner ids back to our matrix indices.
        self.P = np.zeros((n_users, f), dtype=np.float32)
        self.Q = np.zeros((n_items, f), dtype=np.float32)
        self.bu = np.zeros(n_users, dtype=np.float32)
        self.bi = np.zeros(n_items, dtype=np.float32)
        for inner in range(trainset.n_users):
            raw = trainset.to_raw_uid(inner)
            self.P[raw], self.bu[raw] = algo.pu[inner], algo.bu[inner]
        for inner in range(trainset.n_items):
            raw = trainset.to_raw_iid(inner)
            self.Q[raw], self.bi[raw] = algo.qi[inner], algo.bi[inner]
        self.mu = float(trainset.global_mean)
        return self

    def score(self, users: np.ndarray) -> np.ndarray:
        return (self.mu + self.bu[users, None] + self.bi[None, :] + self.P[users] @ self.Q.T).astype(np.float32)

    def predict(self, users: np.ndarray, items: np.ndarray) -> np.ndarray:
        pred = self.mu + self.bu[users] + self.bi[items] + np.einsum("ij,ij->i", self.P[users], self.Q[items])
        return np.clip(pred, 1, 10).astype(np.float32)

    def fold_in(self, items: np.ndarray, ratings: np.ndarray, reg: float) -> tuple[np.ndarray, float]:
        """User vector and bias from the user's ratings, with all film parameters fixed."""
        X = np.hstack([self.Q[items], np.ones((len(items), 1), dtype=np.float32)]).astype(np.float64)
        y = ratings.astype(np.float64) - self.mu - self.bi[items]
        A = X.T @ X + reg * np.eye(X.shape[1])
        sol = np.linalg.solve(A, X.T @ y)
        return sol[:-1].astype(np.float32), float(sol[-1])

    def score_vector(self, p: np.ndarray, bu: float) -> np.ndarray:
        return (self.mu + bu + self.bi + self.Q @ p).astype(np.float32)