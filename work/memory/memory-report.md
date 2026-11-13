# Render memory (512 MB free plan): measurement and free reductions (2026-11-14)

All measurement was offline:
- The real production Docker image, run locally on Linux (Docker Desktop) with `--memory=512m`.
- The same `deploy/start.sh` (alembic, bundle step, uvicorn with `PRELOAD_ENGINE=true`), the Dockerfile's
  `OMP/OPENBLAS/MKL_NUM_THREADS=1` and `MALLOC_ARENA_MAX=2`.
- The local database and local artifacts. Neon and Render were not touched.

Memory is the cgroup's `memory.current` / `memory.peak`, which is what the container limit counts. Scripts:
`work/memory/docker_measure.py` and `work/memory/measure_memory.py`. Raw numbers: `docker-before.json`,
`docker-after.json`, `memory-before.json`, `memory-after.json`.

## Result

| Stage (Linux, 512 MB cap) | Before | After | Saved |
|---|---|---|---|
| Engine loaded, first Home | 415 MB | 357 MB | **−58 MB** |
| After Perfect Pick, series, anime and 20 mixed requests | 418 MB | 362 MB | **−56 MB** |
| Peak (start-up load) | 456 MB | 420 to 432 MB | −24 to −36 MB |

The peak varies about ±10 MB from run to run. Headroom under 512 MB went from about 56 MB to about 80 to 90 MB at the
peak, and to about 150 MB in steady state.

The peak still happens while the engine loads, from temporary copies. Locally the catalogue comes from the full SQL
query, because there is no `catalog_snapshot.parquet` in the local artifacts. Render's bundle carries the snapshot,
which reads far less, so production's start peak should be lower than measured here.

## What changed (no change to any recommendation)

1. **`train_csc` removed** (the engine's 23 MB float32 CSC copy of the training matrix). It was only used by
   `neighbor_votes` (the "N people with similar taste rated this 8+" explanation). It is replaced by
   `online.item_raters`: the CF sources' item x user index arrays, which already exist, plus the ratings as `uint8`
   (2.9 MB). The ratings are rebuilt exactly from the centred matrix and each user's mean, so no transposed copy is
   made at start. This is checked against the old CSC column for all 9,495 items: 0 mismatches. A test covers it.
2. **Interned genre, keyword and language strings** in the catalogue: one string object per distinct value instead of
   one per occurrence. Keywords went from 17.3 to 9.8 MB and genres from 6.7 to 3.1 MB. The values are identical.
3. **Each `.npz` array read once.** Every `np.load(npz)["x"]` decompresses a new full copy. The item-neighbour arrays
   were read twice, and `similar_titles.npz`'s `comps` array was decompressed again on every loop iteration.
4. **After the one-off load:** `gc.collect()` and glibc `malloc_trim(0)`, so freed temporary memory goes back to the
   OS instead of staying counted against the container. This only applies on Linux.

Tests: engine 95, pipeline 114 and API 338 passed.

## Why Render restarts

Render's logs and events are not accessible from here (the Render connector is not authorised).

What the measurements show:
- The app never exceeded 512 MB in these runs (`OOMKilled: false`).
- But it sat at 418 MB steady with a 456 MB peak. Python's memory fragments over hours of traffic, and on the free plan
  any spike, such as several concurrent requests, a big Perfect Pick or the daily cleanup, has only about 50 MB of
  room. So out-of-memory kills during normal running are likely. The highest point is the engine load at start.
- If the start peak alone tips over 512 MB, the result is a restart loop: start, load, OOM, restart.

To confirm, check Render dashboard → service → Events: "Out of memory (used over 512Mi)" means OOM, while "Health check
failed" or a timeout means something else.

## Further free options, not done (they need a separate decision)

| Option | Saving | Risk / cost |
|---|---|---|
| Drop scikit-learn at serve time (it is only used for `IsotonicRegression` in a per-request fit and to unpickle `calibration.joblib`) by porting both to numpy | ~55 MB of import memory | Medium: the numbers must match sklearn exactly, so it needs an equality test |
| Compute `cf_sq_t` (squared centred values, 11.6 MB) on the fly | ~12 MB | Low to medium: code change in user-CF scoring |
| Store `similar_table` comps as a smaller dtype, or drop them if unused | up to ~10 MB | Low |
| Lazy-load rarely used JSONs (`ai_similar.json` 3.5 MB on disk is several times that in memory) | ~10 to 20 MB | Low |
| Move the daily cleanup out of the web process | removes a spike | Low |
