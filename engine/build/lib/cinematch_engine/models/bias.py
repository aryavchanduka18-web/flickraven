"""Bias baseline: global mean + user bias + film bias (the MAE/RMSE reference in spec 12.2).

prediction = mu + b_user + b_film, biases learned by a few rounds of regularized averaging
(film biases first, then user biases), as in Koren's baseline predictors.
"""
import numpy as np
import scipy.sparse as sp


class BiasBaseline:
    def __init__(self, reg_item: float = 25.0, reg_user: float = 10.0, iterations: int = 3):
        self.reg_item, self.reg_user, self.iterations = reg_item, reg_user, iterations

    def fit(self, train: sp.csr_matrix) -> "BiasBaseline":
        coo = train.tocoo()
        u, i, r = coo.row, coo.col, coo.data.astype(np.float64)
        n_users, n_items = train.shape
        self.mu = float(r.mean())
        self.bu = np.zeros(n_users)
        self.bi = np.zeros(n_items)
        n_i = np.bincount(i, minlength=n_items)
        n_u = np.bincount(u, minlength=n_users)
        for _ in range(self.iterations):
            self.bi = np.bincount(i, weights=r - self.mu - self.bu[u], minlength=n_items) / (self.reg_item + n_i)
            self.bu = np.bincount(u, weights=r - self.mu - self.bi[i], minlength=n_users) / (self.reg_user + n_u)
        return self

    def predict(self, users: np.ndarray, items: np.ndarray) -> np.ndarray:
        return (self.mu + self.bu[users] + self.bi[items]).astype(np.float32)