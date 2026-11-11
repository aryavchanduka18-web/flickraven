"""Titles the collaborative models cannot score (the "unavailable score" problem).

Item CF, user CF, SVD and ALS were trained on MovieLens only. A film that is not in MovieLens (most Hindi,
Tamil, Korean and recent films) has no learned factors, so those four sources return "unavailable" for it.
The blend used to add 0 for them, so for an established user (ALS weight 0.7) such a film could never score
above 0.1 and never appeared, however well it matched. "Unavailable" is not "scored low".

The fix, evaluated in pipeline/availability_calibration.py:
1. Blend only the sources that CAN score the film (content, popularity), dividing by their weights, so the
   score is a weighted average of the available percentiles, not a sum with zeros.
2. That average is not on the same scale as a MovieLens film's score (a single percentile spreads out to 0 and 1;
   an average of several shrinks toward the middle). So it is mapped onto the MovieLens films' scale by matching
   probabilities: both groups are calibrated to P(user rates it 7+) on held-out users (isotonic regression),
   and a content-only score s becomes the score a MovieLens film would need to have the same probability.
Nothing else changes: MovieLens films keep exactly the score they had.
"""
import json
from pathlib import Path

import numpy as np

STAGES = ("cold", "warming", "established")


def isotonic_arrays(iso) -> dict:
    """Breakpoints of a fitted sklearn IsotonicRegression: {"x": [...], "y": [...]}."""
    return {"x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]}


class AvailabilityMap:
    """Per stage: probability curve of MovieLens films on the blend scale ("known") and of films without
    collaborative factors on the renormalized-blend scale ("new")."""

    def __init__(self, curves: dict[str, dict[str, dict]]):
        self.curves = curves

    @classmethod
    def load(cls, path: Path) -> "AvailabilityMap | None":
        path = Path(path)
        if not path.exists():
            return None
        return cls(json.loads(path.read_text(encoding="utf-8"))["stages"])

    def map_unavailable(self, stage: str, renorm: np.ndarray) -> np.ndarray:
        """Scores (on the MovieLens films' scale) for films scored only by the sources that can score them."""
        c = self.curves.get(stage) or self.curves["warming"]      # a stage without its own fit uses warming's
        new_x, new_y = np.asarray(c["new"]["x"]), np.asarray(c["new"]["y"])
        known_x, known_y = np.asarray(c["known"]["x"]), np.asarray(c["known"]["y"])
        p = np.interp(renorm, new_x, new_y)                        # P(rated 7+) for this availability group
        # first score at which a MovieLens film reaches each probability level (inverse of the known curve)
        levels, first = np.unique(known_y, return_index=True)
        return np.interp(p, levels, known_x[first]).astype(np.float32)


def renormalized(percentiles: dict[str, np.ndarray], weights: dict[str, float], rows: np.ndarray) -> np.ndarray:
    """Weighted average, over the sources that scored each row, of those sources' percentiles (nan = unavailable)."""
    num = np.zeros(len(rows), dtype=np.float32)
    den = np.zeros(len(rows), dtype=np.float32)
    for s, w in weights.items():
        if not w or s not in percentiles:
            continue
        v = percentiles[s][rows]
        ok = np.isfinite(v)
        num[ok] += w * v[ok]
        den[ok] += w
    return np.where(den > 0, num / np.maximum(den, 1e-9), 0.0).astype(np.float32)
