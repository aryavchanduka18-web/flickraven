"""Applies cinematch_engine.mixed_home to the Home plan (hero and the first Top Picks). Returns the plan unchanged for
anyone without enough liked series or anime, and always when MIXED_HOME is off."""
from __future__ import annotations

import numpy as np

from cinematch_engine.mixed_home import MIN_WEIGHT, compose, lane_weight

from app.services.anime_rows import is_anime_film

HERO, FIRST_PICKS, POOL = 5, 10, 150
FORMATS = ("anime", "series")
LABEL = {"anime": "anime", "series": "series"}


def anime_film_rows(cat) -> set[int]:
    """Japanese animated films: they are films in the catalogue, but for a person who likes anime they are anime."""
    return {r for r in range(len(cat.kind)) if cat.kind[r] == "movie" and is_anime_film(list(cat.genres[r]), cat.language[r])}


def evidence(engine, st, films: set[int] | None = None) -> dict[str, tuple[int, int]]:
    """(liked, disliked) counts per format: liked = rated 7+, liked, picked or saved; disliked = rated 5 or less or disliked.
    Anime counts anime series and Japanese animated films together."""
    kind = engine.cat.kind
    films = films if films is not None else anime_film_rows(engine.cat)
    liked = engine.engaged_rows(st)
    bad = {r for r, v in st.ratings.items() if v <= 5} | set(st.dislikes)
    is_a = lambda r: kind[r] == "anime" or r in films
    out = {"series": (sum(1 for r in liked if kind[r] == "series"), sum(1 for r in bad if kind[r] == "series"))}
    out["anime"] = (sum(1 for r in liked if is_a(r)), sum(1 for r in bad if is_a(r)))
    return out


def mix(engine, st, plan: dict, skip: set[int], stale: set[int] | None = None) -> dict:
    """`stale` are rows shown on earlier days: they go behind fresh ones in EVERY lane (films, series, anime), so the
    mix changes day to day like the rest of Home."""
    stale = stale or set()
    afilms = anime_film_rows(engine.cat)
    ev = evidence(engine, st, afilms)
    weights = {f: lane_weight(*ev[f]) for f in FORMATS}
    if max(weights.values()) < MIN_WEIGHT:
        return plan
    top = next((r for r in plan["rails"] if r["key"] == "top_picks"), None)
    if top is None:
        return plan
    cat = engine.cat
    pool = {e["row"]: e for e in plan["hero"]} | {row: top["scored"][row] for row in top["rows"] if row in top["scored"]}
    order = [e["row"] for e in plan["hero"]] + [row for row in top["rows"] if row in pool]
    fresh_first = lambda lane: [x for x in lane if x[0] not in stale] + [x for x in lane if x[0] in stale]
    rail = plan.get("rail_scores")
    split = weights["anime"] >= MIN_WEIGHT and rail is not None      # anime fan: Japanese animated films move from the film lane to their own
    lanes = {"movie": fresh_first([(row, float(pool[row]["score"])) for row in order if not (split and row in afilms)])}
    for fmt in FORMATS:
        if weights[fmt] >= MIN_WEIGHT:
            rows, scores = engine.kind_rank(st, fmt)
            lanes[fmt] = fresh_first([(int(r), float(s)) for r, s in list(zip(rows, scores))[:POOL] if int(r) not in skip])
    if split:                                    # Japanese animated films: ranked by the film hybrid, but they are anime here
        acted = {int(a) for a in engine.excluded(st)}
        cand = [r for r in afilms if r not in skip and r not in acted and np.isfinite(rail[r])]
        cand.sort(key=lambda r: -float(rail[r]))
        lanes["anime_film"] = fresh_first([(r, float(rail[r])) for r in cand[:POOL]])
        weights["anime_film"] = weights["anime"]
    rows_in = {row for items in lanes.values() for row, _ in items}
    picked = compose(lanes, weights, HERO + FIRST_PICKS, {r: cat.language[r] for r in rows_in}, {r: list(cat.genres[r]) for r in rows_in})
    if not any(f != "movie" for _, f in picked):
        return plan
    entry = {}
    for row, fmt in picked:
        entry[row] = pool[row] if fmt == "movie" else {"row": row, "score": dict(lanes[fmt])[row], "match_pct": None, "shares": {}, "format": "anime" if fmt == "anime_film" else fmt}
    chosen = [row for row, _ in picked]
    new_top = chosen[HERO:] + [row for row in top["rows"] if row not in set(chosen)]
    plan = dict(plan)
    plan["hero"] = [entry[row] for row in chosen[:HERO]]
    plan["rails"] = [dict(r, rows=new_top, scored=pool | {row: entry[row] for row in chosen[HERO:]}) if r is top else r for r in plan["rails"]]
    return plan


def reason(fmt: str) -> list[dict]:
    return [{"code": "cross_format", "source": "cross_format", "share": 0,
             "text": f"Based on the {LABEL.get(fmt, fmt)} you have rated highly"}]
