"""Phase 5 of the unified Home: offline replay of the mixed Home (MIXED_HOME=true) against today's Home, per user group.

    python -m pipeline.mixed_home_replay --users 300 --film-users 800

Read-only. The engine is the served one (api/app/services/recommender.load_engine) over the LOCAL database; nothing is
written to any database and no model file is changed. Results go to work/mixed-home-replay/.

For every user the same state is run twice: today's Home (`engine.home`) and the same plan passed through
`mixed_home_plan.mix` (what MIXED_HOME=true serves). The "first screen" is the hero (5) and the first 10 Top Picks, the
15 slots the mixed layer can change. Groups:

  anime     real anime lists (Kaggle "Anime Recommendations Database", data/raw/anime). 20% of each user's liked
            (7+) matched anime are hidden; the rest of the list is the profile.
  kdrama    real MyDramaList lists (data/raw/mydramalist), users whose matched list is mostly Korean series. 20% of
            their liked (7+) Korean series are hidden.
  indian    MovieLens users with at least 3 liked (7+) Indian-language films in their training ratings; 1/3 of those
            Indian films are hidden (at least 1).
  film      MovieLens held-out users (the same sampler as pipeline/availability_calibration.py): profile = training
            ratings, targets = later ratings of 7+ (test split and the 500 hold-out films). The guard: NDCG@10 of the
            first screen must not fall by more than 0.003.

Leakage: the learned anime and drama similarities served on the site were fitted on ALL list users, the test users
included. Here they are re-learned in memory (same code, pipeline/drama_cf.py) on the list users NOT in the test
sample, and swapped into the engine for the run. The MovieLens models are the served ones: the film group's targets
are later ratings they never saw; the indian group's hidden films were in training (disclosed in the report).

All differences are paired (same users, same hidden titles), with a 95% interval (1.96 standard errors).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from cinematch_engine import lanes as lanes_mod                                   # noqa: E402
from cinematch_engine.online import UserState                                     # noqa: E402
from pipeline.common import PROCESSED, RAW, get_logger, write_json               # noqa: E402

log = get_logger("mixed_home_replay")
OUT = ROOT / "work" / "mixed-home-replay"
SLOTS, K = 15, 10
DISC = 1 / np.log2(np.arange(2, SLOTS + 2))
GUARD = 0.003


# ---------------------------------------------------------------------------------------------------------- engine
def load():
    """Served engine over the local database, opened read-only."""
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    url = dotenv_values(ROOT / ".env")["DATABASE_URL"].strip()
    if "localhost" not in url and "127.0.0.1" not in url:
        raise SystemExit("refusing to run against a non-local database")
    os.environ["DATABASE_URL"] = url
    from app.services import recommender as rec
    db = Session(create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"}))
    engine = rec.load_engine(db)
    tmdb = dict(db.execute(text("SELECT id, tmdb_id FROM movies")).all())
    row_of_tmdb = {int(tmdb[int(m)]): r for r, m in enumerate(engine.cat.movie_ids) if int(m) in tmdb}
    return engine, row_of_tmdb


def leak_free_series_sim(engine, row_of_tmdb, lists: dict, test_uids: dict) -> sp.csr_matrix:
    """The learned anime + drama similarity matrix, re-fitted without the test users (same method as served)."""
    from pipeline.drama_cf import similarities, top_k, user_item_matrix
    n = engine.cat.n
    rows, cols, vals = [], [], []
    for name, (pairs, mapping) in lists.items():
        items = mapping["sid"].tolist()
        x, users = user_item_matrix(pairs, items)
        keep = ~np.isin(users, list(test_uids.get(name, ())))
        nbs = top_k(similarities(x[keep]))
        tm = dict(zip(mapping["sid"], mapping["tmdb_id"]))
        for i, nb in enumerate(nbs):
            a = row_of_tmdb.get(int(tm[items[i]]))
            for j, v in nb:
                b = row_of_tmdb.get(int(tm[items[j]]))
                if a is not None and b is not None:
                    rows.append(a); cols.append(b); vals.append(v)
        log.info("%s similarities re-learned on %d of %d list users", name, int(keep.sum()), len(users))
    sim = sp.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=np.float32)
    return sim.maximum(sim.T).tocsr()


# ---------------------------------------------------------------------------------------------------------- users
def list_users(pairs, mapping, row_of_tmdb, lane_of, lane_ok, n, seed, min_liked=10, max_liked=None):
    """Users of a list dataset with at least `min_liked` liked titles in the wanted lane(s) and at least 60% of their
    matched list in it. Returns ([(uid, ratings {row: score}, hidden rows)], eligible count); 20% of the liked titles
    of that lane are hidden (at least 1)."""
    to_row = {int(s): row_of_tmdb[int(t)] for s, t in zip(mapping["sid"], mapping["tmdb_id"]) if int(t) in row_of_tmdb}
    p = pairs[pairs["sid"].isin(to_row) & (pairs["score"] > 0)].copy()
    p["row"] = p["sid"].map(to_row)
    p["ok"] = p["row"].map(lambda r: lane_ok(lane_of[r]))
    liked = p[(p["score"] >= 7) & p["ok"]].groupby("uid").size()
    share = p.groupby("uid")["ok"].mean()
    ok_n = liked[(liked >= min_liked) & (liked <= (max_liked or 10**9))]
    cand = sorted(set(ok_n.index) & set(share[share >= 0.6].index))
    rng = np.random.default_rng(seed)
    chosen = rng.choice(cand, size=min(n, len(cand)), replace=False)
    by = p[p["uid"].isin(chosen)].groupby("uid")
    out = []
    for u in chosen:
        g = by.get_group(u).drop_duplicates("row", keep="last")
        good = g[(g["score"] >= 7) & g["ok"]]["row"].to_numpy()
        hide = set(int(x) for x in rng.choice(good, size=max(1, int(round(0.2 * len(good)))), replace=False))
        ratings = {int(r): float(np.clip(round(s), 1, 10)) for r, s in zip(g["row"], g["score"]) if int(r) not in hide}
        out.append((int(u), ratings, hide))
    return out, len(cand)


def movielens(row_of_tmdb, lane_of, n_film, n_indian, seed):
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id", "ml_movie_id"])
    ml2row = {int(m): row_of_tmdb[int(t)] for t, m in zip(movies["tmdb_id"], movies["ml_movie_id"])
              if pd.notna(m) and int(t) in row_of_tmdb}
    sp_ = PROCESSED / "splits"
    tr, te, nm = (pd.read_parquet(sp_ / f"{x}.parquet") for x in ("train", "test", "newmovie_test"))
    fitted = set(np.load(ROOT / "artifacts" / "models" / "fitted.npz")["user_ids"].tolist())
    tr = tr[tr["ml_movie_id"].isin(ml2row)].copy()
    tr["row"] = tr["ml_movie_id"].map(ml2row)
    rng = np.random.default_rng(seed)
    # film-only guard group (same eligibility rule as availability_calibration.sample)
    ok = sorted(set(nm[nm.rating >= 7].user_id) & set(te[te.rating >= 7].user_id) & fitted)
    film_ids = rng.choice(ok, size=min(n_film, len(ok)), replace=False)
    later = pd.concat([te, nm])
    later = later[later["user_id"].isin(film_ids) & (later["rating"] >= 7) & later["ml_movie_id"].isin(ml2row)]
    tgt = later.groupby("user_id")["ml_movie_id"].apply(lambda s: {ml2row[int(x)] for x in s})
    trg = tr[tr["user_id"].isin(film_ids)].groupby("user_id")
    film = [(int(u), {int(r): float(v) for r, v in zip(trg.get_group(u)["row"], trg.get_group(u)["rating"])},
             tgt.get(u, set())) for u in film_ids if u in trg.groups]
    # Indian-film fans
    tr["ind"] = tr["row"].map(lambda r: lane_of[r] == "indian_film")
    fans = tr[tr["ind"] & (tr["rating"] >= 7)].groupby("user_id").size()
    cand = sorted(set(fans[fans >= 3].index))
    pick = rng.choice(cand, size=min(n_indian, len(cand)), replace=False) if cand else []
    g2 = tr[tr["user_id"].isin(pick)].groupby("user_id")
    indian = []
    for u in pick:
        g = g2.get_group(u)
        good = g[g["ind"] & (g["rating"] >= 7)]["row"].to_numpy()
        hide = set(int(x) for x in rng.choice(good, size=max(1, len(good) // 3), replace=False))
        indian.append((int(u), {int(r): float(v) for r, v in zip(g["row"], g["rating"]) if int(r) not in hide}, hide))
    # international-film fans who pass the strict gate: 10+ liked international films and over half of their liked films
    liked = tr[tr["rating"] >= 7]
    tot = liked.groupby("user_id").size()
    intl_n = liked[liked["row"].map(lambda r: lane_of[r] == "international_film")].groupby("user_id").size()
    cand2 = sorted(u for u in intl_n.index if intl_n[u] >= 10 and intl_n[u] > 0.5 * tot[u])
    pick2 = rng.choice(cand2, size=min(n_indian, len(cand2)), replace=False) if cand2 else []
    g3 = tr[tr["user_id"].isin(pick2)].groupby("user_id")
    intl_film = []
    for u in pick2:
        g = g3.get_group(u)
        good = g[(g["rating"] >= 7) & g["row"].map(lambda r: lane_of[r] == "international_film")]["row"].to_numpy()
        hide = set(int(x) for x in rng.choice(good, size=max(1, len(good) // 3), replace=False))
        intl_film.append((int(u), {int(r): float(v) for r, v in zip(g["row"], g["rating"]) if int(r) not in hide}, hide))
    return film, indian, intl_film, len(cand), len(cand2)


# ---------------------------------------------------------------------------------------------------------- replay
def first_screen(plan) -> list[int]:
    """Hero then the first K Top Picks: the slots the mixed layer can change."""
    top = next((r for r in plan["rails"] if r["key"] == "top_picks"), {"rows": []})
    return [e["row"] for e in plan["hero"]] + list(top["rows"])[:K]


def screen_metrics(lst: list[int], targets: set[int]) -> dict:
    hit = np.array([r in targets for r in lst], dtype=float)
    ideal = DISC[:min(len(targets), K)].sum()
    return {"hit15": float(hit.any()), "recall15": float(hit.sum() / max(min(len(targets), SLOTS), 1)),
            "ndcg10": float((hit[:K] * DISC[:len(hit[:K])]).sum() / ideal) if ideal else 0.0}


def run_user(engine, mix, ratings, targets, lane_of, lanes=frozenset()):
    st = UserState(ratings=dict(ratings), behavioral_count=len(ratings))
    scores = engine.scores(st)
    plan = engine.home(st, "balanced", scores=scores)
    cur = first_screen(plan)[:SLOTS]
    new = first_screen(mix(engine, st, plan, set(), set()))[:SLOTS]
    out = {}
    for name, lst in (("current", cur), ("mixed", new)):
        out[name] = screen_metrics(lst, targets) | {
            "non_film": sum(1 for r in lst if str(engine.cat.kind[r]) != "movie" or lane_of[r] == "anime_film"),
            "lanes": sorted({lane_of[r] for r in lst})}
    out["changed"] = cur != new
    # does this person qualify for any switched-on lane (enough liked titles of it)? Only those can see a different page.
    from app.services import mixed_home_plan as mh
    from cinematch_engine.mixed_home import MIN_WEIGHT, lane_weight
    ev = mh.evidence(engine, st)
    out["qualifies"] = any(lane_weight(*ev[g]) >= MIN_WEIGHT for g in mh.GROUPS if g in lanes)
    return out


def paired(rows, key):
    a = np.array([r["current"][key] for r in rows]); b = np.array([r["mixed"][key] for r in rows])
    d = b - a
    se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else 0.0
    return {"current": round(float(a.mean()), 4), "mixed": round(float(b.mean()), 4), "diff": round(float(d.mean()), 4),
            "ci95": [round(float(d.mean() - 1.96 * se), 4), round(float(d.mean() + 1.96 * se), 4)]}


def lane_hit_reference(engine, users, kind, lane_name, lane_of):
    """Where today's Home already shows these titles: the person's own anime / Korean-series list (what the anime and
    series rows lower on the page draw from), top 20."""
    hits = []
    for _, ratings, hide in users:
        st = UserState(ratings=dict(ratings), behavioral_count=len(ratings))
        rows, _ = engine.kind_rank(st, kind)
        if lane_name:
            rows = [r for r in rows if lane_of[int(r)] == lane_name]
        hits.append(float(any(int(r) in hide for r in list(rows)[:20])))
    return round(float(np.mean(hits)), 4) if hits else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=300)
    ap.add_argument("--film-users", type=int, default=800)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--lanes", default="anime", help="lanes switched on (HOME_LANES): anime, korean_series, indian_series, "
                    "hollywood_series, international_series, indian_film, international_film")
    ap.add_argument("--out", default=None, help="results file name in work/mixed-home-replay/")
    ap.add_argument("--groups", default="anime,anime_light,kdrama,kdrama_light,intl_drama,indian,intl_film,film")
    a = ap.parse_args()
    t0 = time.time()
    engine, row_of_tmdb = load()
    from app.services import mixed_home_plan
    from pipeline.anime_cf import as_pairs
    lane_of = lanes_mod.lane_of_rows(engine.cat)
    log.info("engine loaded in %.0fs, %d titles", time.time() - t0, engine.cat.n)

    anime_pairs = as_pairs(pd.read_csv(RAW / "anime" / "rating.csv"))
    drama_pairs = pd.read_parquet(RAW / "mydramalist" / "df_pairs.parquet", columns=["uid", "sid", "score", "completed"])
    amap, dmap = (pd.read_csv(PROCESSED / f) for f in ("anime_mal_map.csv", "drama_mdl_map.csv"))
    is_anime, is_ko, is_intl = (lambda l: l.startswith("anime")), (lambda l: l == "korean_series"), (lambda l: l == "international_series")
    anime, n_anime = list_users(anime_pairs, amap, row_of_tmdb, lane_of, is_anime, a.users, a.seed)
    kdrama, n_kd = list_users(drama_pairs, dmap, row_of_tmdb, lane_of, is_ko, a.users, a.seed)
    # light fans: 3 to 9 liked titles of the lane (partial lane weight), and non-Korean Asian drama fans
    anime_l, n_al = list_users(anime_pairs, amap, row_of_tmdb, lane_of, is_anime, a.users, a.seed + 1, 3, 9)
    kdrama_l, n_kl = list_users(drama_pairs, dmap, row_of_tmdb, lane_of, is_ko, a.users, a.seed + 1, 3, 9)
    intl, n_int = list_users(drama_pairs, dmap, row_of_tmdb, lane_of, is_intl, a.users, a.seed + 2, 5)
    excluded_anime = {u for u, _, _ in anime + anime_l}
    excluded_drama = {u for u, _, _ in kdrama + kdrama_l + intl}
    engine.cat.series_sim = leak_free_series_sim(engine, row_of_tmdb, {"anime": (anime_pairs, amap), "drama": (drama_pairs, dmap)},
                                                 {"anime": excluded_anime, "drama": excluded_drama})
    film, indian, intl_film, n_ind, n_if = movielens(row_of_tmdb, lane_of, a.film_users, a.users, a.seed)
    pools = {"anime": n_anime, "anime_light": n_al, "kdrama": n_kd, "kdrama_light": n_kl, "intl_drama": n_int, "indian": n_ind, "intl_film": n_if}
    log.info("eligible pools %s, film %d", pools, len(film))
    import functools
    lanes = mixed_home_plan.enabled_lanes(a.lanes)
    mix = functools.partial(mixed_home_plan.mix, lanes=lanes)

    results = {}
    for name, users in (("anime", anime), ("anime_light", anime_l), ("kdrama", kdrama), ("kdrama_light", kdrama_l),
                        ("intl_drama", intl), ("indian", indian), ("intl_film", intl_film), ("film", film)):
        if name not in a.groups.split(","):
            continue
        rows = []
        t1 = time.time()
        for i, (_, ratings, targets) in enumerate(users):
            if targets:
                rows.append(run_user(engine, mix, ratings, targets, lane_of, lanes))
            if i % 50 == 49:
                log.info("%s %d/%d (%.0fs)", name, i + 1, len(users), time.time() - t1)
        res = {"users": len(rows), "eligible_pool": pools.get(name)}
        if rows:
            res |= {"pages_changed": round(float(np.mean([r["changed"] for r in rows])), 4),
                    "avg_non_film_slots_current": round(float(np.mean([r["current"]["non_film"] for r in rows])), 2),
                    "avg_non_film_slots_mixed": round(float(np.mean([r["mixed"]["non_film"] for r in rows])), 2),
                    "mixed_lanes_seen": pd.Series([l for r in rows for l in r["mixed"]["lanes"]]).value_counts().to_dict()}
            for key in ("hit15", "recall15", "ndcg10"):
                res[key] = paired(rows, key)
            q, nq = [r for r in rows if r["qualifies"]], [r for r in rows if not r["qualifies"]]
            res["share_qualifying_for_a_switched_on_lane"] = round(len(q) / len(rows), 4)
            res["non_qualifiers"] = {"users": len(nq), "pages_changed": round(float(np.mean([r["changed"] for r in nq])), 4) if nq else None}
            if len(q) > 1:
                res["ndcg10_qualifiers_only"] = paired(q, "ndcg10")
                res["hit15_qualifiers_only"] = paired(q, "hit15")
            changed = [r for r in rows if r["changed"]]
            if len(changed) > 1:
                res["ndcg10_changed_pages_only"] = paired(changed, "ndcg10")
        results[name] = res
        log.info("%s: %s", name, json.dumps(res))
    if True:
        results["reference_lane_rows_hit20"] = {"anime": lane_hit_reference(engine, anime, "anime", None, lane_of),
                                                "kdrama": lane_hit_reference(engine, kdrama, "series", "korean_series", lane_of)}
    if "film" in results:
        d = results["film"]["ndcg10"]
        results["film_guard"] = {"rule": f"mixed NDCG@10 minus current >= -{GUARD}", "diff": d["diff"], "ci95": d["ci95"],
                                 "pass": d["diff"] >= -GUARD, "pass_strict_ci": d["ci95"][0] >= -GUARD}
    results["lanes"] = sorted(lanes)
    results["seconds"] = round(time.time() - t0)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / (a.out or "results-lanes.json")
    write_json(out, results)
    log.info("wrote %s", out)


if __name__ == "__main__":
    main()
