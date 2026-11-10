"""Model Agreement for one title: how each model ranks it for this user, and how much they agree.

Every number comes from the live engine. For each source the film's score is turned into a percentile
among all films that source can score for this user (100 = its top film). Sources are grouped in user
words: Collaborative (SVD, item CF, user CF), Content (TF-IDF and labels), Behavioral (implicit ALS),
Popularity (what everyone rates well; it carries real weight for new users, so it is shown too).
Hybrid is the calibrated Match %. Agreement = 100 x (1 - 2 x standard deviation of the source
percentiles that count for this user's stage), so identical rankings give 100 and a split between the
very top and the very bottom gives 0. It needs at least two sources that score the film.
"""
import numpy as np

GROUPS = [
    ("collaborative", "Collaborative", ("svd", "item_cf", "user_cf")),
    ("content", "Content", ("content",)),
    ("behavioral", "Behavioral", ("als",)),
    ("popularity", "Popularity", ("popularity",)),
]
TECHNICAL = {
    "svd": "SVD matrix factorization (explicit ratings)",
    "item_cf": "Item-based collaborative filtering",
    "user_cf": "User-based collaborative filtering",
    "content": "Content similarity: TF-IDF of plot and keywords, plus genres, people, studio, language",
    "als": "ALS on implicit feedback (views, likes, list, watched)",
    "popularity": "Popularity baseline (Bayesian average)",
}
HIGH, MODERATE = 75, 50
# How each group sounds when it is the most and the least positive one.
FOR = {
    "collaborative": ("people with similar taste rate it highly", "people with similar taste are less keen"),
    "content": ("it is close to films you like", "it is less like the films you like"),
    "behavioral": ("it fits what you watch and save", "what you watch and save points elsewhere"),
    "popularity": ("it is widely liked", "it is less widely known"),
}


def informative(vals: np.ndarray) -> bool:
    """A source that gives every film the same score (e.g. item CF when all of a new user's ratings are equal)
    says nothing about this film; it is left out instead of being read as 'ranks it last'."""
    return len(vals) > 1 and float(np.ptp(vals)) > 1e-9


def percentiles(scores: dict[str, np.ndarray], row: int) -> dict[str, float]:
    """Mid-rank percentile: films with the same score share the middle of their rank range."""
    out = {}
    for s, v in scores.items():
        ok = np.isfinite(v)
        if ok[row] and informative(v[ok]):
            vals = v[ok]
            less, equal = float((vals < v[row]).sum()), float((vals == v[row]).sum())
            out[s] = (less + (equal + 1) / 2) / float(len(vals))
    return out


def label(agreement: int | None) -> str | None:
    if agreement is None:
        return None
    return "High" if agreement >= HIGH else "Moderate" if agreement >= MODERATE else "Low"


def sentence(agreement: int | None, groups: list[dict]) -> str:
    known = [g for g in groups if g["score"] is not None]
    if agreement is None or len(known) < 2:
        return "Only one kind of model can judge this film for you so far. Rate a few more films to get a fuller picture."
    best, worst = max(known, key=lambda g: g["score"]), min(known, key=lambda g: g["score"])
    mean = sum(g["score"] for g in known) / len(known)
    if agreement >= HIGH:
        return ("The models agree: this looks like a strong match for you." if mean >= 70 else
                "The models agree this is probably not your kind of film." if mean < 40 else
                "The models agree this is a reasonable match, not a standout.")
    if best["score"] - worst["score"] < 25:
        return "The models see it a little differently, so treat the match as a guide."
    return f"{FOR[best['key']][0].capitalize()}, but {FOR[worst['key']][1]}."


def confidence(engine, st, row: int, match_pct: int | None, scores: dict | None = None) -> dict:
    scores = scores or engine.scores(st)
    pct = percentiles(scores, row)
    weights = engine.weights[st.stage]
    counted = {s: p for s, p in pct.items() if weights.get(s, 0) > 0}
    groups = []
    for key, name, sources in GROUPS:
        parts = [s for s in sources if s in counted]
        score = None
        if parts:
            w = np.array([weights[s] for s in parts])
            score = int(round(100 * float(np.dot(w, [counted[s] for s in parts]) / w.sum())))
        groups.append({"key": key, "label": name, "score": score})
    agreement = (int(round(100 * max(0.0, 1 - 2 * float(np.std(list(counted.values()))))))
                 if len(counted) >= 2 else None)
    return {
        "agreement": agreement, "label": label(agreement), "sentence": sentence(agreement, groups),
        "groups": groups + [{"key": "hybrid", "label": "Hybrid", "score": match_pct}], "stage": st.stage,
        "technical": [{"source": s, "model": TECHNICAL[s], "percentile": int(round(100 * p)),
                       "weight": round(float(weights.get(s, 0)), 3), "counted": s in counted}
                      for s, p in sorted(pct.items(), key=lambda kv: -weights.get(kv[0], 0))],
    }


def agreement_all(engine, st, scores: dict) -> np.ndarray:
    """Agreement for every catalog film at once (NaN where fewer than two weighted sources score it), the
    same formula as confidence(), for the labels on cards."""
    weights = engine.weights[st.stage]
    cols = []
    for s, v in scores.items():
        if weights.get(s, 0) <= 0:
            continue
        ok = np.isfinite(v)
        if not informative(v[ok]):
            continue
        pct = np.full(len(v), np.nan)
        vals = v[ok]
        srt = np.sort(vals)
        less = np.searchsorted(srt, vals, side="left")
        equal = np.searchsorted(srt, vals, side="right") - less
        pct[ok] = (less + (equal + 1) / 2) / ok.sum()       # mid-rank, as in percentiles()
        cols.append(pct)
    if len(cols) < 2:
        return np.full(engine.cat.n, np.nan)
    m = np.vstack(cols)
    n = np.isfinite(m).sum(axis=0)
    with np.errstate(invalid="ignore"):
        agree = np.round(100 * np.clip(1 - 2 * np.nanstd(m, axis=0), 0, 1))
    agree[n < 2] = np.nan
    return agree
