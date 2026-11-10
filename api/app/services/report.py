"""MatchScore accountability: how the titles FlickRaven recommended turned out for you.

What counts (attribution rules, in this order):
- A recommendation is a title written to recommendation_logs for you (a row per time it was shown). The FIRST time it was
  shown is its exposure; the Match % printed then is the one compared with the outcome.
- An outcome is the FIRST rating you gave it AFTER that exposure, taken from the rating events (not the current rating,
  which you may have edited later) and never from an import (Letterboxd/IMDb imports are old opinions).
- A title you had already rated before its first exposure is left out: you knew it, it did not need our recommendation.
- Shown-but-not-opened, opened, marked watched and not-rated are separate steps. A title you never rated is NOT a
  dislike and is not in any percentage.
Logs are kept 60 days (app/services/cleanup.py), so the report covers roughly the last two months.

Statistics rules: nothing below MIN_RATED rated recommendations; a Match % range is only judged from MIN_BUCKET ratings
and only quoted in a sentence from MIN_STATEMENT; genres need MIN_GENRE; every percentage comes with its count and a 95%
Wilson interval. Positive = rated 7 or more. This is ranking quality (do higher Match % get better ratings?), not a
claim that the Match % is a calibrated probability.
"""
from __future__ import annotations

import math
from collections import Counter

MIN_RATED = 10
MIN_BUCKET = 5
MIN_STATEMENT = 10
MIN_GENRE = 3
MIN_TREND = 20
POSITIVE = 7
BUCKETS = [(0, 60, "Under 60%"), (60, 70, "60-70%"), (70, 80, "70-80%"), (80, 90, "80-90%"), (90, 101, "90% and up")]
REASON_LABELS = {"genre": "wrong genre", "long": "too long", "slow": "too slow", "predictable": "too predictable",
                 "language": "not your language", "seen": "already seen", "similar": "too similar to others",
                 "unexpected": "not what you expected", "none": "just not for you"}
FEEDBACK = {"exactly": "Exactly what I wanted", "not_usual": "Good, not my usual taste", "too_slow": "Too slow",
            "too_predictable": "Too predictable", "wrong_genre": "Wrong genre", "not_expected": "Not what I expected"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[int, int]:
    """95% interval for a share, in whole percent."""
    if n == 0:
        return 0, 0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * max(0, centre - half)), round(100 * min(1, centre + half))


def _share(rows: list[dict]) -> dict:
    n = len(rows)
    k = sum(r["rating"] >= POSITIVE for r in rows)
    lo, hi = wilson(k, n)
    return {"n": n, "positive": k, "positive_pct": round(100 * k / n) if n else None, "low": lo, "high": hi,
            "avg_rating": round(sum(r["rating"] for r in rows) / n, 1) if n else None}


def bucket_of(match: int | None) -> str | None:
    if match is None:
        return None
    for lo, hi, label in BUCKETS:
        if lo <= match < hi:
            return label
    return None


def summarize(shown: list[dict], reasons: Counter | None = None, feedback: Counter | None = None) -> dict:
    """shown: one per recommended title {match_pct, rating (first rating after exposure, or None), opened, watched,
    known_before, shown_at, surface, genres}. known_before titles are ignored everywhere."""
    reasons, feedback = reasons or Counter(), feedback or Counter()
    shown = [r for r in shown if not r.get("known_before")]
    rated = [r for r in shown if r["rating"] is not None]
    out = {"shown": len(shown), "opened": sum(bool(r["opened"]) for r in shown), "watched": sum(bool(r["watched"]) for r in shown),
           "rated": len(rated), "needed": MIN_RATED, "ready": len(rated) >= MIN_RATED,
           "positive_threshold": POSITIVE, "log_days": 60}
    if not out["ready"]:
        return out
    out.update(_share(rated))
    predicted = [r["match_pct"] for r in rated if r["match_pct"] is not None]
    out["avg_predicted_match"] = round(sum(predicted) / len(predicted)) if predicted else None
    out["rated_without_match"] = len(rated) - len(predicted)

    buckets = []
    for lo, hi, label in BUCKETS:
        rows = [r for r in rated if r["match_pct"] is not None and lo <= r["match_pct"] < hi]
        s = _share(rows) if rows else {"n": 0, "positive": 0, "positive_pct": None, "low": 0, "high": 0, "avg_rating": None}
        buckets.append({"label": label, **s, "enough": s["n"] >= MIN_BUCKET})
    out["buckets"] = buckets
    out["statements"] = [f"When we predicted {b['label']} match, {b['positive_pct']}% of the {b['n']} you rated got {POSITIVE} or more "
                         f"(plausibly {b['low']}-{b['high']}%)." for b in buckets if b["n"] >= MIN_STATEMENT]
    enough = [b for b in buckets if b["enough"]]
    out["ranking_note"] = ("Higher Match % ranges have been rated higher." if len(enough) >= 2 and enough[-1]["positive_pct"] > enough[0]["positive_pct"]
                           else "Not enough ratings across Match % ranges yet to say whether higher Match % means better ratings."
                           if len(enough) < 2 else "Higher Match % ranges have not been rated higher so far.")

    by_genre: dict[str, list[int]] = {}
    for r in rated:
        for g in r["genres"]:
            by_genre.setdefault(g, []).append(r["rating"])
    rows = [(g, len(v), sum(x >= POSITIVE for x in v) / len(v), sum(x <= 5 for x in v) / len(v)) for g, v in by_genre.items() if len(v) >= MIN_GENRE]
    out["best_genres"] = [{"genre": g, "n": n, "positive_pct": round(100 * p)} for g, n, p, _ in sorted(rows, key=lambda x: (-x[2], -x[1], x[0])) if p >= 0.6][:3]
    out["missed_genres"] = [{"genre": g, "n": n, "low_pct": round(100 * m)} for g, n, _, m in sorted(rows, key=lambda x: (-x[3], -x[1], x[0])) if m >= 0.4][:3]

    by_surface: dict[str, list[dict]] = {}
    for r in rated:
        by_surface.setdefault(r["surface"] or "other", []).append(r)
    out["surfaces"] = [{"surface": s, **_share(v)} for s, v in sorted(by_surface.items()) if len(v) >= MIN_BUCKET]

    if len(rated) >= MIN_TREND:
        ordered = sorted(rated, key=lambda r: r["shown_at"])
        half = len(ordered) // 2
        first, second = _share(ordered[:half]), _share(ordered[half:])
        out["trend"] = {"earlier": first, "later": second}
    else:
        out["trend"] = None
    out["top_reasons"] = [{"reason": REASON_LABELS.get(k, k), "n": n} for k, n in reasons.most_common(3)]
    out["feedback"] = [{"key": k, "label": FEEDBACK.get(k, k), "n": n} for k, n in feedback.most_common()]
    return out
