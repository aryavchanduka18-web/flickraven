"""Your recommendation report: how the titles FlickRaven recommended turned out for you.

Only titles that were recommended to you (recommendation_logs) and that you rated AFTER they were first shown count.
A recommendation you never opened or rated is not a dislike and is ignored. Below MIN_RATED such titles the report
shows only the count, never percentages (a few ratings say nothing reliable). Recommendation logs are kept for 60 days
(app/services/cleanup.py), so the report covers roughly the last two months.
"""
from collections import Counter

MIN_RATED = 10
MIN_GENRE = 3          # a genre needs this many rated recommendations before it is called a strength or a miss
REASON_LABELS = {"genre": "wrong genre", "long": "too long", "slow": "too slow", "predictable": "too predictable",
                 "language": "not your language", "seen": "already seen", "similar": "too similar to others",
                 "unexpected": "not what you expected", "none": "just not for you"}


def summarize(rows: list[dict], reasons: Counter, min_rated: int = MIN_RATED) -> dict:
    """rows: one per recommended-then-rated title {match_pct (or None), rating 1-10, genres}."""
    n = len(rows)
    out = {"rated": n, "needed": min_rated, "ready": n >= min_rated}
    if not out["ready"]:
        return out
    positive = [r for r in rows if r["rating"] >= 7]
    predicted = [r["match_pct"] for r in rows if r["match_pct"] is not None]
    by_genre: dict[str, list[int]] = {}
    for r in rows:
        for g in r["genres"]:
            by_genre.setdefault(g, []).append(r["rating"])
    shares = {g: sum(x >= 7 for x in v) / len(v) for g, v in by_genre.items() if len(v) >= MIN_GENRE}
    misses = {g: sum(x <= 5 for x in v) / len(v) for g, v in by_genre.items() if len(v) >= MIN_GENRE}
    out.update({
        "positive_pct": round(100 * len(positive) / n),
        "avg_rating": round(sum(r["rating"] for r in rows) / n, 1),
        "avg_predicted_match": round(sum(predicted) / len(predicted)) if predicted else None,
        "best_genres": [g for g, s in sorted(shares.items(), key=lambda kv: (-kv[1], kv[0])) if s >= 0.6][:3],
        "missed_genres": [g for g, s in sorted(misses.items(), key=lambda kv: (-kv[1], kv[0])) if s >= 0.4][:3],
        "top_reasons": [REASON_LABELS.get(k, k) for k, _ in reasons.most_common(3)],
    })
    return out
