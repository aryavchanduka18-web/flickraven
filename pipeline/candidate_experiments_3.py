"""Candidate experiments, round 3 (read-only): guarded strongest-likes blend (D3) and a shared-cutoff retrain (G).

    python -m pipeline.candidate_experiments_3 --users 400       # writes work/candidate-recall/experiments-3-<date>.json

Nothing in the engine, the served models (artifacts/models), calibration, Match %, Neon or Render changes. Part G fits
models IN MEMORY only; nothing is written to artifacts/.

Part D (spec relayed 2026-11-12): four arms at blend weights w = 0.25 and 0.5, every stage, in the Balanced mode the
site serves (Familiar kept as a secondary column):
  baseline     shipped
  D1_w         content = (1 - w) * full-profile content + w * content from ratings >= 9 (no guard)
  D2_w         D1_w + language/genre guard (as in #129)
  D3_w         D1_w + guard on language, genre, long tail and "rare" films
Long tail = the engine's own definition: `cat.fame_pct < rerank.TAIL_PCT` (80), i.e. outside the 20% most-voted films
of the catalog. Distinct films is a property of all users' lists together, so the guard protects a per-user proxy:
"rare" = a film the baseline recommends (Balanced top 10) to at most one user of that stage, or never. Each user's
list keeps at least the baseline's count of long-tail and rare films.
Acceptance (strict): later-liked films without MovieLens data in the pool up by more than 2 SE, AND NDCG@10, ILD,
long-tail share, distinct films and the non-English / Hindi / Korean / Japanese top-10 shares each within noise
(> -2 SE) or better, in EVERY stage. Distinct films: paired user bootstrap (1,000 resamples).

Part G: one shared global cutoff chosen to maximise usable users (>= 11 ratings before it and >= 1 eligible positive
after it), models fitted on ratings before the cutoff only (tuned settings and hybrid weights unchanged), 400 users
sampled from the usable ones (seed 11). Baseline per stage: pool recall, Recall@50/100/200, NDCG@10. The same users and
cutoff are also run on the served models, which saw some of these users' post-cutoff ratings (leaky reference).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from pipeline import candidate_experiments as ce
from pipeline import candidate_experiments_2 as c2
from pipeline import candidate_recall as cr

PER_SOURCE = 50
WEIGHTS = (0.25, 0.5)
METRICS = ("ndcg", "ild", "tail", "non_english", "hi", "ko", "ja")       # higher is better for each
BOOT = 1000


# ----------------------------------------------------------------------------- pure helpers (tested)
def ci95(delta: float, se: float) -> list:
    return [round(delta - 1.96 * se, 4), round(delta + 1.96 * se, 4)]


def tail_rare_extra(fame_pct, tail_pct: float, freq: dict):
    """Extra guard groups: 'tail' (engine's long-tail definition) and 'rare' (baseline shows it to <= 1 user)."""
    def extra(row: int) -> set:
        g = set()
        if fame_pct[row] < tail_pct:
            g.add("tail")
        if freq.get(int(row), 0) <= 1:
            g.add("rare")
        return g
    return extra


def frequencies(lists) -> dict:
    out: dict = {}
    for rows in lists:
        for r in rows:
            out[int(r)] = out.get(int(r), 0) + 1
    return out


def distinct_delta(base_lists, arm_lists, n_boot: int = BOOT, seed: int = 0) -> tuple:
    """Distinct films (arm - base) and its paired user-bootstrap SE."""
    d0 = len({r for x in arm_lists for r in x}) - len({r for x in base_lists for r in x})
    rng = np.random.default_rng(seed)
    n = len(base_lists)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        boots.append(len({r for i in idx for r in arm_lists[i]}) - len({r for i in idx for r in base_lists[i]}))
    return d0, float(np.std(boots, ddof=1)), float(np.mean(boots))


def accept(stage_metrics: dict) -> tuple:
    """Strict rule for one stage: non-ML pool recall up > 2 SE; every other metric > -2 SE (within noise or better)."""
    fails = []
    m = stage_metrics
    if not m["nonml_recall"]["delta"] > 2 * m["nonml_recall"]["se"]:
        fails.append("non-ML recall not up")
    for k in METRICS + ("distinct",):
        if m[k]["delta"] < -2 * m[k]["se"]:
            fails.append(f"{k} down")
    return not fails, fails


def usable_users(before: pd.DataFrame, after: pd.DataFrame, min_before: int = 11) -> np.ndarray:
    """Users with >= min_before ratings before the cutoff and >= 1 positive after it on a film not rated before."""
    nb = before.groupby("user_id").size()
    ok = set(nb[nb >= min_before].index)
    pos = after[(after.rating >= cr.POSITIVE) & after.user_id.isin(ok)]
    seen = set(zip(before.user_id[before.user_id.isin(ok)], before.ml_movie_id[before.user_id.isin(ok)]))
    fresh = {u for u, m in zip(pos.user_id, pos.ml_movie_id) if (u, m) not in seen}
    return np.array(sorted(fresh))


# ----------------------------------------------------------------------------- shared per-user setup
def _state(df, ml2row):
    from cinematch_engine.online import UserState
    st = UserState()
    st.ratings = {ml2row[int(m)]: float(y) for m, y in zip(df.ml_movie_id, df.rating) if int(m) in ml2row}
    st.behavioral_count = len(st.ratings)
    return st


def _metrics(engine, rows, lab, prefix: str, nonml_mask) -> dict:
    r = np.asarray(rows)
    mix = ce.top10_mix(r, engine.cat.language, nonml_mask, nonml_mask)
    return {f"ndcg_{prefix}": cr.ndcg(r, lab), f"ild_{prefix}": cr.ild(engine, r),
            f"tail_{prefix}": float((engine.cat.fame_pct[r] < cr.TAIL_PCT).mean()),
            **{f"{k}_{prefix}": mix[k] for k in ("non_english", "hi", "ko", "ja")}, f"rows_{prefix}": r.tolist()}


# ----------------------------------------------------------------------------- part D
def summarise_d(R: pd.DataFrame) -> dict:
    base = R[R.arm == "baseline"].set_index("user")
    out = {}
    for arm in R.arm.unique():
        x = R[R.arm == arm].set_index("user")
        b = base.loc[x.index]
        e = {"users": int(len(x)), "pool_recall": round(float(x.pool_recall.mean()), 4)}
        nd, nse = ce.paired(x.nonml_recall - b.nonml_recall)
        for m in ("balanced", "familiar"):
            s = {"nonml_recall": {"mean": round(float(x.nonml_recall.mean()), 4), "delta": round(nd, 4),
                                  "se": round(nse, 4), "ci95": ci95(nd, nse)}}
            for k in METRICS:
                d, se = ce.paired(x[f"{k}_{m}"] - b[f"{k}_{m}"])
                s[k] = {"mean": round(float(x[f"{k}_{m}"].mean()), 4), "delta": round(d, 4), "se": round(se, 4),
                        "ci95": ci95(d, se)}
            dd, dse, _ = distinct_delta(list(b[f"rows_{m}"]), list(x[f"rows_{m}"]))
            s["distinct"] = {"mean": int(len({r for v in x[f"rows_{m}"] for r in v})), "delta": dd,
                             "se": round(dse, 2), "ci95": ci95(dd, dse)}
            if arm != "baseline":
                ok, fails = accept(s)
                s["stage_verdict"] = "pass" if ok else "fail: " + ", ".join(fails)
            e[m] = s
        out[arm] = e
    return out


def run_d(engine, users, groups, ml2row, log) -> dict:
    from cinematch_engine.online import UserState
    cat = engine.cat
    nonml_mask = cat.universe_of_row < 0
    report = {}
    for stage, n in cr.STRICT_REGIMES.items():
        t = time.time()
        prepared = []
        for u in users:                                 # phase 1: who is evaluated, and the baseline lists
            tr, vau, te, nm = (cr._get(groups, p, u) for p in ("train", "val", "test", "new"))
            st = _state(cr.recent_profile(tr, n), ml2row)
            if len(st.ratings) < 2:
                continue
            tt = cr.split_time(tr)
            lab = cr.strict_relevant(pd.concat([tr, nm[nm.timestamp <= tt]]), pd.concat([vau, te, nm]), tt, ml2row,
                                     engine.excluded(st))
            if lab:
                prepared.append((u, st, lab))
        base_lists = [cr.run_picks_sized(engine, st, engine.scores(st), "balanced", PER_SOURCE).tolist()
                      for _, st, _ in prepared]
        extra = tail_rare_extra(cat.fame_pct, cr.TAIL_PCT, frequencies(base_lists))
        rows = []
        for u, st, lab in prepared:                     # phase 2: arms
            scores = engine.scores(st)
            nonml_lab = {r for r in lab if nonml_mask[r]}
            sub = ce.strong_ratings(st.ratings, "strong9")
            strong = None
            if sub and len(sub) < len(st.ratings):
                s2 = UserState()
                s2.ratings, s2.behavioral_count = sub, st.behavioral_count
                strong = engine.scores(s2)["content"]
            arms = {"baseline": scores}
            for w in WEIGHTS:
                sc = dict(scores)
                if strong is not None:
                    sc["content"] = c2.blend_content(scores["content"], strong, w)
                arms[f"D1_{w}"] = sc
            out = {}
            for arm, sc in arms.items():
                ranked, _, fam = cr.pool_and_picks(engine, st, sc, PER_SOURCE)
                bal = cr.run_picks_sized(engine, st, sc, "balanced", PER_SOURCE)
                out[arm] = (ranked, fam.tolist(), bal.tolist())
            b = out["baseline"]
            for w in WEIGHTS:
                ranked, fam, bal = out[f"D1_{w}"]
                rk = ranked.tolist()
                out[f"D2_{w}"] = (ranked, c2.mix_guard(fam, b[1], rk, cat.language, cat.genres),
                                  c2.mix_guard(bal, b[2], rk, cat.language, cat.genres))
                out[f"D3_{w}"] = (ranked, c2.mix_guard(fam, b[1], rk, cat.language, cat.genres, extra=extra),
                                  c2.mix_guard(bal, b[2], rk, cat.language, cat.genres, extra=extra))
            for arm, (ranked, fam, bal) in out.items():
                row = {"arm": arm, "user": int(u), "nonml_recall": cr.recall(nonml_lab, ranked),
                       "pool_recall": cr.recall(lab, ranked)}
                row.update(_metrics(engine, bal, lab, "balanced", nonml_mask))
                row.update(_metrics(engine, fam, lab, "familiar", nonml_mask))
                rows.append(row)
        report[stage] = summarise_d(pd.DataFrame(rows))
        log(f"D {stage} done {time.time() - t:.0f}s ({len(prepared)} users)")
    verdicts = {}
    for arm in report["established"]:
        if arm == "baseline":
            continue
        per_stage = {s: accept(report[s][arm]["balanced"]) for s in report}
        verdicts[arm] = {"win": all(ok for ok, _ in per_stage.values()),
                         "fails": {s: f for s, (ok, f) in per_stage.items() if not ok}}
    return {"stages": report, "verdict_balanced_all_stages": verdicts}


# ----------------------------------------------------------------------------- part G
def _set_popularity(engine, uni_pop):
    """production_like's popularity proxy, from the given universe popularity scores."""
    cat = engine.cat
    uni = cat.universe_rows
    pop = np.zeros(cat.n)
    pop[uni] = uni_pop
    rest = np.setdiff1d(np.arange(cat.n), uni)
    order = np.sort(cat.votes[uni])
    q = np.searchsorted(order, cat.votes[rest]) / len(order)
    pop[rest] = np.quantile(uni_pop, np.clip(q, 0, 1))
    cat.popularity = pop.astype(np.float32)


def _item_neighbors(data):
    """Stored item-CF neighbour lists (idx, vals) for the engine, fitted exactly as models_io does."""
    from cinematch_engine.models.item_cf import ItemCF
    from pipeline.models_io import STORED_ITEM_NEIGHBORS, settings
    ic = settings("item_cf")
    item = ItemCF(shrinkages=(ic["shrinkage"],), max_neighbors=STORED_ITEM_NEIGHBORS).fit(data.train, data.user_means())
    return item.neighbors[ic["shrinkage"]]


def run_g(engine0, movies, f, n_users: int, seed: int, log) -> dict:
    import joblib
    from cinematch_engine.availability import AvailabilityMap
    from cinematch_engine.data.splits import build_split
    from cinematch_engine.online import OnlineEngine
    from pipeline.common import ARTIFACTS, PROCESSED
    from pipeline.models_io import fit_sources

    sp_dir = PROCESSED / "splits"
    ml2row = {int(x): i for i, x in enumerate(movies["ml_movie_id"]) if pd.notna(x)}
    main = pd.concat([pd.read_parquet(sp_dir / f"{p}.parquet") for p in ("train", "val", "test")], ignore_index=True)
    newm = pd.read_parquet(sp_dir / "newmovie_test.parquet")
    main = main[main.ml_movie_id.isin(ml2row)]
    newm = newm[newm.ml_movie_id.isin(ml2row)]
    allr = pd.concat([main, newm], ignore_index=True)
    counts = {}
    for q in np.arange(0.50, 0.96, 0.05):
        c = int(np.quantile(main.timestamp, q))
        counts[c] = len(usable_users(main[main.timestamp <= c], allr[allr.timestamp > c]))
        log(f"G cutoff q={q:.2f} {datetime.fromtimestamp(c, tz=timezone.utc).date()} usable={counts[c]}")
    cutoff = max(counts, key=counts.get)
    cut_date = datetime.fromtimestamp(cutoff, tz=timezone.utc).date().isoformat()
    t = time.time()
    # exactly the served models' item space (the catalog has grown since they were fitted)
    items = pd.DataFrame({"ml_movie_id": np.asarray(f["item_ids"], dtype=np.int64), "tmdb_id": np.asarray(f["item_tmdb"])})
    train_df = main[(main.timestamp <= cutoff) & main.ml_movie_id.isin(set(items.ml_movie_id))]
    data = build_split(train_df, main[main.timestamp > cutoff], items, "global")
    assert (np.asarray(data.item_tmdb) == np.asarray(f["item_tmdb"])).all(), "item space differs from the served one"
    src = fit_sources(data, np.zeros((1, 1), np.float32))
    log(f"G models fitted on {len(train_df):,} ratings before {cut_date} in {time.time() - t:.0f}s")
    models = ARTIFACTS / "models"
    eng = OnlineEngine(engine0.cat, src, json.loads((models / "hybrid_weights.json").read_text(encoding="utf-8")),
                       joblib.load(models / "calibration.joblib"), _item_neighbors(data), data.train)
    eng.availability = AvailabilityMap.load(models / "availability_calibration.json")
    usable = np.intersect1d(usable_users(main[main.timestamp <= cutoff], allr[allr.timestamp > cutoff]),
                            np.asarray(data.user_ids))
    chosen = np.random.default_rng(seed).choice(usable, size=min(n_users, len(usable)), replace=False)
    by_user = allr[allr.user_id.isin(chosen)].groupby("user_id")
    main_ids = set(main.ml_movie_id)
    res = {"cutoff": cut_date,
           "usable_users_by_cutoff": {datetime.fromtimestamp(c, tz=timezone.utc).date().isoformat(): v
                                      for c, v in counts.items()},
           "usable_users": int(len(usable)), "users_sampled": int(len(chosen)),
           "train_ratings": int(len(train_df)), "stages": {}}
    for label, engine in (("cutoff_models", eng), ("served_models_leaky", engine0)):
        _set_popularity(engine, src.popularity if label == "cutoff_models" else f["popularity"])
        for stage, n in cr.STRICT_REGIMES.items():
            rows = []
            for u in chosen:
                d = by_user.get_group(u)
                before, after = d[d.timestamp <= cutoff], d[d.timestamp > cutoff]
                st = _state(cr.recent_profile(before[before.ml_movie_id.isin(main_ids)], n), ml2row)
                if len(st.ratings) < 2:
                    continue
                lab = cr.strict_relevant(before, after, cutoff, ml2row, engine.excluded(st))
                if not lab:
                    continue
                sc = engine.scores(st)
                ranked, _, fam = cr.pool_and_picks(engine, st, sc, PER_SOURCE)
                bal = cr.run_picks_sized(engine, st, sc, "balanced", PER_SOURCE)
                rows.append({"relevant": len(lab), "pool_size": len(ranked), "pool_recall": cr.recall(lab, ranked),
                             **{f"recall@{k}": cr.recall(lab, ranked, k) for k in cr.RECALL_AT},
                             "ndcg_balanced": cr.ndcg(bal, lab), "ndcg_familiar": cr.ndcg(fam, lab)})
            x = pd.DataFrame(rows)
            res["stages"].setdefault(stage, {})[label] = {
                "users": int(len(x)), "mean_relevant": round(float(x.relevant.mean()), 1),
                "mean_pool_size": round(float(x.pool_size.mean()), 1),
                **{k: round(float(x[k].mean()), 4) for k in
                   ("pool_recall", "recall@50", "recall@100", "recall@200", "ndcg_balanced", "ndcg_familiar")},
                "pool_recall_se": round(float(x.pool_recall.std(ddof=1) / np.sqrt(len(x))), 4)}
            log(f"G {label} {stage} pool recall {res['stages'][stage][label]['pool_recall']} ({len(x)} users)")
    _set_popularity(engine0, f["popularity"])
    return res


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--parts", default="D,G")
    a = ap.parse_args()
    from pipeline.availability_calibration import build_engine, sample
    from pipeline.cold_eval import production_like
    from pipeline.common import PROCESSED

    def log(msg):
        print(msg, flush=True)

    t0 = time.time()
    engine, movies, f = build_engine()
    production_like(engine)
    report = {"date": date.today().isoformat(), "seed": a.seed, "per_source": PER_SOURCE,
              "long_tail_definition": "cat.fame_pct < rerank.TAIL_PCT (80): outside the 20% most-voted catalog films"}
    cr.OUT.mkdir(parents=True, exist_ok=True)
    out = cr.OUT / f"experiments-3-{report['date']}.json"
    parts = set(a.parts.split(","))
    if "D" in parts:
        ml2row, hold_rows, users, groups = sample(engine, movies, f, a.users, a.seed)
        va = pd.read_parquet(PROCESSED / "splits" / "val.parquet")
        groups["val"] = va[va.user_id.isin(users)].groupby("user_id")
        report["D"] = run_d(engine, users, groups, ml2row, log)
        out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        log(json.dumps(report["D"]["verdict_balanced_all_stages"], indent=1))
    if "G" in parts:
        report["G"] = run_g(engine, movies, f, a.users, a.seed, log)
    report["seconds"] = round(time.time() - t0)
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log(f"done {report['seconds']}s")


if __name__ == "__main__":
    main()
