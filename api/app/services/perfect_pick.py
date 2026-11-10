"""The Perfect Pick: three titles from three answers (mood, time, familiar or adventurous).

The recommender does the ranking (hybrid score for films, series ranking for series); the answers only narrow the
list and decide how much novelty counts. Nothing here invents a title or a number.
"""
from dataclasses import dataclass

TIMES = {"short": "Under 90 minutes", "medium": "About 2 hours", "long": "Plenty of time", "series": "A series"}
ADVENTURES = ("familiar", "balanced", "adventurous")
SERIES_MAX_HOURS = 25          # "a series I can finish": 25 hours or less in total
FLOOR = {"familiar": 0.0, "balanced": 0.3, "adventurous": 0.35}       # lowest recommender percentile each style accepts


@dataclass
class Cand:
    id: int
    pct: float            # percentile of the user's score among the candidates, 0..1 (1 = best)
    novelty: float        # 0..1, higher = less well known
    role: str = "close"   # close | step_out | surprise


def choose(cands: list[Cand], adventure: str, k: int = 3) -> list[Cand]:
    """Familiar: the best by recommender score. Adventurous: score and novelty together (never below the floor).
    Balanced: the best two by score and one surprise (the most novel title that still scores well)."""
    if adventure not in ADVENTURES:
        raise ValueError(adventure)
    pool = sorted(cands, key=lambda c: (-c.pct, c.id))
    if adventure == "familiar":
        return [Cand(c.id, c.pct, c.novelty, "close") for c in pool[:k]]
    if adventure == "adventurous":
        eligible = [c for c in pool if c.pct >= FLOOR["adventurous"]] or pool
        best = sorted(eligible, key=lambda c: (-(0.55 * c.pct + 0.45 * c.novelty), c.id))[:k]
        return [Cand(c.id, c.pct, c.novelty, "step_out") for c in best]
    top = pool[:k - 1]
    rest = [c for c in pool[k - 1:] if c.pct >= FLOOR["balanced"]] or pool[k - 1:]
    surprise = sorted(rest, key=lambda c: (-c.novelty, -c.pct, c.id))[:1]
    return [Cand(c.id, c.pct, c.novelty, "close") for c in top] + [Cand(c.id, c.pct, c.novelty, "surprise") for c in surprise]


def pct_of(values: list[float]) -> list[float]:
    """Percentile of each value within the list (the largest is 1.0)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    for rank, i in enumerate(order, 1):
        out[i] = rank / n
    return out


def reasons(role: str, mood: str, mood_exact: bool, time_text: str, match_pct: int | None) -> list[dict]:
    """Plain sentences, each one something the code actually checked."""
    def r(code: str, text: str) -> dict:
        return {"code": code, "source": "perfect_pick", "text": text, "share": 0.0, "anchor_movie_id": None}
    out = [r("pp_mood", f"Fits \"{mood.lower()}\"" if mood_exact else f"Not a perfect fit for \"{mood.lower()}\": the closest we found"),
           r("pp_time", time_text)]
    if role == "surprise":
        out.append(r("pp_surprise", "The one surprise: less well known, still scores well for you"))
    elif role == "step_out":
        out.append(r("pp_step_out", "A step outside your usual picks: less well known, still on your taste"))
    elif match_pct is not None:
        out.append(r("pp_taste", f"{match_pct}% match with your taste"))
    else:
        out.append(r("pp_taste", "High in your own ranking of series"))
    return out
