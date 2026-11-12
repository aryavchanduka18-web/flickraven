"""Surprise Me (spec section 6.9).

1. Unseen hybrid candidates with Match % >= 60 and community rating >= 6.5/10.
2. Main genre not in the user's top 3 genres.
3. Below the 70th popularity percentile.
4. Weighted random pick by Match %.
"""
import numpy as np

REASON = "Outside your usual genres, but people with similar taste rated it highly."


def surprise_me(candidates: np.ndarray, match_pct: np.ndarray, community: np.ndarray, main_genre: list,
                popularity_pct: np.ndarray, user_top_genres: set, rng: np.random.Generator):
    keep = [(c, m) for c, m in zip(candidates, match_pct)
            if m >= 60 and community[c] >= 6.5 and main_genre[c] not in user_top_genres and popularity_pct[c] < 70]
    if not keep:
        return None
    items, weights = zip(*keep)
    w = np.asarray(weights, dtype=float)
    return int(rng.choice(np.asarray(items), p=w / w.sum()))