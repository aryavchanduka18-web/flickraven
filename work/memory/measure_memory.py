"""Measure the API's memory like production (offline, local Docker database, no Neon, no Gemini call).

    $env:PYTHONUTF8=1; $env:OMP_NUM_THREADS=1; $env:OPENBLAS_NUM_THREADS=1; $env:MKL_NUM_THREADS=1
    .\.venv\Scripts\python.exe work/memory/measure_memory.py [--label before]

Stages (process RSS = working set on Windows, peak = peak working set):
  imports -> load_engine -> Home (guest with 30 ratings) -> Perfect Pick -> Tonight -> series/anime rails
  -> More Like This -> 20 mixed requests -> gc.
Then a size table of every large object the engine keeps (numpy / scipy sparse / python lists and dicts).
Writes work/memory/memory-<label>.json. The assistant chat is not called (it would spend Gemini quota); its server
work is a prompt build plus one HTTP call, not model memory.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
os.environ.setdefault("PRELOAD_ENGINE", "false")
os.environ.setdefault("RUN_CLEANUP", "false")
PROC = psutil.Process()


def mb(x) -> float:
    return round(x / 2**20, 1)


def rss() -> dict:
    mi = PROC.memory_info()
    return {"rss_mb": mb(mi.rss), "peak_mb": mb(getattr(mi, "peak_wset", mi.rss))}


def deep_size(o, seen=None, depth=0) -> int:
    """Approximate bytes held by o (numpy/scipy aware; big containers sampled)."""
    import numpy as np
    import scipy.sparse as sp
    seen = seen if seen is not None else set()
    if id(o) in seen or depth > 6:
        return 0
    seen.add(id(o))
    if isinstance(o, np.ndarray):
        extra = 0
        if o.dtype == object and o.size:
            flat = o.ravel()
            sample = flat[:: max(1, o.size // 2000)]
            extra = int(sum(deep_size(x, seen, depth + 1) for x in sample) * o.size / len(sample))
        return int(o.nbytes) + extra
    if sp.issparse(o):
        return sum(int(getattr(o, a).nbytes) for a in ("data", "indices", "indptr") if hasattr(o, a))
    if isinstance(o, (str, bytes, int, float, bool)) or o is None:
        return sys.getsizeof(o)
    if isinstance(o, dict):
        items = list(o.items())
        if len(items) > 5000:
            sample = items[:: max(1, len(items) // 2000)]
            per = sum(deep_size(k, seen, depth + 1) + deep_size(v, seen, depth + 1) for k, v in sample) / len(sample)
            return sys.getsizeof(o) + int(per * len(items))
        return sys.getsizeof(o) + sum(deep_size(k, seen, depth + 1) + deep_size(v, seen, depth + 1) for k, v in items)
    if isinstance(o, (list, tuple, set, frozenset)):
        items = list(o)
        if len(items) > 5000:
            sample = items[:: max(1, len(items) // 2000)]
            return sys.getsizeof(o) + int(sum(deep_size(x, seen, depth + 1) for x in sample) * len(items) / len(sample))
        return sys.getsizeof(o) + sum(deep_size(x, seen, depth + 1) for x in items)
    if hasattr(o, "__dict__"):
        return sys.getsizeof(o) + deep_size(vars(o), seen, depth + 1)
    return sys.getsizeof(o)


def components(engine) -> list:
    out = []
    for owner, obj in (("engine", engine), ("catalog", engine.cat), ("sources", engine.src)):
        for k, v in vars(obj).items():
            if owner == "engine" and k in ("cat", "src"):
                continue
            n = deep_size(v)
            if n > 256 * 1024:
                out.append({"object": f"{owner}.{k}", "mb": mb(n), "type": type(v).__name__})
    return sorted(out, key=lambda r: -r["mb"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="before")
    a = ap.parse_args()
    stages = {"start": rss()}
    t0 = time.time()
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.services import recommender as rec
    stages["after_imports"] = rss()
    with SessionLocal() as db:
        engine = rec.load_engine(db)
    stages["after_load_engine"] = rss()
    gc.collect()
    stages["after_load_engine_gc"] = rss()
    comps = components(engine)
    cat = engine.cat
    with TestClient(app) as c:
        assert c.post("/api/auth/guest").status_code in (200, 201)
        order = sorted(range(cat.n), key=lambda r: -float(cat.votes[r]))
        films = [int(cat.movie_ids[r]) for r in order if cat.kind[r] == "movie"][:30]
        for i, mid in enumerate(films):
            c.put(f"/api/ratings/{mid}", json={"rating": 6 + (i % 5)})
        stages["after_30_ratings"] = rss()
        assert c.get("/api/recs/home").status_code == 200
        stages["after_home"] = rss()
        c.post("/api/recs/perfect-pick", json={"kind": "movie", "genres": ["Crime"], "mood": None})
        stages["after_perfect_pick"] = rss()
        from cinematch_engine.tonight import moods
        c.post("/api/recs/tonight", json={"mood": sorted(moods())[0]})
        stages["after_tonight"] = rss()
        c.get("/api/recs/series-rails")
        c.get("/api/recs/anime")
        stages["after_series_anime"] = rss()
        c.get(f"/api/movies/{films[0]}/similar")
        stages["after_more_like_this"] = rss()
        paths = ["/api/recs/home", "/api/recs/kind/tv", "/api/recs/series-rails", "/api/recs/anime",
                 "/api/search?q=love", f"/api/movies/{films[3]}/similar", "/api/me/taste-dna", "/api/recs/surprise",
                 "/api/discover/options", "/api/me/report"]
        for i in range(20):
            c.get(paths[i % len(paths)])
        stages["after_20_mixed"] = rss()
    gc.collect()
    stages["after_final_gc"] = rss()
    out = {"label": a.label, "seconds": round(time.time() - t0, 1), "stages": stages, "components": comps,
           "threads": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}}
    p = ROOT / "work" / "memory" / f"memory-{a.label}.json"
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for k, v in stages.items():
        print(f"{k:24s} rss {v['rss_mb']:7.1f} MB   peak {v['peak_mb']:7.1f} MB")
    print("\nlargest engine objects:")
    for r in comps[:25]:
        print(f"  {r['mb']:7.1f} MB  {r['object']}  ({r['type']})")


if __name__ == "__main__":
    main()
