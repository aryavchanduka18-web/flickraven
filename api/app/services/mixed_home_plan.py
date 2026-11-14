"""Applies cinematch_engine.mixed_home to the Home plan (hero and the first Top Picks). Returns the plan unchanged for
anyone without enough liked series or anime, and always when MIXED_HOME is off."""
from __future__ import annotations

import numpy as np

from cinematch_engine import lanes as lanes_mod
from cinematch_engine.mixed_home import MIN_WEIGHT, compose, lane_weight

HERO, FIRST_PICKS, POOL = 5, 10, 150
SERIES_FEEDS = lanes_mod.SERIES_LANES
LABEL = lanes_mod.LABEL
GROUPS = ("anime",) + lanes_mod.SERIES_LANES + lanes_mod.FILM_EXTRA_LANES
# Every lane has its own switch (setting HOME_LANES, a comma list of these names). A lane earns default-on status through
# its own evaluation (docs/unified-home-phase5-replay.md), not because another lane performed well.
ALL_LANES = ("anime",) + lanes_mod.SERIES_LANES + lanes_mod.FILM_EXTRA_LANES
DEFAULT_LANES = frozenset({"anime", "korean_series", "hollywood_series", "indian_series"})
STRICT_FILM_MIN_LIKED, STRICT_FILM_MIN_SHARE = 10, 0.5     # film lanes: 10+ liked in the lane AND over half of the person's liked films


def film_lane_gate(liked_in_lane: int, liked_films: int) -> bool:
    """Film lanes (Indian, international) open only for a real fan: 10+ liked titles in the lane AND over half of all the
    films the person likes. A few liked foreign films do not make a lane (they rank in the film list as before)."""
    return liked_in_lane >= STRICT_FILM_MIN_LIKED and liked_in_lane > STRICT_FILM_MIN_SHARE * max(liked_films, 1)


def enabled_lanes(spec: str) -> frozenset[str]:
    """HOME_LANES -> lane names; unknown names are ignored (a typo cannot switch on something else)."""
    return frozenset(n.strip() for n in spec.split(",") if n.strip() in ALL_LANES)


def active_lanes(settings) -> frozenset[str]:
    """The lanes switched on: HOME_MIX_DISABLED turns off everything; ANIME_HOME_MIX controls the anime lane on its own;
    MIXED_HOME controls the other lanes listed in HOME_LANES (series, films)."""
    if getattr(settings, "home_mix_disabled", False):
        return frozenset()
    lanes: set[str] = set()
    if getattr(settings, "anime_home_mix", False):
        lanes.add("anime")
    if getattr(settings, "mixed_home", False):
        lanes |= enabled_lanes(getattr(settings, "home_lanes", "")) - {"anime"}
    return frozenset(lanes)


def anime_film_rows(cat) -> set[int]:
    """Japanese animated films: they are films in the catalogue, but for a person who likes anime they are anime."""
    return {r for r, l in enumerate(lanes_mod.lane_of_rows(cat)) if l == "anime_film"}


def evidence(engine, st, films: set[int] | None = None) -> dict[str, tuple[int, int]]:
    """(liked, disliked) counts per lane group: liked = rated 7+, liked, picked or saved; disliked = rated 5 or less or
    disliked. Anime series and Japanese animated films count together as "anime"; each series lane and each extra film
    lane (Indian, international) counts on its own."""
    lane_of = lanes_mod.lane_of_rows(engine.cat)
    liked = engine.engaged_rows(st)
    bad = {r for r, v in st.ratings.items() if v <= 5} | set(st.dislikes)
    out = {g: [0, 0] for g in GROUPS}
    for i, rows in enumerate((liked, bad)):
        for r in rows:
            g = lanes_mod.group(lane_of[r])
            if g in out:
                out[g][i] += 1
    return {g: (v[0], v[1]) for g, v in out.items()}


def mix(engine, st, plan: dict, skip: set[int], stale: set[int] | None = None, lanes: frozenset[str] | set[str] = DEFAULT_LANES) -> dict:
    """`stale` are rows shown on earlier days: they go behind fresh ones in EVERY lane (films, series, anime), so the
    mix changes day to day like the rest of Home. Each lane counts as much as this person's evidence for it.
    `lanes` are the lanes switched on (HOME_LANES); a lane that is not in it never enters the page."""
    stale = stale or set()
    cat = engine.cat
    lane_of = lanes_mod.lane_of_rows(cat)
    ev = evidence(engine, st)
    weights = {g: lane_weight(*ev[g]) for g in GROUPS}
    liked_films = [r for r in engine.engaged_rows(st) if lane_of[r].endswith("_film")]
    for g in GROUPS:
        if g not in lanes:
            weights[g] = 0.0
        elif g in lanes_mod.FILM_EXTRA_LANES and not film_lane_gate(ev[g][0], len(liked_films)):
            weights[g] = 0.0                      # strict gate for film lanes: a real fan of that lane, not a person who liked a few
    if max(weights.values()) < MIN_WEIGHT:
        return plan
    top = next((r for r in plan["rails"] if r["key"] == "top_picks"), None)
    if top is None:
        return plan
    pool = {e["row"]: e for e in plan["hero"]} | {row: top["scored"][row] for row in top["rows"] if row in top["scored"]}
    order = [e["row"] for e in plan["hero"]] + [row for row in top["rows"] if row in pool]
    fresh_first = lambda lane: [x for x in lane if x[0] not in stale] + [x for x in lane if x[0] in stale]
    rail = plan.get("rail_scores")
    acted = {int(a) for a in engine.excluded(st)} if rail is not None else set()
    anime_on = weights["anime"] >= MIN_WEIGHT and rail is not None      # anime fan: animated Japanese films get their own lane

    def film_lane(name: str) -> list[tuple[int, float]]:
        """A film lane from the film hybrid's own scores (rail_scores), best first, for the rows of one taxonomy lane."""
        cand = [r for r in range(len(lane_of)) if lane_of[r] == name and r not in skip and r not in acted and np.isfinite(rail[r])]
        cand.sort(key=lambda r: -float(rail[r]))
        return fresh_first([(r, float(rail[r])) for r in cand[:POOL]])

    # Each film belongs to exactly ONE lane, so how it is presented never depends on which list happened to win it: films of
    # an active anime or film lane leave the base film list and are shown by their own lane.
    film_extras = {n for n in lanes_mod.FILM_EXTRA_LANES if rail is not None and weights[n] >= MIN_WEIGHT}
    own_lane = ({"anime_film"} if anime_on else set()) | film_extras
    lanes = {"movie": fresh_first([(row, float(pool[row]["score"])) for row in order if lane_of[row] not in own_lane])}
    w = {"anime_film": weights["anime"]}
    if weights["anime"] >= MIN_WEIGHT:
        rows, scores = engine.kind_rank(st, "anime")
        lanes["anime"] = fresh_first([(int(r), float(s)) for r, s in list(zip(rows, scores))[:POOL] if int(r) not in skip])
        w["anime"] = weights["anime"]
        if anime_on:
            lanes["anime_film"] = film_lane("anime_film")
    if any(weights[l] >= MIN_WEIGHT for l in SERIES_FEEDS):
        rows, scores = engine.kind_rank(st, "series")
        for name in SERIES_FEEDS:
            if weights[name] >= MIN_WEIGHT:
                got = [(int(r), float(s)) for r, s in zip(rows, scores) if lane_of[int(r)] == name and int(r) not in skip][:POOL]
                if got:
                    lanes[name] = fresh_first(got)
                    w[name] = weights[name]
    if rail is not None:
        for name in lanes_mod.FILM_EXTRA_LANES:
            if weights[name] >= MIN_WEIGHT:
                got = film_lane(name)
                if got:
                    lanes[name] = got
                    w[name] = weights[name]
    rows_in = {row for items in lanes.values() for row, _ in items}
    picked = compose(lanes, w, HERO + FIRST_PICKS, {r: cat.language[r] for r in rows_in}, {r: list(cat.genres[r]) for r in rows_in})
    if not any(f != "movie" for _, f in picked):
        return plan
    entry = {}
    for row, fmt in picked:
        entry[row] = pool[row] if fmt == "movie" else {"row": row, "score": dict(lanes[fmt])[row], "match_pct": None, "shares": {},
                                                       "format": "anime" if fmt.startswith("anime") else fmt}
    chosen = [row for row, _ in picked]
    new_top = chosen[HERO:] + [row for row in top["rows"] if row not in set(chosen)]
    plan = dict(plan)
    plan["hero"] = [entry[row] for row in chosen[:HERO]]
    plan["rails"] = [dict(r, rows=new_top, scored=pool | {row: entry[row] for row in chosen[HERO:]}) if r is top else r for r in plan["rails"]]
    return plan


def reason(fmt: str) -> list[dict]:
    return [{"code": "cross_format", "source": "cross_format", "share": 0,
             "text": f"Based on the {LABEL.get(fmt, fmt)} you have rated highly"}]
