"""Explanations (spec section 6.11).

Rules: at most 3 reasons; a reason is shown only if its source gave at least 20% of the final score;
the evidence must be real (a film the user really liked, a real count of similar users).
"""
from dataclasses import dataclass

import numpy as np

MIN_SHARE, MAX_REASONS = 0.20, 3


@dataclass
class Reason:
    source: str
    code: str
    text: str
    share: float
    evidence: dict


def explain(item: int, shares: dict[str, float], liked: np.ndarray, content_sim: np.ndarray,
            item_neighbors: dict[int, dict[int, float]] | None, neighbor_votes: int | None,
            top_genre: str | None, title_of, preferences: str | None = None,
            reranked: bool = False, added_genre: str | None = None) -> list[Reason]:
    """shares: source -> share of the final score. liked: the user's liked film indices (rating >= 8,
    likes, onboarding picks). Returns at most 3 reasons, strongest first."""
    out: list[Reason] = []
    for source, share in sorted(shares.items(), key=lambda kv: -kv[1]):
        if share < MIN_SHARE:
            continue
        if source == "item_cf" and len(liked) and item_neighbors is not None:
            sims = item_neighbors.get(item, {})
            best = max(liked, key=lambda j: sims.get(int(j), 0.0))
            if sims.get(int(best), 0.0) > 0:
                out.append(Reason(source, "because_you_liked", f"Because you liked {title_of(best)}", share,
                                  {"film": int(best), "similarity": round(float(sims[int(best)]), 3)}))
        elif source == "content" and len(liked):
            top = np.asarray(liked)[np.argsort(-content_sim[item, liked])][:2]
            if content_sim[item, top[0]] > 0:
                names = " and ".join(title_of(t) for t in top)
                out.append(Reason(source, "similar_themes", f"Similar themes to {names}", share,
                                  {"films": [int(t) for t in top]}))
        elif source == "user_cf" and neighbor_votes:
            out.append(Reason(source, "similar_people", f"{neighbor_votes} people with similar taste rated this 8+",
                              share, {"neighbors": int(neighbor_votes)}))
        elif source in ("svd", "als") and top_genre:
            if not any(r.code == "fits_taste" for r in out):
                out.append(Reason(source, "fits_taste", "Fits the kind of films you rate highly", share,
                                  {"top_genre": top_genre}))
        elif source == "popularity":
            out.append(Reason(source, "loved_by_viewers", "Loved by FlickRaven viewers", share, {}))
        if len(out) == MAX_REASONS:
            break
    if preferences and len(out) < MAX_REASONS:
        out.append(Reason("preferences", "matches_preferences", f"Matches your interest in {preferences}", 0.0, {}))
    if reranked and added_genre and len(out) < MAX_REASONS:
        out.append(Reason("rerank", "adds_variety", f"Adds variety to your list ({added_genre})", 0.0,
                          {"genre": added_genre}))
    return out[:MAX_REASONS]