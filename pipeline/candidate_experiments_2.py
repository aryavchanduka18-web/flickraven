"""Candidate experiments, round 2 (read-only), on the candidate-recall harness.

    python -m pipeline.candidate_experiments_2 --users 400     # writes work/candidate-recall/experiments-2-<date>.*

Same 400 users, seed, stages and strict protocol as pipeline/candidate_experiments.py; paired per user. Nothing in the
engine, models, calibration, Match % or database changes: arms swap the content source's scores for one call or
rearrange the returned list in memory.

D  blended strongest-likes content profile (round 1 replaced the content profile with ratings >= 9 only: more films
   without MovieLens data in the pool, but narrower and more English lists).
   D1_w   content = (1 - w) * full-profile content + w * strongest-likes content, w = 0.25 / 0.5
   D2_w   D1_w plus a mix guard on the top 10: for every language group (English, non-English, Hindi, Korean,
          Japanese) and primary genre the baseline top 10 has, the arm's top 10 keeps at least as many; missing ones are
          filled with the arm's best-ranked pool films of that group, replacing the lowest-ranked films whose group
          has a surplus.
   Win: pool recall of later-liked films without MovieLens data up (> 2 SE), NDCG@10 not worse (> -2 SE), and ILD,
   long-tail share and the non-English / Hindi / Korean / Japanese top-10 shares within 2 SE of baseline, distinct
   films within 5%.

E  a separate "recent for you" row (Top Picks untouched): the 10 best unseen films released in the 3 years up to the
   user's split time, ranked by the user's catalog-wide hybrid score (`rail_scores`, the score rows already use).
   E0 = the recent films the current Top Picks top 10 already shows; E1 = the 10 most popular recent films.
   Judged on the recent films the user later liked: share of them in the row, any-hit rate, NDCG@10 within recent.

C  baseline pool recall with ONE global cutoff (split_summary.json, 2018-08-14) instead of per-user split times:
   profile = the user's ratings at or before the cutoff (2 / 6 / all most recent), relevant = eligible unseen
   positives after it. Only validation, test and hold-out-film ratings count as relevant (they are not in the
   training matrix). The served models were trained on the per-user split, so other users' post-cutoff training
   ratings shape the item factors; there are no global-cutoff models to swap in. Read this as a check of the
   protocol, not a fully leak-free rerun.

MovieLens cannot judge Hindi / Indian films, series, anime, or films without MovieLens data other than the 500
hold-out films.
"""
from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from datetime import date

import numpy as np
import pandas as pd

from pipeline import candidate_experiments as ce
from pipeline import candidate_recall as cr

PER_SOURCE = 50
WEIGHTS = (0.25, 0.5)
LANG_GROUPS = ("hi", "ko", "ja")
MIX_KEYS = ("ndcg", "ild", "tail", "non_english", "hi", "ko", "ja", "nonml_top10")


# ----------------------------------------------------------------------------- pure helpers (tested)
def blend_content(full, strong, w: float) -> np.ndarray:
    """(1 - w) * full + w * strong; where only one side is finite, that side alone."""
    full, strong = np.asarray(full, float), np.asarray(strong, float)
    with np.errstate(invalid="ignore"):
        out = (1 - w) * full + w * strong
    only_full = np.isfinite(full) & ~np.isfinite(strong)
    only_strong = ~np.isfinite(full) & np.isfinite(strong)
    out[only_full], out[only_strong] = full[only_full], strong[only_strong]
    return out


def groups_of(row: int, language, genres) -> set:
    lang = language[row] or ""
    g = {"lang:en" if lang == "en" else "lang:non_en"}
    if lang in LANG_GROUPS:
        g.add(f"lang:{lang}")
    if len(genres[row]):
        g.add(f"genre:{genres[row][0]}")
    return g


def mix_guard(arm, base, ranked, language, genres, max_swaps: int = 10, max_candidates: int = 300) -> list:
    """Make `arm` keep at least the baseline top 10's count of every language group and primary genre.

    Candidates come from `ranked` (then `base`), tried in order of how many missing groups they cover, then rank. A
    candidate replaces the lowest-placed film whose groups would all keep their baseline count. Stops when no swap
    exists."""
    out = [int(x) for x in arm]
    need: dict = {}
    for r in base:
        for g in groups_of(int(r), language, genres):
            need[g] = need.get(g, 0) + 1
    for _ in range(max_swaps):
        have: dict = {}
        for r in out:
            for g in groups_of(r, language, genres):
                have[g] = have.get(g, 0) + 1
        deficit = {g for g in need if have.get(g, 0) < need[g]}
        if not deficit:
            break
        swapped = False
        seen, cands = set(out), []
        for r in list(ranked)[:max_candidates] + list(base):
            r = int(r)
            if r in seen:
                continue
            seen.add(r)
            cover = len(groups_of(r, language, genres) & deficit)
            if cover:
                cands.append((cover, len(cands), r))
        for _, _, cand in sorted(cands, key=lambda c: (-c[0], c[1])):      # most deficits covered, then best-ranked
            cg = groups_of(cand, language, genres)
            for pos in range(len(out) - 1, -1, -1):
                og = groups_of(out[pos], language, genres)
                if all(x in cg or have.get(x, 0) - 1 >= need.get(x, 0) for x in og):
                    out[pos] = cand
                    swapped = True
                    break
            if swapped:
                break
        if not swapped:
            break
    return out


def top_recent(score, recent_mask, excluded, k: int = 10) -> np.ndarray:
    """The k best-scoring rows inside recent_mask, excluding `excluded` and non-finite scores."""
    v = np.where(np.asarray(recent_mask, bool), np.asarray(score, float), -np.inf)
    v[np.asarray(list(excluded), dtype=np.int64)] = -np.inf
    v[~np.isfinite(v)] = -np.inf
    order = np.argsort(-v, kind="stable")[:k]
    return order[np.isfinite(v[order])]


def row_metrics(row, relevant_recent: set, top_picks, language, nonml_mask) -> dict:
    row = [int(x) for x in row]
    if not relevant_recent:
        return {}
    hits = relevant_recent & set(row)
    lang = [language[r] or "" for r in row]
    n = max(len(row), 1)
    return {"recall": len(hits) / len(relevant_recent), "hit": float(bool(hits)),
            "ndcg": cr.ndcg(row, relevant_recent) if row else 0.0, "size": len(row),
            "non_english": sum(x != "en" for x in lang) / n,
            **{code: sum(x == code for x in lang) / n for code in LANG_GROUPS},
            "nonml": float(np.mean([nonml_mask[r] for r in row])) if row else 0.0,
            "overlap_top_picks": len(set(row) & {int(x) for x in top_picks}) / n}


def d_verdict(m: dict, base: dict, nonml_delta: float, nonml_se: float) -> str:
    """Arm D win rule (module doc), for one mode's summary against baseline's."""
    ok_recall = nonml_delta > 2 * nonml_se if nonml_se else nonml_delta > 0
    ok_ndcg = not (m["ndcg_delta"] < -2 * m["ndcg_se"])
    within = all(abs(m[f"{k}_delta"]) <= 2 * m[f"{k}_se"] + 1e-12 for k in ("ild", "tail", "non_english", "hi", "ko", "ja"))
    ok_distinct = abs(m["distinct_films"] - base["distinct_films"]) <= 0.05 * base["distinct_films"]
    if ok_recall and ok_ndcg and within and ok_distinct:
        return "win"
    fails = [name for name, ok in (("non-ML recall", ok_recall), ("NDCG", ok_ndcg), ("mix/diversity", within),
                                   ("distinct films", ok_distinct)) if not ok]
    return "no: " + ", ".join(fails)


def summarise_d(D: pd.DataFrame, M: pd.DataFrame) -> dict:
    out = {}
    for stage in D.stage.unique():
        d = D[D.stage == stage]
        base = d[d.arm == "baseline"].set_index("user")
        res, nonml = {}, {}
        for arm in d.arm.unique():
            x = d[d.arm == arm].set_index("user")
            b = base.loc[x.index]
            nr, nrse = ce.paired(x.nonml_recall - b.nonml_recall)
            nonml[arm] = (nr, nrse)
            e = {"users": int(len(x)), "pool_recall": round(float(x.pool_recall.mean()), 4),
                 "nonml_recall": round(float(x.nonml_recall.mean()), 4),
                 "nonml_recall_delta": round(nr, 4), "nonml_recall_se": round(nrse, 4),
                 **{f"recall@{k}": round(float(x[f"recall@{k}"].mean()), 4) for k in cr.RECALL_AT},
                 "latency_p95_s": round(float(x.seconds.quantile(0.95)), 3)}
            if len(M):
                mm = M[(M.part == "D") & (M.stage == stage) & (M.arm == arm)]
                if len(mm):
                    e["peak_traced_mb_max"] = round(float(mm.peak_mb.max()), 2)
            for m in ce.MODES:
                s = {}
                for k in MIX_KEYS:
                    dlt, se = ce.paired(x[f"{k}_{m}"] - b[f"{k}_{m}"])
                    s[k], s[f"{k}_delta"], s[f"{k}_se"] = round(float(x[f"{k}_{m}"].mean()), 4), round(dlt, 4), round(se, 4)
                s["distinct_films"] = int(len(np.unique(np.concatenate([np.asarray(v) for v in x[f"rows_{m}"]]))))
                s["changed_top10_users"] = int(sum(set(p) != set(q) for p, q in zip(x[f"rows_{m}"], b[f"rows_{m}"])))
                e[m] = s
            res[arm] = e
        for arm, e in res.items():
            for m in ce.MODES:
                e[m]["verdict"] = "baseline" if arm == "baseline" else d_verdict(e[m], res["baseline"][m], *nonml[arm])
        out[stage] = res
    return out


# ----------------------------------------------------------------------------- the run
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--memory-users", type=int, default=20)
    a = ap.parse_args()

    from cinematch_engine.online import UserState
    from pipeline.availability_calibration import build_engine, sample
    from pipeline.cold_eval import production_like
    from pipeline.common import PROCESSED

    t0 = time.time()
    engine, movies, f = build_engine()
    production_like(engine)
    ml2row, hold_rows, users, groups = sample(engine, movies, f, a.users, a.seed)
    va = pd.read_parquet(PROCESSED / "splits" / "val.parquet")
    groups["val"] = va[va.user_id.isin(users)].groupby("user_id")
    cutoff = int(json.loads((PROCESSED / "split_summary.json").read_text(encoding="utf-8"))["global_cutoff_timestamp"])
    cat = engine.cat
    nonml_mask = cat.universe_of_row < 0
    kind = np.asarray(cat.kind)
    year = np.asarray(cat.year, float)
    print(f"engine ready {time.time() - t0:.0f}s; users {len(users)}", flush=True)

    def state(ratings_df):
        st = UserState()
        st.ratings = {ml2row[int(m)]: float(y) for m, y in zip(ratings_df.ml_movie_id, ratings_df.rating) if int(m) in ml2row}
        st.behavioral_count = len(st.ratings)
        return st

    D_rows, E_rows, C_rows, mem = [], [], [], []
    for stage, n in cr.STRICT_REGIMES.items():
        t = time.time()
        n_users = 0
        for u in users:
            tr, vau, te, nm = (cr._get(groups, p, u) for p in ("train", "val", "test", "new"))
            # ---- C: one global cutoff, baseline pool only
            allr = pd.concat([tr, vau, te, nm])
            before = allr[allr.timestamp <= cutoff]
            if len(before):
                stc = state(cr.recent_profile(before, n))
                if len(stc.ratings) >= 2:
                    labc = cr.strict_relevant(before, pd.concat([vau, te, nm]), cutoff, ml2row, engine.excluded(stc))
                    if labc:
                        ranked_c, _, _ = cr.pool_and_picks(engine, stc, engine.scores(stc), PER_SOURCE)
                        C_rows.append({"stage": stage, "user": int(u), "relevant": len(labc), "pool_size": len(ranked_c),
                                       "pool_recall": cr.recall(labc, ranked_c),
                                       **{f"recall@{k}": cr.recall(labc, ranked_c, k) for k in cr.RECALL_AT}})
            # ---- per-user split protocol (as round 1)
            st = state(cr.recent_profile(tr, n))
            if len(st.ratings) < 2:
                continue
            tt = cr.split_time(tr)
            lab = cr.strict_relevant(pd.concat([tr, nm[nm.timestamp <= tt]]), pd.concat([vau, te, nm]), tt, ml2row,
                                     engine.excluded(st))
            if not lab:
                continue
            measure = n_users < a.memory_users
            n_users += 1
            t_year = ce.year_of(tt)
            scores = engine.scores(st)
            nonml_lab = {r for r in lab if nonml_mask[r]}
            recent_mask = (year >= t_year - (ce.RECENT_YEARS - 1)) & (year <= t_year) & (kind == "movie")
            recent_lab = {r for r in lab if recent_mask[r]}

            # ---- D arms
            sub = ce.strong_ratings(st.ratings, "strong9")
            strong, strong_s = None, 0.0
            if sub and len(sub) < len(st.ratings):
                s2 = UserState()
                s2.ratings, s2.behavioral_count = sub, st.behavioral_count
                ts = time.perf_counter()
                strong = engine.scores(s2)["content"]
                strong_s = time.perf_counter() - ts
            arms = {"baseline": (scores, 0.0)}
            for w in WEIGHTS:
                if strong is None:
                    arms[f"D1_{w}"] = (scores, 0.0)          # no 9+ rating to emphasise: same as baseline
                else:
                    sc = dict(scores)
                    sc["content"] = blend_content(scores["content"], strong, w)
                    arms[f"D1_{w}"] = (sc, strong_s)
            out = {}
            for arm, (sc, extra) in arms.items():
                if measure:
                    tracemalloc.start()
                tm = time.perf_counter()
                ranked, _, fam = cr.pool_and_picks(engine, st, sc, PER_SOURCE)
                secs = time.perf_counter() - tm + extra
                if measure:
                    mem.append({"part": "D", "stage": stage, "arm": arm,
                                "peak_mb": tracemalloc.get_traced_memory()[1] / 2**20})
                    tracemalloc.stop()
                bal = cr.run_picks_sized(engine, st, sc, "balanced", PER_SOURCE)
                out[arm] = (ranked, fam.tolist(), bal.tolist(), secs)
            for w in WEIGHTS:
                ranked, fam, bal, secs = out[f"D1_{w}"]
                tm = time.perf_counter()
                g_fam = mix_guard(fam, out["baseline"][1], ranked.tolist(), cat.language, cat.genres)
                g_bal = mix_guard(bal, out["baseline"][2], ranked.tolist(), cat.language, cat.genres)
                out[f"D2_{w}"] = (ranked, g_fam, g_bal, secs + time.perf_counter() - tm)
            for arm, (ranked, fam, bal, secs) in out.items():
                row = {"stage": stage, "arm": arm, "user": int(u), "relevant": len(lab), "seconds": secs,
                       "traced": measure, "pool_recall": cr.recall(lab, ranked),
                       "nonml_recall": cr.recall(nonml_lab, ranked),
                       **{f"recall@{k}": cr.recall(lab, ranked, k) for k in cr.RECALL_AT}}
                for m, r in (("familiar", fam), ("balanced", bal)):
                    r = np.asarray(r)
                    row[f"ndcg_{m}"] = cr.ndcg(r, lab)
                    row[f"ild_{m}"] = cr.ild(engine, r)
                    row[f"tail_{m}"] = float((cat.fame_pct[r] < cr.TAIL_PCT).mean())
                    row[f"rows_{m}"] = r.tolist()
                    mix = ce.top10_mix(r, cat.language, nonml_mask, nonml_mask)
                    for k in ("non_english", "hi", "ko", "ja", "nonml_top10"):
                        row[f"{k}_{m}"] = mix[k]
                D_rows.append(row)

            # ---- E: recent-for-you row (Top Picks untouched)
            if recent_lab:
                excl = engine.excluded(st)
                if measure:
                    tracemalloc.start()
                tm = time.perf_counter()
                row_e = top_recent(engine.rail_scores(st, scores), recent_mask, excl)
                e_secs = time.perf_counter() - tm
                if measure:
                    mem.append({"part": "E", "stage": stage, "arm": "E",
                                "peak_mb": tracemalloc.get_traced_memory()[1] / 2**20})
                    tracemalloc.stop()
                row_e1 = top_recent(scores["popularity"], recent_mask, excl)
                tp = out["baseline"][2]
                for name, rw in (("E_recent_for_you", row_e), ("E1_popular_recent", row_e1),
                                 ("E0_top_picks_recent_only", [r for r in tp if recent_mask[r]]),
                                 ("E0_top_picks_top10", tp)):
                    E_rows.append({"stage": stage, "user": int(u), "row": name, "recent_relevant": len(recent_lab),
                                   "seconds": e_secs if name == "E_recent_for_you" else np.nan, "traced": measure,
                                   **row_metrics(rw, recent_lab, tp, cat.language, nonml_mask)})
        print(f"{stage} done {time.time() - t:.0f}s", flush=True)

    D, E, C, M = pd.DataFrame(D_rows), pd.DataFrame(E_rows), pd.DataFrame(C_rows), pd.DataFrame(mem)
    D = D.assign(seconds=D.seconds.where(~D.traced))
    report = {"date": date.today().isoformat(), "users_sampled": int(len(users)), "seed": a.seed,
              "global_cutoff": "2018-08-14", "D": summarise_d(D, M), "E": {}, "C": {}}
    for stage in cr.STRICT_REGIMES:
        ee = E[E.stage == stage]
        report["E"][stage] = {}
        base_e = ee[ee.row == "E0_top_picks_top10"].set_index("user")
        for name in ee.row.unique():
            x = ee[ee.row == name]
            r = {"users": int(len(x)), "mean_recent_relevant": round(float(x.recent_relevant.mean()), 1),
                 **{k: round(float(x[k].mean()), 4) for k in
                    ("recall", "hit", "ndcg", "size", "non_english", "hi", "ko", "ja", "nonml", "overlap_top_picks")}}
            if name == "E_recent_for_you":
                r["latency_p95_s"] = round(float(x.seconds[~x.traced.astype(bool)].quantile(0.95)), 3)
                mm = M[(M.part == "E") & (M.stage == stage)] if len(M) else M
                if len(mm):
                    r["peak_traced_mb_max"] = round(float(mm.peak_mb.max()), 2)
            if name in ("E_recent_for_you", "E1_popular_recent"):
                xi = x.set_index("user")
                for k in ("recall", "ndcg"):
                    dlt, se = ce.paired(xi[k] - base_e.loc[xi.index, k])
                    r[f"{k}_delta_vs_top_picks"], r[f"{k}_se"] = round(dlt, 4), round(se, 4)
            report["E"][stage][name] = r
        c = C[C.stage == stage]
        report["C"][stage] = {"users": int(len(c)), "mean_relevant": round(float(c.relevant.mean()), 1),
                              "mean_pool_size": round(float(c.pool_size.mean()), 1),
                              "pool_recall": round(float(c.pool_recall.mean()), 4),
                              **{f"recall@{k}": round(float(c[f"recall@{k}"].mean()), 4) for k in cr.RECALL_AT}}
    report["seconds"] = round(time.time() - t0)
    cr.OUT.mkdir(parents=True, exist_ok=True)
    (cr.OUT / f"experiments-2-{report['date']}.json").write_text(json.dumps(report, indent=1, default=str),
                                                                 encoding="utf-8")
    print(json.dumps({"C": report["C"], "E": report["E"]}, indent=1), flush=True)
    for stage, res in report["D"].items():
        for arm, e in res.items():
            print(stage, arm, "nonml", e["nonml_recall"], e["nonml_recall_delta"], "| bal", e["balanced"]["ndcg_delta"],
                  e["balanced"]["verdict"], "| fam", e["familiar"]["ndcg_delta"], e["familiar"]["verdict"], flush=True)
    print(f"done {report['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
