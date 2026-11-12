"""Candidate-recall harness (read-only): how many films a user later likes ever reach the candidate pool?

    python -m pipeline.candidate_recall --users 400            # full run, writes work/candidate-recall/
    python -m pipeline.candidate_recall --users 20 --quick     # smoke run

Nothing in the engine, the models, the calibration or the database is changed. The real `OnlineEngine.top_picks` is run
unchanged; the harness only wraps `candidate_pool` and `_add_unavailable_candidates` on the in-memory objects to (a) record
the pool they build and (b) change the per-source size for the sweep (50 / 100 / 200). The wrappers are removed afterwards.

Two protocols on the SAME held-out MovieLens users as work/audit/retrieval_audit.py (pipeline.availability_calibration
.sample, seed 11):

  audit   exactly the audit's protocol: profile = random n training ratings (pipeline.cold_eval.make_state), relevant =
          test-split and hold-out-film ratings >= 7 minus the profile. Used to reproduce the audit's 31-37% pool recall.
  strict  temporal holdout. Split time T = the user's last training rating. Profile = the n most recent training ratings
          (all of them for established). Relevant = ratings >= 7 strictly after T (validation, test and hold-out-film
          ratings), only on eligible films: in the catalog, a film (series and anime are excluded by the engine), not
          rated by the user at or before T, not hidden by the engine's own exclusions.

Between the two, the label changes are applied one at a time (same pools) so any gap is attributed to a named step.

Limits that cannot be fixed with MovieLens: no series or anime, no language or genre onboarding, no session signals; films
without MovieLens data are represented by the 500 hold-out films (well-known films, so they flatter that group); NCF is a
lab-only model (spec 5, A3) with no fold-in for a new profile, so it is not a pool source and cannot be measured here.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import time
import tracemalloc
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

POSITIVE = 7                     # rating >= 7/10 is a positive (spec 4.3)
K = 10
DISC = 1 / np.log2(np.arange(2, K + 2))
SIZES = (50, 100, 200)
RECALL_AT = (50, 100, 200)
STRICT_REGIMES = {"cold": 2, "warming": 6, "established": None}          # n most recent training ratings (None = all)
AUDIT_REGIMES = {"cold2": (2, 0), "picks5": (0, 5), "warming6": (6, 0), "established": (None, 0)}
HEAD_PCT, TAIL_PCT = 95, 80      # fame percentile: head >= 95 (top 5%), torso 80-95, long tail < 80 (rerank.TAIL_PCT)
OUT = Path(__file__).resolve().parents[1] / "work" / "candidate-recall"
EMPTY = pd.DataFrame({"user_id": pd.Series(dtype="int64"), "ml_movie_id": pd.Series(dtype="int64"),
                      "rating": pd.Series(dtype="int64"), "timestamp": pd.Series(dtype="int64")})


# ----------------------------------------------------------------------------- pure helpers (tested on synthetic data)
def split_time(train: pd.DataFrame) -> int:
    """The user's split time: the timestamp of their last training rating."""
    return int(train["timestamp"].max())


def recent_profile(train: pd.DataFrame, n: int | None) -> pd.DataFrame:
    """The n most recent training ratings (ties by film id, as the split itself); None = the whole training history."""
    r = train.sort_values(["timestamp", "ml_movie_id"])
    return r if n is None else r.tail(n)


def strict_relevant(before: pd.DataFrame, after: pd.DataFrame, t: int, ml2row: dict, excluded=()) -> set[int]:
    """Eligible catalog rows the user rated >= POSITIVE strictly after t.

    before: every rating of the user at or before t (all of them count as seen, not only the profile).
    after:  candidate later ratings (any split); rows at or before t also count as seen, so callers may pass whole parts.
    excluded: catalog rows the engine hides for this user (its own `excluded`, which includes non-film rows)."""
    seen = {ml2row[int(m)] for m in before["ml_movie_id"] if int(m) in ml2row}
    seen |= {ml2row[int(m)] for m, ts in zip(after["ml_movie_id"], after["timestamp"]) if ts <= t and int(m) in ml2row}
    later = after[(after["timestamp"] > t) & (after["rating"] >= POSITIVE)]
    rel = {ml2row[int(m)] for m in later["ml_movie_id"] if int(m) in ml2row}
    return rel - seen - {int(x) for x in excluded}


def recall(relevant: set, ranked, k: int | None = None) -> float:
    """Share of relevant rows in the first k of `ranked` (k None = all of it)."""
    if not relevant:
        return float("nan")
    top = list(ranked) if k is None else list(ranked)[:k]
    return len(relevant & {int(x) for x in top}) / len(relevant)


def ndcg(rec, lab: set) -> float:
    if not lab:
        return float("nan")
    rel = np.array([int(x) in lab for x in list(rec)[:K]], float)
    return float((rel * DISC[:len(rel)]).sum() / DISC[:min(len(lab), K)].sum())


def popularity_bucket(fame_pct: float) -> str:
    return "head" if fame_pct >= HEAD_PCT else ("torso" if fame_pct >= TAIL_PCT else "long_tail")


def decade(year) -> str:
    if year is None or not np.isfinite(year):
        return "unknown"
    return f"{int(year) // 10 * 10}s"


def ranked_pool(pool, norm, final, sources) -> tuple[np.ndarray, dict]:
    """Pool rows best first by blend score, and the rows each source proposed (norm > 0 means the source proposed it:
    candidate_pool gives a proposed film a percentile in (0, 1] and every other film 0)."""
    pool, final = np.asarray(pool), np.asarray(final)
    proposed = {s: set(pool[np.asarray(norm[i]) > 0].tolist()) for i, s in enumerate(sources)}
    return pool[np.argsort(-final, kind="stable")], proposed


def source_overlap(relevant: set, proposed: dict) -> dict:
    """Per source: (relevant rows it proposes, relevant rows ONLY it proposes); and relevant rows by number of sources."""
    out = {}
    for s, items in proposed.items():
        hit = relevant & items
        others = set().union(*[v for k, v in proposed.items() if k != s])
        out[s] = (len(hit), len(hit - others))
    counts: dict[int, int] = {}
    for r in relevant:
        c = sum(r in v for v in proposed.values())
        counts[c] = counts.get(c, 0) + 1
    return {"per_source": out, "by_n_sources": counts}


def micro_breakdown(items: pd.DataFrame, by: str, hit: str = "in_pool", min_n: int = 30) -> pd.DataFrame:
    """Recall per bucket over relevant items (micro: every relevant film counts once). Buckets under min_n -> 'other'."""
    d = items.copy()
    d[by] = d[by].astype(str)
    n = d.groupby(by)[hit].transform("size")
    d[by] = np.where(n >= min_n, d[by], "other")
    g = d.groupby(by)[hit].agg(["size", "mean"]).rename(columns={"size": "relevant", "mean": "recall"})
    return g.sort_values("relevant", ascending=False)


# ----------------------------------------------------------------------------- engine instrumentation (in memory only)
@contextlib.contextmanager
def instrumented(engine, per_source: int):
    """Run the real top_picks with `per_source` films per source, recording the pool it builds.

    Yields a dict that a top_picks call fills: the base pool from candidate_pool, then the rows added by
    _add_unavailable_candidates (first call: films without MovieLens factors; a second call, only when a tail channel is
    on: the long-tail channel). Both get `per_source`. Everything is restored on exit."""
    from cinematch_engine import online
    rec: dict = {}
    orig_cp = online.candidate_pool
    orig_add = engine._add_unavailable_candidates     # bound method of this instance

    def cp(scores, excluded, per_source_=None):
        pool, norm = orig_cp(scores, excluded, per_source=per_source)
        rec.clear()
        valid = pool[0] >= 0
        rec["calls"] = 0
        rec["base_pool"], rec["base_norm"] = pool[0][valid], norm[:, 0, valid]
        return pool, norm

    def add(st, scores, excl, pool, norm, final, w, per_source_=50, rows=None):
        n0 = len(pool)
        first = rec.get("calls", 0) == 0
        if first:
            rec["base_final"] = np.asarray(final).copy()
        p2, n2, f2 = orig_add(st, scores, excl, pool, norm, final, w, per_source=per_source, rows=rows)
        rec["non_movielens_extra" if first else "tail_channel"] = set(np.asarray(p2[n0:]).tolist())
        if first:
            rec["pool"], rec["final"] = np.asarray(p2), np.asarray(f2)
        rec["calls"] = rec.get("calls", 0) + 1
        return p2, n2, f2

    online.candidate_pool = cp
    engine._add_unavailable_candidates = add
    try:
        yield rec
    finally:
        online.candidate_pool = orig_cp
        engine.__dict__.pop("_add_unavailable_candidates", None)     # back to the class method


def run_picks(engine, st, scores, mode: str, tail=None):
    from cinematch_engine import rerank
    saved = rerank.MODES[mode]["tail_share"]
    if tail is not None:
        rerank.MODES[mode]["tail_share"] = tail
    try:
        return np.array([p["row"] for p in engine.top_picks(st, mode, k=K, scores=scores)])
    finally:
        rerank.MODES[mode]["tail_share"] = saved


def pool_and_picks(engine, st, scores, per_source: int, mode="familiar", tail=0.0):
    """One real top_picks call at this pool size: (ranked pool, per-source proposals, top-10 rows)."""
    from cinematch_engine.sources import SOURCES
    with instrumented(engine, per_source) as rec:
        picks = run_picks(engine, st, scores, mode, tail)
    if "pool" in rec:
        pool, final = rec["pool"], rec["final"]
    else:                                              # no availability map: the base pool is the pool
        pool, final = rec["base_pool"], rec.get("base_final", np.zeros(len(rec["base_pool"])))
    norm = np.zeros((len(SOURCES), len(pool)), np.float32)
    norm[:, :rec["base_norm"].shape[1]] = rec["base_norm"]
    ranked, proposed = ranked_pool(pool, norm, final, SOURCES)
    proposed["non_movielens_extra"] = rec.get("non_movielens_extra", set())
    return ranked, proposed, picks


def run_picks_sized(engine, st, scores, mode, per_source):
    """Top 10 of a shipped mode (with its own tail channel) at this pool size."""
    with instrumented(engine, per_source):
        return run_picks(engine, st, scores, mode)


def ild(engine, rows) -> float:
    x = engine.cat.content[np.asarray(rows)]
    s = (x @ x.T).toarray()
    n = len(rows)
    return float(1 - (s.sum() - np.trace(s)) / max(n * (n - 1), 1))


# ----------------------------------------------------------------------------- label steps (audit -> strict)
def _get(groups, part, u) -> pd.DataFrame:
    try:
        return groups[part].get_group(u)
    except KeyError:
        return EMPTY


def label_steps(tr, va, te, nm, ml2row, profile_rows: set, excluded) -> dict:
    """Audit labels -> strict labels, one change at a time (same profile, so the same pool)."""
    t = split_time(tr)
    pos = lambda d: {ml2row[int(m)] for m, y in zip(d.ml_movie_id, d.rating) if y >= POSITIVE and int(m) in ml2row}
    seen = {ml2row[int(m)] for m in tr.ml_movie_id if int(m) in ml2row}
    seen |= {ml2row[int(m)] for m, ts in zip(nm.ml_movie_id, nm.timestamp) if ts <= t and int(m) in ml2row}
    steps = {"audit": (pos(te) | pos(nm)) - profile_rows}
    steps["1_minus_everything_seen_before_T"] = steps["audit"] - seen
    steps["2_hold_out_ratings_after_T_only"] = (pos(te) | pos(nm[nm.timestamp > t])) - profile_rows - seen
    steps["3_plus_validation_positives"] = steps["2_hold_out_ratings_after_T_only"] | (pos(va[va.timestamp > t]) - seen)
    steps["strict"] = strict_relevant(pd.concat([tr, nm[nm.timestamp <= t]]), pd.concat([va, te, nm]), t, ml2row, excluded)
    return steps


# ----------------------------------------------------------------------------- the run
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--memory-users", type=int, default=15, help="users per regime whose top_picks calls are traced")
    ap.add_argument("--quick", action="store_true", help="skip the audit reproduction and the balanced mode")
    ap.add_argument("--tag", default="", help="suffix for the output files (e.g. 'latency')")
    a = ap.parse_args()

    from cinematch_engine.online import UserState
    from cinematch_engine.sources import SOURCES
    from pipeline.availability_calibration import build_engine, sample
    from pipeline.cold_eval import make_state, production_like
    from pipeline.common import PROCESSED

    t0 = time.time()
    engine, movies, f = build_engine()
    production_like(engine)
    ml2row, hold_rows, users, groups = sample(engine, movies, f, a.users, a.seed)
    va = pd.read_parquet(PROCESSED / "splits" / "val.parquet")
    groups["val"] = va[va.user_id.isin(users)].groupby("user_id")
    cat = engine.cat
    print(f"engine ready {time.time() - t0:.0f}s; users {len(users)}", flush=True)
    report = {"date": date.today().isoformat(), "users_sampled": int(len(users)), "seed": a.seed, "sizes": list(SIZES)}
    parts = lambda u: tuple(_get(groups, p, u) for p in ("train", "val", "test", "new"))

    # ---- 1. audit reproduction (pool at 50, the audit's own sampler), plus the label steps on the same pools
    if not a.quick:
        rep = {}
        for regime, (n_r, n_p) in AUDIT_REGIMES.items():
            vals: dict = {}
            t = time.time()
            for u in users:
                tr, vau, te, nm = parts(u)
                st = make_state(engine, ml2row, tr, len(tr) if n_r is None else n_r, n_p)
                if len(st.ratings) + len(st.picks) < 2:
                    continue
                steps = label_steps(tr, vau, te, nm, ml2row, set(st.ratings) | st.picks, engine.excluded(st))
                if not steps["audit"]:
                    continue
                ranked, _, _ = pool_and_picks(engine, st, engine.scores(st), 50)
                for step, lab in steps.items():
                    if lab:
                        vals.setdefault(step, []).append((recall(lab, ranked), len(lab)))
            rep[regime] = {k: {"pool_recall": round(float(np.mean([x[0] for x in v])), 4), "users": len(v),
                               "mean_relevant": round(float(np.mean([x[1] for x in v])), 1)} for k, v in vals.items()}
            print("audit", regime, json.dumps(rep[regime]), f"{time.time() - t:.0f}s", flush=True)
        report["audit_reproduction"] = rep

    # ---- 2-4. strict protocol: recall@K, per source, overlap, breakdowns, size sweep
    items, users_rows, src_rows, mem_rows = [], [], [], []
    modes = ("familiar",) if a.quick else ("familiar", "balanced")
    all_src = list(SOURCES) + ["non_movielens_extra"]
    for regime, n in STRICT_REGIMES.items():
        t = time.time()
        src_acc: dict = {}
        overlap_acc: dict = {}
        n_users = 0
        for ui, u in enumerate(users):
            tr, vau, te, nm = parts(u)
            prof = recent_profile(tr, n)
            st = UserState()
            st.ratings = {ml2row[int(m)]: float(y) for m, y in zip(prof.ml_movie_id, prof.rating) if int(m) in ml2row}
            st.behavioral_count = len(st.ratings)
            if len(st.ratings) < 2:
                continue
            tt = split_time(tr)
            lab = strict_relevant(pd.concat([tr, nm[nm.timestamp <= tt]]), pd.concat([vau, te, nm]), tt, ml2row,
                                  engine.excluded(st))
            if not lab:
                continue
            scores = engine.scores(st)
            measure = n_users < a.memory_users
            n_users += 1
            for size in SIZES:
                if measure:
                    tracemalloc.start()
                    tm = time.perf_counter()
                ranked, proposed, rec = pool_and_picks(engine, st, scores, size)
                if measure:
                    mem_rows.append({"regime": regime, "size": size, "seconds": time.perf_counter() - tm,
                                     "peak_mb": tracemalloc.get_traced_memory()[1] / 2**20})
                    tracemalloc.stop()
                pos_of = {int(r): i for i, r in enumerate(ranked)}
                by_mode = {"familiar": rec}
                for m in modes[1:]:
                    by_mode[m] = run_picks_sized(engine, st, scores, m, size)
                row = {"regime": regime, "size": size, "user": int(u), "stage": st.stage, "relevant": len(lab),
                       "pool_size": len(ranked), "pool_recall": recall(lab, ranked),
                       **{f"recall@{k}": recall(lab, ranked, k) for k in RECALL_AT}}
                for m, r in by_mode.items():
                    row[f"ndcg@10_{m}"] = ndcg(r, lab)
                    row[f"ild_{m}"] = ild(engine, r)
                    row[f"tail_share_{m}"] = float((cat.fame_pct[r] < TAIL_PCT).mean())
                    row[f"rows_{m}"] = r.tolist()
                users_rows.append(row)
                ov = source_overlap(lab, {s: proposed.get(s, set()) for s in all_src})
                acc = src_acc.setdefault(size, {s: [0, 0] for s in all_src})
                for s, (h, only) in ov["per_source"].items():
                    acc[s][0] += h
                    acc[s][1] += only
                oc = overlap_acc.setdefault(size, {})
                for c, v in ov["by_n_sources"].items():
                    oc[c] = oc.get(c, 0) + v
                for r in lab:
                    srcs = [s for s in all_src if r in proposed.get(s, set())]
                    items.append({"regime": regime, "size": size, "user": int(u), "row": int(r), "in_pool": r in pos_of,
                                  **{f"in_top{k}": pos_of.get(r, 10**9) < k for k in RECALL_AT},
                                  "n_sources": len(srcs), "sources": ",".join(srcs) or "none",
                                  "language": cat.language[r] or "unknown", "decade": decade(cat.year[r]),
                                  "primary_genre": cat.genres[r][0] if len(cat.genres[r]) else "none",
                                  "popularity": popularity_bucket(float(cat.fame_pct[r])),
                                  "movielens_linked": bool(cat.universe_of_row[r] >= 0)})
            if (ui + 1) % 100 == 0:
                print(f"  {regime} {ui + 1}/{len(users)} {time.time() - t:.0f}s", flush=True)
        for size, acc in src_acc.items():
            tot = sum(1 for x in items if x["regime"] == regime and x["size"] == size)
            for s, (h, only) in acc.items():
                src_rows.append({"regime": regime, "size": size, "source": s, "recall": h / max(tot, 1),
                                 "only_this_source": only / max(tot, 1)})
            report.setdefault("overlap_by_n_sources", {}).setdefault(regime, {})[str(size)] = {
                str(c): round(v / max(tot, 1), 4) for c, v in sorted(overlap_acc[size].items())}
        print(f"strict {regime} done {time.time() - t:.0f}s", flush=True)

    U, I, S, M = pd.DataFrame(users_rows), pd.DataFrame(items), pd.DataFrame(src_rows), pd.DataFrame(mem_rows)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = report["date"] + (f"-{a.tag}" if a.tag else "")
    I.to_parquet(OUT / f"recall-items-{stamp}.parquet", index=False)
    U.drop(columns=[c for c in U.columns if c.startswith("rows_")]).to_parquet(OUT / f"recall-users-{stamp}.parquet",
                                                                               index=False)
    sweep = {}
    for regime in STRICT_REGIMES:
        sweep[regime] = {}
        base = U[(U.regime == regime) & (U["size"] == 50)].set_index("user")
        for size in SIZES:
            d = U[(U.regime == regime) & (U["size"] == size)].set_index("user")
            if d.empty:
                continue
            e = {"users": int(len(d)), "mean_relevant": round(float(d.relevant.mean()), 1),
                 "mean_pool_size": round(float(d.pool_size.mean()), 1),
                 "pool_recall": round(float(d.pool_recall.mean()), 4),
                 **{f"recall@{k}": round(float(d[f"recall@{k}"].mean()), 4) for k in RECALL_AT}}
            for m in modes:
                diff = d[f"ndcg@10_{m}"] - base.loc[d.index, f"ndcg@10_{m}"]
                allr = np.concatenate([np.asarray(x) for x in d[f"rows_{m}"]])
                e[m] = {"ndcg@10": round(float(d[f"ndcg@10_{m}"].mean()), 4),
                        "ndcg_vs_50": round(float(diff.mean()), 4),
                        "se_diff": round(float(diff.std(ddof=1) / np.sqrt(len(diff))), 4) if size != 50 else 0.0,
                        "ild": round(float(d[f"ild_{m}"].mean()), 3),
                        "long_tail_share": round(float(d[f"tail_share_{m}"].mean()), 3),
                        "distinct_films": int(len(np.unique(allr)))}
            if len(M):
                mm = M[(M.regime == regime) & (M["size"] == size)]
                e["top_picks_traced_peak_mb_max"] = round(float(mm.peak_mb.max()), 1)
                e["top_picks_traced_peak_mb_mean"] = round(float(mm.peak_mb.mean()), 1)
                e["top_picks_seconds_mean"] = round(float(mm.seconds.mean()), 3)
                e["top_picks_seconds_p95"] = round(float(mm.seconds.quantile(0.95)), 3)
                e["timed_calls"] = int(len(mm))
            sweep[regime][str(size)] = e
    report["sweep"] = sweep
    report["sources"] = {r: {str(sz): {x.source: {"recall": round(x.recall, 4), "only_this_source": round(x.only_this_source, 4)}
                                       for x in S[(S.regime == r) & (S["size"] == sz)].itertuples()} for sz in SIZES}
                         for r in STRICT_REGIMES}
    br = {}
    for regime in STRICT_REGIMES:
        br[regime] = {}
        d50, d200 = (I[(I.regime == regime) & (I["size"] == s)] for s in (50, 200))
        for by in ("language", "decade", "primary_genre", "popularity", "movielens_linked"):
            t50, t200 = micro_breakdown(d50, by), micro_breakdown(d200, by)
            t50top = micro_breakdown(d50, by, hit="in_top100")
            br[regime][by] = {str(k): {"relevant": int(v.relevant), "pool_recall_50": round(float(v.recall), 4),
                                       "recall@100_at_50": round(float(t50top.recall.get(k, np.nan)), 4),
                                       "pool_recall_200": round(float(t200.recall.get(k, np.nan)), 4)}
                              for k, v in t50.iterrows()}
    report["breakdowns"] = br
    report["stage_check"] = {r: U[U.regime == r].stage.value_counts().to_dict() for r in STRICT_REGIMES}
    try:                                               # whole offline process (engine + harness), not a Render number
        import psutil
        mi = psutil.Process().memory_info()
        report["process_peak_rss_mb"] = round(getattr(mi, "peak_wset", mi.rss) / 2**20)
    except ImportError:
        pass
    report["seconds"] = round(time.time() - t0)
    (OUT / f"recall-{stamp}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("sweep", "seconds")}, indent=1), flush=True)


if __name__ == "__main__":
    main()
