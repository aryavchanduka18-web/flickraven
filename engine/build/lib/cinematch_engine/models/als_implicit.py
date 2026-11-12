"""Implicit ALS (spec section 5, model 6): weighted alternating least squares
(Hu, Koren and Volinsky, 2008), trained with the `implicit` library.

Every (user, film) pair has a preference p = 1 if there is a positive signal, else 0, and a
confidence c = 1 + alpha * w, where w is the signal strength (offline: rating - 6 for ratings >= 7,
so a 10/10 counts more than a 7/10; live: the event weights). The model finds user vectors x and
film vectors y minimizing  sum c (p - x.y)^2 + lambda (|x|^2 + |y|^2)  by alternating closed-form
solves. Score = x_user . y_film.

Fold-in: with the film vectors fixed, a user's vector has the closed form
    x = (Y^T Y + Y^T (C_u - I) Y + lambda I)^-1  Y^T C_u p_u
which only needs the films that user interacted with.
"""
import numpy as np
import scipy.sparse as sp
from implicit.als import AlternatingLeastSquares

POSITIVE_MIN, NEUTRAL = 7, 6


def implicit_strength(train: sp.csr_matrix) -> sp.csr_matrix:
    """Offline signal strength from ratings: rating - 6 for ratings >= 7, nothing otherwise."""
    w = train.copy().astype(np.float32)
    w.data = np.where(w.data >= POSITIVE_MIN, w.data - NEUTRAL, 0).astype(np.float32)
    w.eliminate_zeros()
    return w


class ImplicitALS:
    def __init__(self, factors: int = 64, regularization: float = 0.05, alpha: float = 10.0,
                 iterations: int = 15, seed: int = 42):
        self.factors, self.reg, self.alpha, self.iterations, self.seed = factors, regularization, alpha, iterations, seed

    def fit(self, strength: sp.csr_matrix) -> "ImplicitALS":
        conf = strength.copy()
        conf.data = 1.0 + self.alpha * conf.data            # confidence c = 1 + alpha * w
        model = AlternatingLeastSquares(factors=self.factors, regularization=self.reg,
                                        iterations=self.iterations, random_state=self.seed,
                                        use_gpu=False, calculate_training_loss=False)
        model.fit(conf.tocsr(), show_progress=False)
        self.model = model
        self.X = np.asarray(model.user_factors, dtype=np.float32)
        self.Y = np.asarray(model.item_factors, dtype=np.float32)
        self.YtY = self.Y.T @ self.Y
        return self

    def score(self, users: np.ndarray) -> np.ndarray:
        return (self.X[users] @ self.Y.T).astype(np.float32)

    def fold_in(self, items: np.ndarray, strength: np.ndarray) -> np.ndarray:
        """User vector from that user's signals only, film vectors fixed (closed form above)."""
        c = 1.0 + self.alpha * strength.astype(np.float64)
        Yu = self.Y[items].astype(np.float64)
        A = self.YtY + (Yu.T * (c - 1.0)) @ Yu + self.reg * np.eye(self.factors)
        b = Yu.T @ c                                          # p = 1 on the user's films
        return np.linalg.solve(A, b).astype(np.float32)