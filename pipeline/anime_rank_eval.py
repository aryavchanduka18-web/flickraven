"""Offline test of the anime ranking: today's served ranking against learned anime models, on held-out real anime lists.

    python -m pipeline.anime_rank_eval --val 500 --test 1200

Read-only. The engine is the served one over the LOCAL database (as pipeline/mixed_home_replay.py); nothing is written
to any database and no model file is changed. Results go to work/anime-rank-eval/.

Users: Kaggle "Anime Recommendations Database" list users with 10+ liked (7+) anime that match the catalog (series or
films). Two disjoint samples: VALIDATION (to choose weights and settings) and TEST (the numbers reported). Every
learned model here (today's cosine neighbours too) is re-fitted WITHOUT either sample, so nothing is leaked.

For each user 20% of the liked matched anime are hidden (the targets) and the rest of the list is the profile, in two
scenarios: "full" (the whole rest of the list, ratings as given) and "light5" (only 5 random liked titles, rated as
given: what a new anime fan on the site looks like). Watched-without-a-rating entries are only excluded, never taste.

Lists measured (NDCG@10 and hit@10, paired differences with 95% intervals):
  series   anime series (engine.kind_rank(st, "anime"): what the hero/Top Picks anime lane, "Anime for you", the Anime
           page and /recs/kind/anime use). Targets are the hidden liked anime series.
  films    anime films (today: the film hybrid's rail_scores among anime films, what the anime-film lane and the Anime
           page films row use). Targets are the hidden liked anime films.

A new model can only rank anime the lists know (the dataset ends in 2017, so newer anime are never targets). To avoid
rewarding a model for simply burying new anime, every candidate is applied "slot-preserving": the anime the model knows
keep exactly the places they hold in today's list and are only re-ordered among themselves; unknown anime do not move.
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd
import scipy.sparse as sp

from cinematch_engine import lanes as lanes_mod
from cinematch_engine.online import UserState
from pipeline import anime_model as am
from pipeline.common import PROCESSED, RAW, get_logger, write_json
from pipeline.mixed_home_replay import ROOT, load

log = get_logger("anime_rank_eval")
OUT = ROOT / "work" / "anime-rank-eval"
K = 10
DISC = 1 / np.log2(np.arange(2, K + 2))


def ndcg(lst, targets) -> tuple[float, float]:
    hit = np.array([int(r) in targets for r in lst[:K]], dtype=float)
    ideal = DISC[:min(len(targets), K)].sum()
    return float((hit * DISC[:len(hit)]).sum() / ideal) if ideal else 0.0, float(hit.any())


def pct(v):
    return (np.argsort(np.argsort(v, kind="stable"), kind="stable") + 1) / max(len(v), 1)


def slot_preserving(order: list[int], known: set[int], score: dict[int, float]) -> list[int]:
    """Re-order only the `known` rows of `order` among the slots they already hold, by `score` (higher first)."""
    slots = [i for i, r in enumerate(order) if r in known]
    ranked = sorted((order[i] for i in slots), key=lambda r: -score[r])
    out = list(order)
    for i, r in zip(slots, ranked):
        out[i] = r
    return out


def profile_vector(st: UserState, col_of_row: dict[int, int], n: int) -> np.ndarray:
    """The same entry weights the model was trained on: rated 7..10 -> 0.6..1, liked or picked -> 1."""
    u = np.zeros(n)
    for r, v in st.ratings.items():
        if v >= 7 and r in col_of_row:
            u[col_of_row[r]] = max(u[col_of_row[r]], 0.6 + 0.4 * (min(v, 10) - 7) / 3)
    for r in st.likes | st.picks:
        if r in col_of_row:
            u[col_of_row[r]] = 1.0
    return u


def users(pairs, row_of_sid, n, seed, exclude=()):
    """[(uid, rated {row: score}, watched rows, liked rows)] for list users with 10+ liked matched anime."""
    p = pairs[pairs["sid"].isin(row_of_sid) & ~pairs["uid"].isin(set(exclude))].copy()
    p["row"] = p["sid"].map(row_of_sid)
    liked = p[p["score"] >= 7].groupby("uid")["row"].nunique()
    cand = sorted(liked[liked >= 10].index)
    rng = np.random.default_rng(seed)
    chosen = rng.choice(cand, size=min(n, len(cand)), replace=False)
    by = p[p["uid"].isin(chosen)].groupby("uid")
    out = []
    for u in chosen:
        g = by.get_group(u).sort_values("score").drop_duplicates("row", keep="last")     # seasons of one title: the best score
        rated = {int(r): float(np.clip(round(s), 1, 10)) for r, s in zip(g["row"], g["score"]) if s > 0}
        watched = {int(r) for r, s in zip(g["row"], g["score"]) if s == 0}
        out.append((int(u), rated, watched))
    return out, len(cand)


def split(rated: dict, rng) -> tuple[dict, set, dict]:
    good = sorted(r for r, v in rated.items() if v >= 7)
    hide = set(int(x) for x in rng.choice(good, size=max(1, int(round(0.2 * len(good)))), replace=False))
    full = {r: v for r, v in rated.items() if r not in hide}
    rest_good = [r for r in good if r not in hide]
    five = set(int(x) for x in rng.choice(rest_good, size=min(5, len(rest_good)), replace=False))
    return full, hide, {r: full[r] for r in five}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val", type=int, default=500)
    ap.add_argument("--test", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--lams", default="300,3000,10000,30000")
    ap.add_argument("--fetch", action="store_true", help="fetch missing TMDB alternative titles of anime films")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    engine, row_of_tmdb = load()
    cat = engine.cat
    lane_of = lanes_mod.lane_of_rows(cat)
    series_rows = {r for r in range(cat.n) if lane_of[r] == "anime_series"}
    film_rows = {r for r in range(cat.n) if lane_of[r] == "anime_film"}
    tmdb_of_row = {r: t for t, r in row_of_tmdb.items()}
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id", "title", "original_title", "title_type"])
    m = am.mapping(movies, {tmdb_of_row[r] for r in film_rows if r in tmdb_of_row}, fetch=a.fetch)
    m = m[m["tmdb_id"].isin(row_of_tmdb)].reset_index(drop=True)
    m["row"] = m["tmdb_id"].map(row_of_tmdb)
    old = pd.read_csv(PROCESSED / "anime_mal_map.csv")
    pairs = am.as_pairs(pd.read_csv(RAW / "anime" / "rating.csv"))
    row_of_sid = dict(zip(m["sid"], m["row"]))

    val, n_ok = users(pairs, row_of_sid, a.val, a.seed)
    test, _ = users(pairs, row_of_sid, a.test, a.seed + 1, exclude=[u for u, _, _ in val])
    held = {u for u, _, _ in val + test}
    log.info("eligible list users %d; val %d, test %d", n_ok, len(val), len(test))

    # today's served neighbours (cosine, TV series only, old mapping), re-fitted without the held-out users
    from pipeline.drama_cf import similarities, top_k, user_item_matrix
    oitems = old["sid"].tolist()
    x, uids = user_item_matrix(pairs, oitems)
    nbs = top_k(similarities(x[~np.isin(uids, list(held))]))
    otm = dict(zip(old["sid"], old["tmdb_id"]))
    rr, cc, vv = [], [], []
    for i, nb in enumerate(nbs):
        ra = row_of_tmdb.get(int(otm[oitems[i]]))
        for j, v in nb:
            rb = row_of_tmdb.get(int(otm[oitems[j]]))
            if ra is not None and rb is not None:
                rr.append(ra); cc.append(rb); vv.append(v)
    s = sp.csr_matrix((vv, (rr, cc)), shape=(cat.n, cat.n), dtype=np.float32)
    engine.cat.series_sim = s.maximum(s.T).tocsr()

    # candidate models on the new mapping (series + films), fitted without the held-out users
    rows_of_col = np.array(sorted(set(m["row"])))
    col_of_row = {int(r): i for i, r in enumerate(rows_of_col)}
    col_of_sid = {int(sid): col_of_row[int(r)] for sid, r in zip(m["sid"], m["row"])}
    n_items = len(rows_of_col)
    known = set(col_of_row)
    xt = am.matrix(pairs, col_of_sid, n_items, drop_uids=held)
    log.info("training matrix %s, %d entries", xt.shape, xt.nnz)
    models = {}
    for lam in [float(v) for v in a.lams.split(",")]:
        b = am.ease(xt, lam)
        models[f"ease{int(lam)}"] = b
        for top in (60, 200):
            models[f"ease{int(lam)}_top{top}"] = am.sparsify(b, top).toarray()
    is_series = np.array([int(r) in series_rows for r in rows_of_col])
    # cosine item CF on the new mapping (series + films), for a like-for-like comparison with EASE
    present = (xt > 0).astype(np.float64)
    xn = xt @ sp.diags(1 / np.sqrt(np.maximum(np.asarray(xt.multiply(xt).sum(axis=0)).ravel(), 1e-9)))
    cos = (xn.T @ xn).toarray()
    both = (present.T @ present).toarray()
    cos = cos * both / (both + 25.0)
    np.fill_diagonal(cos, 0)
    models["cosine"] = cos
    pop_col = np.asarray((xt > 0).sum(axis=0)).ravel().astype(float)
    log.info("models ready (%.0fs)", time.time() - t0)

    gem = cat.gemini_sim

    def candidates(st, base_rows, which):
        """{name: {row: score}} over the known rows of base_rows."""
        kr = [int(r) for r in base_rows if int(r) in known]
        if not kr:
            return {}
        cols = np.array([col_of_row[r] for r in kr])
        u = profile_vector(st, col_of_row, n_items)
        content = engine.scores(st)["content"][kr]
        content = np.where(np.isfinite(content), content, np.nanmin(content[np.isfinite(content)]) if np.isfinite(content).any() else 0)
        fame = cat.fame_pct[kr]
        g = np.zeros(len(kr))
        if gem is not None:
            w = {r: (v - 6) / 4 for r, v in st.ratings.items() if v >= 7}
            liked = [r for r in w if gem[r].nnz]
            if liked:
                vec = sp.csr_matrix(([w[r] for r in liked], ([0] * len(liked), liked)), shape=(1, cat.n))
                g = np.asarray((vec @ gem[:, kr]).todense()).ravel()
        out = {"popularity_lists": dict(zip(kr, pop_col[cols])), "content": dict(zip(kr, content))}
        pc, pf, pg = pct(content), pct(fame), pct(g)
        raw = {}
        for name in which:
            sc = u @ models[name][:, cols] if u.any() else np.zeros(len(kr))
            raw[name] = pct(sc + 1e-9 * fame)
            out[name] = dict(zip(kr, sc + 1e-9 * fame))
        for name in which:                      # the two model families together, and one fame blend for the record
            if name.startswith("ease"):
                for we in (0.5, 0.7):
                    out[f"{name}+cosine|e{we}"] = dict(zip(kr, we * raw[name] + (1 - we) * raw["cosine"]))
        out["ease3000|m0.85f0.15"] = dict(zip(kr, 0.85 * raw["ease3000"] + 0.15 * pf)) if "ease3000" in raw else out["cosine"]
        return out

    names_full = list(models)

    def evaluate(sample, seed):
        rng = np.random.default_rng(seed)
        res = {"series": {}, "films": {}}
        for n_done, (uid, rated, watched) in enumerate(sample):
            full, hide, five = split(rated, rng)
            for scen, prof in (("full", full), ("light5", five)):
                # light5: the rest of the list is excluded (as if watched) so both scenarios rank the same unseen titles
                seen = set(watched) | (set(full) - set(prof))
                st = UserState(ratings=dict(prof), watched=seen, behavioral_count=len(prof))
                rows, _ = engine.kind_rank(st, "anime")
                gone = st.watched
                today_s = [int(r) for r in rows if int(r) not in gone]
                rail = engine.rail_scores(st)
                today_f = sorted((r for r in film_rows if np.isfinite(rail[r]) and r not in gone and r not in prof),
                                 key=lambda r: (-float(rail[r]), r))
                for lst_name, today, tg in (("series", today_s, hide & series_rows), ("films", today_f, hide & film_rows)):
                    if not tg:
                        continue
                    cands = candidates(st, today, names_full)
                    rec = res[lst_name].setdefault(scen, {})
                    rec.setdefault("today", []).append(ndcg(today, tg))
                    for name, sc in cands.items():
                        rec.setdefault(name, []).append(ndcg(slot_preserving(today, set(sc), sc), tg))
                    kn = [r for r in today if r in known]
                    rec.setdefault("_known_only_today", []).append(ndcg(kn, tg))
                    for name in ("ease300", "cosine"):
                        if name in cands:
                            rec.setdefault(f"_known_only_{name}", []).append(ndcg(sorted(kn, key=lambda r: -cands[name][r]), tg))
                    rec.setdefault("_unknown_in_today_top10", []).append((sum(1 for r in today[:K] if r not in known), 0.0))
            if n_done % 100 == 0:
                log.info("%d/%d users (%.0fs)", n_done, len(sample), time.time() - t0)
        return res

    def summary(res):
        out = {}
        for lst, by in res.items():
            for scen, d in by.items():
                base = np.array([x[0] for x in d["today"]])
                rows = {}
                for name, vals in d.items():
                    v = np.array([x[0] for x in vals]); h = np.array([x[1] for x in vals])
                    e = {"ndcg10": round(float(v.mean()), 4), "hit10": round(float(h.mean()), 4), "users": len(v)}
                    if not name.startswith("_") and name != "today":
                        diff = v - base
                        se = diff.std(ddof=1) / np.sqrt(len(diff)) if len(diff) > 1 else 0.0
                        e["diff"] = round(float(diff.mean()), 4)
                        e["ci95"] = [round(float(diff.mean() - 1.96 * se), 4), round(float(diff.mean() + 1.96 * se), 4)]
                    rows[name] = e
                out[f"{lst}/{scen}"] = dict(sorted(rows.items(), key=lambda kv: -kv[1]["ndcg10"]))
        return out

    v = summary(evaluate(val, a.seed + 100))
    write_json(OUT / "validation.json", v)
    log.info("validation done (%.0fs)", time.time() - t0)
    t = summary(evaluate(test, a.seed + 200))
    meta = {"eligible_users": n_ok, "val_users": len(val), "test_users": len(test), "train_matrix": list(xt.shape),
            "matched_series": int(is_series.sum()), "matched_films": int((~is_series).sum()),
            "catalog_anime_series": len(series_rows), "catalog_anime_films": len(film_rows),
            "old_matched_series": len(old), "seconds": round(time.time() - t0)}
    write_json(OUT / "test.json", {"meta": meta, "results": t})
    log.info("done: %s", meta)


if __name__ == "__main__":
    main()
