"""Candidate-source experiments (read-only), on the candidate-recall harness (pipeline/candidate_recall.py).

    python -m pipeline.candidate_experiments --users 400          # writes work/candidate-recall/experiments-<date>.*
    python -m pipeline.candidate_experiments --users 10           # smoke run

Every arm runs the real `OnlineEngine.top_picks` unchanged at 50 per source. An arm either ADDS films to the pool
(through the harness's `inject` hook, which places them with the engine's own availability-aware score) or swaps one
source's scores for that call. Nothing in the engine, models, calibration, Match % or database is changed.

Arms (same users, profiles and baseline pool for every arm; differences are paired per user):
  baseline          shipped pool (50 per source)
  recent_20/50      + the N most popular eligible films released in the 3 years up to the user's split time
                    (year(T)-2 .. year(T): "recent" as it was when the user was being recommended to)
  nonml_quota_5/10  established users only: + k films without MovieLens data, chosen by the content source's
                    similarity to the user's profile (positive similarity required), never by popularity alone
  strong9_content   content source scored from ratings >= 9 only (identical to baseline if there are none)
  top5_content      content source scored from the user's 5 highest ratings

Protocol (as candidate_recall's strict protocol): split time T = last training rating; profile = n most recent training
ratings (2 / 6 / all); relevant = eligible unseen films rated >= 7 after T.

MovieLens cannot judge: Hindi and other Indian films (a handful of relevant ratings), series, anime, and films without
MovieLens data other than the 500 hold-out films. An arm that adds such films can only LOSE NDCG here (they can never be
hits), so their top-10 share is reported next to NDCG and must be read with that in mind.
"""
from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from pipeline import candidate_recall as cr

PER_SOURCE = 50
RECENT_YEARS = 3
LANGS = ("hi", "ko", "ja")
MODES = ("familiar", "balanced")


# ----------------------------------------------------------------------------- arm selectors (pure, tested)
def year_of(ts: int) -> int:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).year


def recent_rows(year, kind, popularity: np.ndarray, t_year: int, n: int, blocked) -> np.ndarray:
    """The n most popular films released in the RECENT_YEARS up to t_year, not blocked (excluded or already pooled)."""
    year = np.asarray(year, float)
    ok = (year >= t_year - (RECENT_YEARS - 1)) & (year <= t_year) & (np.asarray(kind) == "movie")
    ok &= np.isfinite(popularity)
    ok[np.asarray(list(blocked), dtype=np.int64)] = False
    rows = np.nonzero(ok)[0]
    return rows[np.argsort(-popularity[rows], kind="stable")[:n]]


def nonml_rows(nonml, content: np.ndarray, k: int, blocked) -> np.ndarray:
    """The k films without MovieLens data most similar to the profile by the content source (similarity must be > 0)."""
    rows = np.setdiff1d(np.asarray(nonml, dtype=np.int64), np.asarray(list(blocked), dtype=np.int64))
    v = content[rows]
    rows = rows[np.isfinite(v) & (v > 0)]
    return rows[np.argsort(-content[rows], kind="stable")[:k]]


def strong_ratings(ratings: dict, rule: str) -> dict:
    """Subset of a profile's ratings for the strong-likes content arms."""
    if rule == "strong9":
        return {r: y for r, y in ratings.items() if y >= 9}
    if rule == "top5":
        return dict(sorted(ratings.items(), key=lambda kv: (-kv[1], kv[0]))[:5])
    raise ValueError(rule)


def paired(diff) -> tuple[float, float]:
    d = np.asarray(diff, float)
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return float("nan"), float("nan")
    return float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d)))


def verdict(ndcg_d, ndcg_se, ild_d, ild_se, tail_d, tail_se) -> str:
    """Win only if NDCG@10 rises by more than 2 SE and neither diversity nor long-tail share falls by more than 2 SE."""
    if not np.isfinite(ndcg_d) or not ndcg_se:
        return "no change"
    regress = (ild_d < -2 * ild_se) or (tail_d < -2 * tail_se)
    if ndcg_d > 2 * ndcg_se and not regress:
        return "win"
    if ndcg_d < -2 * ndcg_se:
        return "worse"
    return "regresses diversity/tail" if regress else "no significant change"


def top10_mix(rows, language, nonml_mask, unhittable_mask) -> dict:
    rows = np.asarray(rows)
    lang = [language[r] or "" for r in rows]
    out = {"english": float(np.mean([x == "en" for x in lang])), "non_english": float(np.mean([x != "en" for x in lang])),
           "nonml_top10": float(nonml_mask[rows].mean()), "nonml_at_1": float(nonml_mask[rows[0]]) if len(rows) else 0.0,
           "unhittable_top10": float(unhittable_mask[rows].mean())}
    for code in LANGS:
        out[code] = float(np.mean([x == code for x in lang]))
    return out


def summarise(R: pd.DataFrame, M: pd.DataFrame) -> dict:
    """Per stage and arm: recall, paired NDCG/ILD/tail deltas vs baseline, top-10 mix, latency, memory, verdict."""
    stages = {}
    for stage in R.stage.unique():
        d = R[R.stage == stage]
        base = d[d.arm == "baseline"].set_index("user")
        out = {}
        for arm in d.arm.unique():
            x = d[d.arm == arm].set_index("user")
            b = base.loc[x.index]
            e = {"users": int(len(x)), "mean_pool_size": round(float(x.pool_size.mean()), 1),
                 "mean_added_by_arm": round(float(x.arm_added.mean()), 1),
                 "relevant_found_via_arm_share": round(float(x.arm_hits.sum() / max(x.relevant.sum(), 1)), 4),
                 "pool_recall": round(float(x.pool_recall.mean()), 4),
                 **{f"recall@{k}": round(float(x[f"recall@{k}"].mean()), 4) for k in cr.RECALL_AT},
                 "recent_films_pool_recall": round(float(x.recent_recall.mean()), 4),
                 "recent_relevant_users": int(x.recent_recall.notna().sum()),
                 "nonml_films_pool_recall": round(float(x.nonml_recall.mean()), 4),
                 "nonml_relevant_users": int(x.nonml_recall.notna().sum()),
                 "latency_mean_s": round(float(x.seconds.mean()), 3),
                 "latency_p95_s": round(float(x.seconds.quantile(0.95)), 3)}
            if len(M):
                mm = M[(M.stage == stage) & (M.arm == arm)]
                e["peak_traced_mb_max"] = round(float(mm.peak_mb.max()), 2) if len(mm) else None
            for m in MODES:
                nd, nse = paired(x[f"ndcg_{m}"] - b[f"ndcg_{m}"])
                idd, ise = paired(x[f"ild_{m}"] - b[f"ild_{m}"])
                tdd, tse = paired(x[f"tail_{m}"] - b[f"tail_{m}"])
                allr = np.concatenate([np.asarray(v) for v in x[f"rows_{m}"]])
                e[m] = {"ndcg@10": round(float(x[f"ndcg_{m}"].mean()), 4), "ndcg_delta": round(nd, 4),
                        "ndcg_se": round(nse, 4), "ild": round(float(x[f"ild_{m}"].mean()), 3),
                        "ild_delta": round(idd, 4), "ild_se": round(ise, 4),
                        "long_tail_share": round(float(x[f"tail_{m}"].mean()), 3), "tail_delta": round(tdd, 4),
                        "tail_se": round(tse, 4), "distinct_films": int(len(np.unique(allr))),
                        "changed_top10_users": int(sum(set(p) != set(q) for p, q in zip(x[f"rows_{m}"], b[f"rows_{m}"]))),
                        **{k: round(float(x[f"{k}_{m}"].mean()), 4) for k in
                           ("english", "non_english", "hi", "ko", "ja", "nonml_top10", "nonml_at_1", "unhittable_top10")},
                        "verdict": "baseline" if arm == "baseline" else verdict(nd, nse, idd, ise, tdd, tse)}
            out[arm] = e
        stages[stage] = out
    return stages


# ----------------------------------------------------------------------------- the run
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--memory-users", type=int, default=20, help="users per stage whose calls are traced for memory")
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
    cat = engine.cat
    nonml_mask = cat.universe_of_row < 0
    hittable = ~nonml_mask
    hittable[hold_rows] = True
    unhittable_mask = ~hittable
    nonml = engine.unavailable_rows()
    kind = np.asarray(cat.kind)
    print(f"engine ready {time.time() - t0:.0f}s; users {len(users)}", flush=True)

    rows_out, mem_rows = [], []
    for stage, n in cr.STRICT_REGIMES.items():
        t = time.time()
        n_users = 0
        for u in users:
            tr, vau, te, nm = (cr._get(groups, p, u) for p in ("train", "val", "test", "new"))
            prof = cr.recent_profile(tr, n)
            st = UserState()
            st.ratings = {ml2row[int(m)]: float(y) for m, y in zip(prof.ml_movie_id, prof.rating) if int(m) in ml2row}
            st.behavioral_count = len(st.ratings)
            if len(st.ratings) < 2:
                continue
            tt = cr.split_time(tr)
            lab = cr.strict_relevant(pd.concat([tr, nm[nm.timestamp <= tt]]), pd.concat([vau, te, nm]), tt, ml2row,
                                     engine.excluded(st))
            if not lab:
                continue
            t_year = year_of(tt)
            scores = engine.scores(st)
            arms = {"baseline": (scores, None, 0.0)}
            for N in (20, 50):
                def inj(st_, sc, excl, pool, N=N):
                    return recent_rows(cat.year, kind, sc["popularity"], t_year, N, np.union1d(excl, pool))
                arms[f"recent_{N}"] = (scores, inj, 0.0)
            if stage == "established":
                for k in (5, 10):
                    def inj(st_, sc, excl, pool, k=k):
                        return nonml_rows(nonml, sc["content"], k, np.union1d(excl, pool))
                    arms[f"nonml_quota_{k}"] = (scores, inj, 0.0)
            for rule in ("strong9", "top5"):
                sub = strong_ratings(st.ratings, rule)
                if sub and len(sub) < len(st.ratings):
                    s2 = UserState()
                    s2.ratings, s2.behavioral_count = sub, st.behavioral_count
                    ts = time.perf_counter()
                    swapped = dict(scores)
                    swapped["content"] = engine.scores(s2)["content"]
                    arms[f"{rule}_content"] = (swapped, None, time.perf_counter() - ts)
                else:
                    arms[f"{rule}_content"] = (scores, None, 0.0)       # nothing to drop: identical to baseline
            measure = n_users < a.memory_users
            n_users += 1
            recent_lab = {r for r in lab if np.isfinite(cat.year[r]) and cat.year[r] >= t_year - (RECENT_YEARS - 1)}
            nonml_lab = {r for r in lab if nonml_mask[r]}
            for arm, (sc, inj, extra_s) in arms.items():
                if measure:
                    tracemalloc.start()
                tm = time.perf_counter()
                ranked, proposed, rec = cr.pool_and_picks(engine, st, sc, PER_SOURCE, inject=inj)
                secs = time.perf_counter() - tm + extra_s
                if measure:
                    mem_rows.append({"stage": stage, "arm": arm, "peak_mb": tracemalloc.get_traced_memory()[1] / 2**20})
                    tracemalloc.stop()
                bal = cr.run_picks_sized(engine, st, sc, "balanced", PER_SOURCE, inject=inj)
                added = proposed.get("arm", set())
                row = {"stage": stage, "arm": arm, "user": int(u), "relevant": len(lab), "pool_size": len(ranked),
                       "seconds": secs, "traced": measure, "arm_added": len(added), "arm_hits": len(lab & added),
                       "pool_recall": cr.recall(lab, ranked),
                       "recent_recall": cr.recall(recent_lab, ranked), "nonml_recall": cr.recall(nonml_lab, ranked),
                       **{f"recall@{k}": cr.recall(lab, ranked, k) for k in cr.RECALL_AT}}
                for m, r in (("familiar", rec), ("balanced", bal)):
                    row[f"ndcg_{m}"] = cr.ndcg(r, lab)
                    row[f"ild_{m}"] = cr.ild(engine, r)
                    row[f"tail_{m}"] = float((cat.fame_pct[r] < cr.TAIL_PCT).mean())
                    row[f"rows_{m}"] = r.tolist()
                    for key, v in top10_mix(r, cat.language, nonml_mask, unhittable_mask).items():
                        row[f"{key}_{m}"] = v
                rows_out.append(row)
            if n_users % 100 == 0:
                print(f"  {stage} {n_users} users {time.time() - t:.0f}s", flush=True)
        print(f"{stage} done {time.time() - t:.0f}s", flush=True)

    R, M = pd.DataFrame(rows_out), pd.DataFrame(mem_rows)
    # latency from untraced calls only (tracing slows the call)
    report = {"date": date.today().isoformat(), "users_sampled": int(len(users)), "seed": a.seed,
              "per_source": PER_SOURCE, "recent_years": RECENT_YEARS,
              "stages": summarise(R.assign(seconds=R.seconds.where(~R.traced)), M)}
    report["seconds"] = round(time.time() - t0)
    cr.OUT.mkdir(parents=True, exist_ok=True)
    stamp = report["date"]
    (cr.OUT / f"experiments-{stamp}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    R.drop(columns=[c for c in R.columns if c.startswith("rows_")]).to_parquet(
        cr.OUT / f"experiments-users-{stamp}.parquet", index=False)
    for stage, out in report["stages"].items():
        for arm, e in out.items():
            print(stage, arm, "pool", e["pool_recall"], "| bal", e["balanced"]["ndcg_delta"], e["balanced"]["ndcg_se"],
                  e["balanced"]["verdict"], "| fam", e["familiar"]["ndcg_delta"], e["familiar"]["ndcg_se"],
                  e["familiar"]["verdict"], flush=True)
    print(f"done {report['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
