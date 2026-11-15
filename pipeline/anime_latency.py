"""Serve-time cost of the anime model: kind_rank("anime") with and without it, by profile size.

    python -m pipeline.anime_latency --ratings data/raw/anime2023/rating.csv

Read-only, local database (as pipeline/mixed_home_replay.py). Fits the three served models in memory (nothing written)
and times the engine's own calls for list users with 1, 5, 15 and 60 liked anime the model knows.
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

log = get_logger("anime_latency")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default=str(RAW / "anime" / "rating.csv"))
    ap.add_argument("--per-size", type=int, default=75)
    a = ap.parse_args()
    engine, row_of_tmdb = load()
    cat = engine.cat
    lane_of = lanes_mod.lane_of_rows(cat)
    tmdb_of_row = {r: t for t, r in row_of_tmdb.items()}
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet", columns=["tmdb_id", "title", "original_title", "title_type"])
    pairs = am.as_pairs(pd.read_csv(a.ratings))
    films = {tmdb_of_row[r] for r in range(cat.n) if lane_of[r] == "anime_film" and r in tmdb_of_row}
    m = am.mapping(movies, films, sids=set(pairs["sid"].unique()))
    m = m[m["tmdb_id"].isin(row_of_tmdb)].reset_index(drop=True)
    m["row"] = m["tmdb_id"].map(row_of_tmdb)
    rows_of_col = np.array(sorted(set(m["row"])))
    col_of_row = {int(r): i for i, r in enumerate(rows_of_col)}
    x = am.matrix(pairs, {int(s): col_of_row[int(r)] for s, r in zip(m["sid"], m["row"])}, len(rows_of_col))
    served = {}
    for name, sm in am.fit(x).items():
        coo = sm.tocoo()
        served[name] = sp.csr_matrix((coo.data, (rows_of_col[coo.row], rows_of_col[coo.col])), shape=(cat.n, cat.n), dtype=np.float32)
    row_of_sid = dict(zip(m["sid"], m["row"]))
    p = pairs[pairs["sid"].isin(row_of_sid) & (pairs["score"] >= 7)].copy()
    p["row"] = p["sid"].map(row_of_sid)
    by = p.groupby("uid")["row"].apply(lambda s: sorted(set(int(v) for v in s)))
    rng = np.random.default_rng(3)
    out = {"memory_mib": round(sum(s.data.nbytes + s.indices.nbytes + s.indptr.nbytes for s in served.values()) / 2**20, 2)}
    for size in (1, 5, 15, 60):
        cand = [u for u, r in by.items() if len(r) >= size]
        users = rng.choice(cand, size=min(a.per_size, len(cand)), replace=False)
        t_off, t_on, t_order = [], [], []
        for u in users:
            liked = [int(v) for v in rng.choice(by[u], size=size, replace=False)]
            st = UserState(ratings={r: 9.0 for r in liked}, behavioral_count=size)
            cat.anime_sim = None
            t = time.perf_counter(); rows, _ = engine.kind_rank(st, "anime"); t_off.append(time.perf_counter() - t)
            cat.anime_sim = served
            t = time.perf_counter(); engine.kind_rank(st, "anime"); t_on.append(time.perf_counter() - t)
            t = time.perf_counter(); engine.anime_order(st, rows.tolist()); t_order.append(time.perf_counter() - t)
        ms = lambda v: {"median": round(1000 * float(np.median(v)), 2), "p95": round(1000 * float(np.percentile(v, 95)), 2)}
        out[f"liked_{size}"] = {"users": len(users), "kind_rank_without": ms(t_off), "kind_rank_with": ms(t_on),
                                "anime_order_alone": ms(t_order), "tier": engine.anime_scores(st)[0] if engine.anime_scores(st) else None}
        log.info("liked %d: %s", size, out[f"liked_{size}"])
    write_json(ROOT / "work" / "anime-rank-eval-2023" / "latency.json", out)


if __name__ == "__main__":
    main()
