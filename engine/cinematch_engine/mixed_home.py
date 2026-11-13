"""Mixed films, series and anime for the Home hero and the first Top Picks (switched off unless MIXED_HOME is on).

The three rankings stay separate: a 0.85 from the film hybrid does not mean what a 0.85 from the anime ranker means,
and there are no held-out series or anime ratings to calibrate them against. So nothing here compares raw scores.
Each candidate is turned into the share of its OWN list that it beats (1.0 = best of its list), and a lane other than
films counts only as much as the evidence this person has given for it (liked and disliked titles of that format).

`compose` then picks greedily with diminishing returns, so a format, a language or a genre cannot run away with the
page, and a title from a lane enters only if it clears a quality floor in its own list. There are no fixed quotas: a
person with no anime history gets exactly the film list, and nobody gets a weak title just to fill a share.
"""
from __future__ import annotations

import numpy as np

FLOOR = 0.6            # a series or anime must beat 60% of its own candidate list to be eligible
MIN_WEIGHT = 0.25      # below this much evidence for a format, that format is not mixed in at all
FORMAT_DECAY = 0.85    # each title already picked from a format makes the next one of it worth 15% less
LANG_DECAY = 0.92
GENRE_DECAY = 0.94


def lane_weight(positive: int, negative: int) -> float:
    """How much to trust a format for this person, 0..1. Needs about 12 liked titles for full weight, and is cut by the
    share they disliked: 50 liked and 40 disliked is not an anime fan."""
    total = positive + negative
    if positive <= 0 or total <= 0:
        return 0.0
    return min(1.0, positive / 12.0) * (positive / total)


def percentile(scores: list[float]) -> list[float]:
    """Share of the list each score beats, 1.0 for the best, in the input order."""
    n = len(scores)
    if n == 0:
        return []
    order = np.argsort(np.argsort(-np.asarray(scores, dtype=float)))      # 0 = best
    return [1.0 - float(r) / n for r in order]


def compose(lanes: dict[str, list[tuple[int, float]]], weights: dict[str, float], k: int, language: dict[int, str],
            genres: dict[int, list[str]], floor: float = FLOOR) -> list[tuple[int, str]]:
    """lanes: format -> [(row, score)] best first, e.g. {"movie": [...], "anime": [...], "series": [...]}.
    weights: format -> evidence weight (movie is always 1.0). Returns up to k (row, format), best first."""
    pool: list[tuple[float, int, str]] = []
    for fmt, items in lanes.items():
        w = 1.0 if fmt == "movie" else weights.get(fmt, 0.0)
        if fmt != "movie" and w < MIN_WEIGHT:
            continue
        pct = percentile([s for _, s in items])
        for (row, _), p in zip(items, pct):
            if fmt != "movie" and p < floor:
                continue
            pool.append((p * (1.0 if fmt == "movie" else 0.5 + 0.5 * w), row, fmt))
    picked: list[tuple[int, str]] = []
    count_fmt: dict[str, int] = {}
    count_lang: dict[str, int] = {}
    count_genre: dict[str, int] = {}
    taken: set[int] = set()
    while pool and len(picked) < k:
        def value(c):
            v, row, fmt = c
            v *= FORMAT_DECAY ** count_fmt.get(fmt, 0) if fmt != "movie" else 1.0
            v *= LANG_DECAY ** count_lang.get(language.get(row, ""), 0)
            for g in genres.get(row, [])[:2]:
                v *= GENRE_DECAY ** count_genre.get(g, 0)
            return v
        best = max((c for c in pool if c[1] not in taken), key=value, default=None)
        if best is None:
            break
        _, row, fmt = best
        picked.append((row, fmt))
        taken.add(row)
        count_fmt[fmt] = count_fmt.get(fmt, 0) + 1
        count_lang[language.get(row, "")] = count_lang.get(language.get(row, ""), 0) + 1
        for g in genres.get(row, [])[:2]:
            count_genre[g] = count_genre.get(g, 0) + 1
    return picked
