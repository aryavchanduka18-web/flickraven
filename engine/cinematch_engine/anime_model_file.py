"""Reading the anime model file (pipeline/anime_model.py writes it) and the one rule for which liked anime it knows.

Used by the site (api/app/services/recommender.py), the engine (OnlineEngine.anime_scores) and the real-user tier count
(pipeline/anime_tier_counts.py), so all three agree. Anything unexpected in the file means no model at all: the anime
lists then keep the earlier order instead of the site failing to start.
"""
from __future__ import annotations

import math

import numpy as np
import scipy.sparse as sp

TIERS = ("long", "mid", "short")
KNOWN_REF = "mid"        # a liked anime counts when its row in this model gives at least one vote (inside the catalog)


class BadModelFile(ValueError):
    """The file is valid JSON but not a usable anime model."""


def _vote(v) -> tuple[int, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise BadModelFile(f"a vote is not a [tmdb_id, weight] pair: {v!r}")
    b, w = v
    if isinstance(b, bool) or not isinstance(b, int) or isinstance(w, bool) or not isinstance(w, (int, float)):
        raise BadModelFile(f"a vote has the wrong types: {v!r}")
    if not math.isfinite(w):
        raise BadModelFile(f"a vote weight is not finite: {v!r}")
    return b, float(w)


def parse(data, tmdb_ids: list[int]) -> dict[str, sp.csr_matrix]:
    """{"long", "mid", "short": n x n csr over the catalog rows (row = the anime that votes)} from the file's JSON.
    Raises BadModelFile for any structural problem, and when a tier has no vote between two catalog titles."""
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        raise BadModelFile("no 'models' object")
    models = data["models"]
    row_of = {int(t): i for i, t in enumerate(tmdb_ids)}
    n = len(tmdb_ids)
    out = {}
    for name in TIERS:
        tier = models.get(name)
        if not isinstance(tier, dict):
            raise BadModelFile(f"model '{name}' is missing or not an object")
        rows, cols, vals = [], [], []
        for a, votes in tier.items():
            try:
                a = int(a)
            except (TypeError, ValueError):
                raise BadModelFile(f"model '{name}' has a title id that is not a number: {a!r}") from None
            if not isinstance(votes, list):
                raise BadModelFile(f"model '{name}', title {a}: votes are not a list")
            for v in votes:
                b, w = _vote(v)
                if a in row_of and b in row_of:
                    rows.append(row_of[a]); cols.append(row_of[b]); vals.append(w)
        if not vals:
            raise BadModelFile(f"model '{name}' has no vote between two catalog titles")
        out[name] = sp.csr_matrix((np.asarray(vals, dtype=np.float32), (rows, cols)), shape=(n, n))
    return out


def known_inputs(sims: dict[str, sp.csr_matrix], rows) -> list[int]:
    """The rows (liked anime) the model can use: their row in the reference model holds a vote. This number picks the
    tier (OnlineEngine.anime_scores), so the tier count must use it too."""
    ref = sims[KNOWN_REF]
    return [r for r in rows if ref.indptr[r + 1] > ref.indptr[r]]
