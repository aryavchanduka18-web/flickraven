"""Popularity model (spec section 5, model 1): Bayesian average.

score = v / (v + m) * R + m / (v + m) * C
R = the film's mean rating, v = its number of ratings, C = the global mean, m = a minimum-count
constant. A film with few ratings is pulled toward the global mean, so one 10/10 rating cannot
put an unknown film at the top.
"""
import numpy as np
import scipy.sparse as sp


def bayesian_average(sums: np.ndarray, counts: np.ndarray, global_mean: float, m: float) -> np.ndarray:
    counts = counts.astype(np.float64)
    mean = np.divide(sums, counts, out=np.full_like(counts, global_mean), where=counts > 0)
    return (counts / (counts + m) * mean + m / (counts + m) * global_mean).astype(np.float32)


class PopularityModel:
    def __init__(self, m: float):
        self.m = m

    def fit(self, train: sp.csr_matrix) -> "PopularityModel":
        csc = train.tocsc()
        counts = np.diff(csc.indptr)
        sums = np.asarray(csc.sum(axis=0)).ravel()
        self.global_mean = float(train.data.mean())
        self.scores = bayesian_average(sums, counts, self.global_mean, self.m)
        return self

    def score(self, users: np.ndarray) -> np.ndarray:
        return np.broadcast_to(self.scores, (len(users), len(self.scores))).copy()