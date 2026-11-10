"""How taste changes over time: the genres of the titles a person liked or rated 7+, month by month.

Only real activity counts (a rating of 7+ or a like, dated by when it was made). A change is described only when
both the earlier and the recent window hold at least MIN_WINDOW titles, so two ratings never become a "trend".
"""
from collections import Counter

MIN_WINDOW = 5
MONTHS = 6


def by_month(events: list[tuple[str, list[str]]]) -> list[dict]:
    """events: (YYYY-MM, genres of one liked title). -> [{month, titles, top: [{genre, titles, share}]}], oldest first."""
    months: dict[str, list[list[str]]] = {}
    for month, genres in events:
        months.setdefault(month, []).append(genres)
    out = []
    for month in sorted(months)[-MONTHS:]:
        c = Counter(g for genres in months[month] for g in set(genres))
        n = len(months[month])
        out.append({"month": month, "titles": n, "top": [{"genre": g, "titles": k, "share": round(k / n, 2)} for g, k in c.most_common(3)]})
    return out


def shift(events: list[tuple[str, list[str]]]) -> dict | None:
    """Earlier vs recent: the genre whose share of liked titles rose the most, and the one that fell the most.
    The recent window is the latest month with activity and the one before it; everything older is "earlier"."""
    months = sorted({m for m, _ in events})
    if len(months) < 2:
        return None
    recent_months = set(months[-2:])
    recent = [g for m, g in events if m in recent_months]
    earlier = [g for m, g in events if m not in recent_months]
    if len(recent) < MIN_WINDOW or len(earlier) < MIN_WINDOW:
        return None

    def share(rows):
        c = Counter(g for genres in rows for g in set(genres))
        return {g: k / len(rows) for g, k in c.items()}
    a, b = share(earlier), share(recent)
    diff = {g: b.get(g, 0) - a.get(g, 0) for g in set(a) | set(b)}
    up, down = max(diff, key=lambda g: (diff[g], g)), min(diff, key=lambda g: (diff[g], g))
    return {"earlier_titles": len(earlier), "recent_titles": len(recent),
            "rising": {"genre": up, "from": round(a.get(up, 0), 2), "to": round(b.get(up, 0), 2)} if diff[up] >= 0.1 else None,
            "falling": {"genre": down, "from": round(a.get(down, 0), 2), "to": round(b.get(down, 0), 2)} if diff[down] <= -0.1 else None}
