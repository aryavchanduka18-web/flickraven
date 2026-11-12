"""The "New Releases For You" Home row (films only, a separate row, Top Picks unchanged).

Why: the recall experiments (work/candidate-recall/experiments-2-2026-11-12.md, section E) found that Top Picks shows
only 1 to 4% of the recent films a person goes on to like, while a separate row of the best recent films, ranked by the
same hybrid score, shows 11 to 16% of them (+0.10 to +0.12 NDCG@10 within recent films, about 9 standard errors),
with little overlap with Top Picks. MovieLens cannot judge Hindi or other Indian films, series, anime or films
without MovieLens data, so the first version is films only, and whether personal ranking or plain popularity is better
is for real clicks and likes to decide (every title in the row carries the usual row tracking, source `rail:recent_for_you`).

Pure function over the catalogue and the per-film hybrid score the Home route already has. No new model, no change to
Top Picks or to any score.
"""
from __future__ import annotations

import numpy as np

RECENT_YEARS = 3          # this year and the two before it
SIZE = 20
MIN_ROWS = 8              # fewer than this and the row is not shown
KEY = "recent_for_you"
TITLE = "New Releases For You"
REASON = {"code": KEY, "source": "hybrid", "share": 0, "text": "A recent release that fits your taste"}


def recent_rail(cat, rail_scores, taken: set[int], skip: set[int], this_year: int,
                size: int = SIZE, min_rows: int = MIN_ROWS) -> dict | None:
    """The best films released in the last RECENT_YEARS years by hybrid score, in the Home plan's rail format.

    rail_scores: one hybrid score per catalogue row, -inf for films the person has already acted on.
    taken: rows already in the hero or another row (a title is shown once on the page).
    skip: rows the person hid ("Not interested").
    """
    first = this_year - (RECENT_YEARS - 1)      # a year-only filter: films dated after this year (upcoming) are left out
    scores = np.asarray(rail_scores, dtype=float)
    mask = np.isfinite(scores) & (np.asarray(cat.year, dtype=float) >= first) & (np.asarray(cat.year, dtype=float) <= this_year) & (np.asarray(cat.kind) == "movie")
    for r in set(taken) | set(skip):
        mask[int(r)] = False
    idx = np.nonzero(mask)[0]
    if len(idx) < min_rows:
        return None
    order = idx[np.argsort(-scores[idx], kind="stable")][:size]
    return {"key": KEY, "title": TITLE, "source": "hybrid", "rows": [int(r) for r in order], "reason": REASON, "scored": {}}


def insert_after_top_picks(rails: list[dict], row: dict | None) -> list[dict]:
    """Put the new row straight after Top Picks (first place when Top Picks is missing). Returns a new list."""
    if row is None:
        return list(rails)
    at = next((i + 1 for i, r in enumerate(rails) if r["key"] == "top_picks"), 0)
    return [*rails[:at], row, *rails[at:]]
