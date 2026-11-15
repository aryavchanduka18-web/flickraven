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
    """lanes: format -> [(row, score)] best first, e.g. {"movie": [...], "anime": [...], "series": [...]}. Only the ORDER
    of a lane counts (its rank share), never the score. weights: format -> evidence weight (movie is always 1.0).
    Returns up to k (row, format), best first."""
    pool: list[tuple[float, int, str]] = []
    for fmt, items in lanes.items():
        w = 1.0 if fmt == "movie" else weights.get(fmt, 0.0)
        if fmt != "movie" and w < MIN_WEIGHT:
            continue
        n = len(items)
        # Rank share from the lane's own order (best first), NOT recomputed from raw scores, so a lane that was already
        # put in fresh-first order for Home keeps that order here.
        for i, (row, _) in enumerate(items):
            p = 1.0 - i / n
            if fmt != "movie" and p < floor:
                continue
            pool.append((p * (1.0 if fmt == "movie" else 0.5 + 0.5 * w), row, fmt))
    picked: list[tuple[int, str]] = []
    count_fmt: dict[str, int] = {}
    count_lang: dict[str, int] = {}
    count_genre: dict[str, int] = {}
    taken: set[int] = set()
    def family(fmt):                                  # anime and anime_film count as one format, all series lanes as one
        return "anime" if fmt.startswith("anime") else "series" if fmt.endswith("_series") else fmt
    while pool and len(picked) < k:
        def value(c):
            v, row, fmt = c
            v *= FORMAT_DECAY ** count_fmt.get(family(fmt), 0) if fmt != "movie" else 1.0
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
        count_fmt[family(fmt)] = count_fmt.get(family(fmt), 0) + 1
        count_lang[language.get(row, "")] = count_lang.get(language.get(row, ""), 0) + 1
        for g in genres.get(row, [])[:2]:
            count_genre[g] = count_genre.get(g, 0) + 1
    return picked


STRONG_FAN_WEIGHT = 0.5   # about 6+ liked anime with few dislikes
HERO_FORMAT_CAP = 3       # films always keep at least 2 of the 5 hero slides


def hero_target(liked_format: int, liked_films: int, weight: float, hero: int = 5, cap: int = HERO_FORMAT_CAP) -> int:
    """How many hero slides a strong fan of a format (anime) should get: their share of liked titles in that format times
    the hero size, rounded, at most `cap`. 0 below STRONG_FAN_WEIGHT, so casual fans and film-only people are unchanged.
    50 liked anime and 10 liked films: 3 of 5. 12 and 12: 3. 6 and 30: 1."""
    if weight < STRONG_FAN_WEIGHT or liked_format <= 0:
        return 0
    share = liked_format / (liked_format + max(liked_films, 0))
    return min(cap, int(np.floor(hero * share + 0.5)))


def lift_in_hero(picked: list[tuple[int, str]], lanes: dict[str, list[tuple[int, float]]], fmts: tuple[str, ...],
                 target: int, hero: int = 5, floor: float = FLOOR) -> list[tuple[int, str]]:
    """Make sure the first `hero` places hold at least `target` titles of `fmts`. Candidates are taken in order from the
    rest of `picked`, then from the lanes themselves, and only above the quality `floor` of their own list (fresh-first
    order is kept, so stale titles come last). They replace the lowest FILM places in the hero; those films move to the
    front of the rest, so nothing is lost. Series slides are never displaced. Returns the new list."""
    head, rest = list(picked[:hero]), list(picked[hero:])
    need = target - sum(1 for _, f in head if f in fmts)
    if need <= 0:
        return list(picked)
    taken = {r for r, _ in picked}
    cands = [x for x in rest if x[1] in fmts]
    extra = []
    for fmt in fmts:
        items = lanes.get(fmt, [])
        n = len(items)
        extra += [(1.0 - i / n, row, fmt) for i, (row, _) in enumerate(items) if row not in taken and 1.0 - i / n >= floor]
    cands += [(row, fmt) for _, row, fmt in sorted(extra, key=lambda c: -c[0])]
    seen, add = set(), []
    for row, fmt in cands:
        if row not in seen:
            seen.add(row)
            add.append((row, fmt))
        if len(add) == need:
            break
    film_slots = [i for i in range(len(head) - 1, -1, -1) if head[i][1] == "movie"][:len(add)]
    add = add[:len(film_slots)]
    displaced = [head[i] for i in film_slots]
    for i, x in zip(film_slots, add):
        head[i] = x
    added = set(add)
    return head + displaced + [x for x in rest if x not in added]
