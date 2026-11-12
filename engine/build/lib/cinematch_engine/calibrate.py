"""Match % (spec section 6.7): one-feature logistic regression per stage,
blend score -> probability that the user rates the film >= 7/10.
Match % = probability x 100, rounded, capped at 99. Values are not stretched."""
import numpy as np
from sklearn.linear_model import LogisticRegression


class MatchCalibrator:
    def __init__(self):
        self.models = {}

    def fit(self, stage: str, scores: np.ndarray, liked: np.ndarray) -> "MatchCalibrator":
        m = LogisticRegression(C=1e6)
        m.fit(scores.reshape(-1, 1), liked.astype(int))
        self.models[stage] = m
        return self

    def probability(self, stage: str, scores: np.ndarray) -> np.ndarray:
        return self.models[stage].predict_proba(np.asarray(scores).reshape(-1, 1))[:, 1]

    def match_pct(self, stage: str, scores: np.ndarray) -> np.ndarray:
        return np.minimum(np.round(self.probability(stage, scores) * 100), 99).astype(int)

    def params(self) -> dict:
        return {s: {"coef": float(m.coef_[0, 0]), "intercept": float(m.intercept_[0])} for s, m in self.models.items()}


def calibration_table(prob: np.ndarray, liked: np.ndarray, bins: int = 10) -> list[dict]:
    """Predicted vs observed share of liked films per probability bin (the calibration check)."""
    edges = np.quantile(prob, np.linspace(0, 1, bins + 1))
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (prob >= lo) & (prob <= hi)
        if sel.sum():
            rows.append({"predicted": float(prob[sel].mean()), "observed": float(liked[sel].mean()), "n": int(sel.sum())})
    return rows