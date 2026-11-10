"""Long-tail channel: how much of the top 10 is long tail, and what it costs in NDCG.

    python -m pipeline.tail_eval --users 500

Users and held-out ratings come from the same splits as pipeline/availability_calibration.py. For each user the
profile is their whole training history (established) and the engine's Top Picks (k = 10) is scored against the
films they later rated 7+ (test split, plus the 500 hold-out films). Long tail = outside the 20% most-voted films of
the catalog (engine rerank.TAIL_PCT). Coverage = distinct films recommended to at least one user / films in the
MovieLens universe. NDCG is measured only against ratings that exist, so a long-tail film nobody in MovieLens rated
cannot score: the NDCG cost shown is an upper bound on the real cost.
"""
import argparse
import json

import numpy as np

from cinematch_engine import rerank
from cinematch_engine.online import UserState
from pipeline.availability_calibration import build_engine, sample
from pipeline.common import ARTIFACTS, get_logger, write_json

log = get_logger("tail_eval")
K = 10


def run(engine, ml2row, users, groups, mode: str, share: float, n_ratings=None) -> dict:
    rerank.MODES[mode]["tail_share"] = share
    disc = 1 / np.log2(np.arange(2, K + 2))
    nd, tail, pct, seen = [], [], [], []
    for u in users:
        r = groups["train"].get_group(u)
        if n_ratings:
            r = r.sample(min(n_ratings, len(r)), random_state=1)
        st = UserState()
        st.ratings = {ml2row[int(a)]: float(b) for a, b in zip(r.ml_movie_id, r.rating) if int(a) in ml2row}
        st.behavioral_count = len(st.ratings)
        if len(st.ratings) < 2:
            continue
        labeled = set()
        for part in ("test", "new"):
            g = groups[part].get_group(u)
            labeled |= {ml2row[int(a)] for a, b in zip(g.ml_movie_id, g.rating) if b >= 7 and int(a) in ml2row}
        if not labeled:
            continue
        rows = np.array([p["row"] for p in engine.top_picks(st, mode, k=K)])
        rel = np.array([x in labeled for x in rows], float)
        nd.append((rel * disc[:len(rows)]).sum() / disc[:min(len(labeled), K)].sum())
        tail.append(np.mean(engine.cat.fame_pct[rows] < rerank.TAIL_PCT))
        pct.append(engine.cat.fame_pct[rows].mean())
        seen.extend(rows.tolist())
    universe = set(engine.cat.universe_rows.tolist())
    return {"mode": mode, "tail_share_setting": share, "users": len(nd), "ndcg@10": round(float(np.mean(nd)), 4),
            "long_tail_share": round(float(np.mean(tail)), 4), "mean_fame_percentile": round(float(np.mean(pct)), 1),
            "coverage_of_movielens_films": round(len(set(seen) & universe) / len(universe), 4),
            "distinct_films": len(set(seen))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=500)
    a = ap.parse_args()
    engine, movies, f = build_engine()
    ml2row, _, users, groups = sample(engine, movies, f, a.users)
    saved = {m: c["tail_share"] for m, c in rerank.MODES.items()}
    out = []
    for mode in ("balanced", "discover"):
        for share in (0.0, 0.1, 0.2, 0.3, 0.4):
            res = run(engine, ml2row, users, groups, mode, share)
            log.info(json.dumps(res))
            out.append(res)
    for m, v in saved.items():
        rerank.MODES[m]["tail_share"] = v
    write_json(ARTIFACTS / "metrics" / "long_tail.json", out)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
