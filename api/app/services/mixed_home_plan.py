"""Applies cinematch_engine.mixed_home to the Home plan (hero and the first Top Picks). Returns the plan unchanged for
anyone without enough liked series or anime, and always when MIXED_HOME is off."""
from __future__ import annotations

from cinematch_engine.mixed_home import MIN_WEIGHT, compose, lane_weight

HERO, FIRST_PICKS, POOL = 5, 10, 150
FORMATS = ("anime", "series")
LABEL = {"anime": "anime", "series": "series"}


def evidence(engine, st) -> dict[str, tuple[int, int]]:
    """(liked, disliked) counts per format: liked = rated 7+, liked, picked or saved; disliked = rated 5 or less or disliked."""
    kind = engine.cat.kind
    liked = engine.engaged_rows(st)
    bad = {r for r, v in st.ratings.items() if v <= 5} | set(st.dislikes)
    return {f: (sum(1 for r in liked if kind[r] == f), sum(1 for r in bad if kind[r] == f)) for f in FORMATS}


def mix(engine, st, plan: dict, skip: set[int]) -> dict:
    ev = evidence(engine, st)
    weights = {f: lane_weight(*ev[f]) for f in FORMATS}
    if max(weights.values()) < MIN_WEIGHT:
        return plan
    top = next((r for r in plan["rails"] if r["key"] == "top_picks"), None)
    if top is None:
        return plan
    cat = engine.cat
    pool = {e["row"]: e for e in plan["hero"]} | {row: top["scored"][row] for row in top["rows"] if row in top["scored"]}
    order = [e["row"] for e in plan["hero"]] + [row for row in top["rows"] if row in pool]
    lanes = {"movie": [(row, float(pool[row]["score"])) for row in order]}
    for fmt in FORMATS:
        if weights[fmt] >= MIN_WEIGHT:
            rows, scores = engine.kind_rank(st, fmt)
            lanes[fmt] = [(int(r), float(s)) for r, s in list(zip(rows, scores))[:POOL] if int(r) not in skip]
    rows_in = {row for items in lanes.values() for row, _ in items}
    picked = compose(lanes, weights, HERO + FIRST_PICKS, {r: cat.language[r] for r in rows_in}, {r: list(cat.genres[r]) for r in rows_in})
    if not any(f != "movie" for _, f in picked):
        return plan
    entry = {}
    for row, fmt in picked:
        entry[row] = pool[row] if fmt == "movie" else {"row": row, "score": dict(lanes[fmt])[row], "match_pct": None, "shares": {}, "format": fmt}
    chosen = [row for row, _ in picked]
    new_top = chosen[HERO:] + [row for row in top["rows"] if row not in set(chosen)]
    plan = dict(plan)
    plan["hero"] = [entry[row] for row in chosen[:HERO]]
    plan["rails"] = [dict(r, rows=new_top, scored=pool | {row: entry[row] for row in chosen[HERO:]}) if r is top else r for r in plan["rails"]]
    return plan


def reason(fmt: str) -> list[dict]:
    return [{"code": "cross_format", "source": "cross_format", "share": 0,
             "text": f"Based on the {LABEL.get(fmt, fmt)} you have rated highly"}]
