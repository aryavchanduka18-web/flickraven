"""More Like This neighbours: build them, and measure them against the old formula.

    python -m pipeline.similar_titles              # build artifacts/models/similar_titles.npz (about 1-2 minutes)
    python -m pipeline.similar_titles --evaluate   # also re-run the comparison and write artifacts/metrics/similar_titles.json
    python -m pipeline.similar_titles --tune       # the weight search that chose DEFAULT_WEIGHTS (tune half + validation users)

Two measurements (neither is perfect, so both are reported):
1. Hand-written test set (pipeline/curated/similar_testset.yaml): 27 anchors across Hollywood, Hindi, Tamil,
   Telugu, Korean, Japanese, Spanish films, US/UK/Indian/Korean series and anime, each with titles a viewer
   would call similar. Recall@20 = share of those titles in the top 20. Half the anchors ("tune") chose the
   weights; the other half ("test") is only reported.
2. Held-out MovieLens users: a film the user rated 8+ in training is the anchor; the films they rated 7+ in the
   validation (tuning) or test (report) split are the targets. Each target competes with 100 films of the same
   fame band, so popularity alone cannot win; hit@10 = share of targets ranked in the top 10 of 101 (random 9.9%).
   This measures "people who liked A also liked B", which rewards same-era films more than same-story films.
Only MovieLens films can be measured by (2); series, anime and Indian films only by (1).
"""
import argparse

import numpy as np
import pandas as pd
import scipy.sparse as sp
import yaml

from cinematch_engine import similar as S
from pipeline.common import ARTIFACTS, PROCESSED, ROOT, get_logger, write_json


log = get_logger("similar_titles")
MODELS = ARTIFACTS / "models"
OUT = MODELS / "similar_titles.npz"
TESTSET = ROOT / "pipeline" / "curated" / "similar_testset.yaml"
OLD = {"genre": 0.3, "language": 0.2, "era": 0.1, "era_scale": 12.0}


def load():
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet").reset_index(drop=True)
    credits = pd.read_parquet(PROCESSED / "credits_clean.parquet")
    return movies, credits


def build() -> S.SimilarFeatures:
    movies, credits = load()
    f = S.build_features(movies, credits)
    table = S.build_table(f)
    np.savez_compressed(OUT, **table)
    log.info("More Like This neighbours for %d titles written to %s", f.n, OUT)
    return f


# ------------------------------------------------------------------ evaluation
def _old_scorer(f: S.SimilarFeatures):
    """The formula served until 2026-11-10 (OnlineEngine.similar): content cosine + 0.3 genre Jaccard
    + 0.2 same language + 0.1 exp(-year gap / 12), over the whole catalog with no type filter."""
    rows = pd.read_parquet(MODELS / "content_rows.parquet")
    x = sp.load_npz(MODELS / "content_matrix.npz").tocsr()
    pos = dict(zip(rows["tmdb_id"], rows["row"]))
    x = x[[pos[t] for t in f.tmdb_ids]]

    def score(a: int, cand: np.ndarray) -> np.ndarray:
        sig = S.signals(f, a, cand)
        cos = np.asarray((x[cand] @ x[a].T).todense()).ravel()
        gap = np.nan_to_num(np.abs(f.year[cand] - f.year[a]))
        return cos + OLD["genre"] * sig["genre"] + OLD["language"] * sig["language"] + OLD["era"] * np.exp(-gap / OLD["era_scale"])
    return score


def _new_scorer(f, weights):
    return lambda a, cand: S.combine(S.signals(f, a, cand), weights)


def testset(f: S.SimilarFeatures, movies: pd.DataFrame) -> list[dict]:
    out = []
    for t in yaml.safe_load(TESTSET.read_text()):
        s = movies[movies["title"] == t["anchor"]]
        if t.get("year"):
            s = s[s["year"] == t["year"]]
        if t.get("type"):
            s = s[s["title_type"] == t["type"]]
        if s.empty:
            log.warning("test set anchor not in the catalog: %s", t["anchor"])
            continue
        a = int(s.sort_values("tmdb_vote_count", ascending=False).index[0])
        exp, missing = [], []
        for e in t["expected"]:
            x = movies[(movies["title"] == e) & (movies["title_type"] == f.kind[a])]
            (exp.append(int(x.sort_values("tmdb_vote_count", ascending=False).index[0])) if len(x) else missing.append(e))
        out.append({"anchor": t["anchor"], "row": a, "split": t["split"], "expected": exp, "missing": missing})
    return out


def recall(cases, scorer, f, split, k=20, same_type=True):
    vals = []
    for c in cases:
        if c["split"] != split or not c["expected"]:
            continue
        a = c["row"]
        cand = np.nonzero(f.kind == f.kind[a])[0] if same_type else np.arange(f.n)
        cand = cand[cand != a]
        sc = scorer(a, cand)
        top = cand[np.argsort(-sc, kind="stable")[:k]]
        vals.append(len(set(top.tolist()) & set(c["expected"])) / len(c["expected"]))
    return float(np.mean(vals))


def movielens_users(f, split: str, n: int, seed: int):
    fitted = np.load(MODELS / "fitted.npz")
    row_of = {t: i for i, t in enumerate(f.tmdb_ids)}
    universe = np.array([row_of[t] for t in fitted["item_tmdb"]])
    ml2u = {int(x): i for i, x in enumerate(fitted["item_ids"])}
    uid = {int(u): i for i, u in enumerate(fitted["user_ids"])}
    train = sp.load_npz(MODELS / "train_ratings.npz").tocsr()
    t = pd.read_parquet(PROCESSED / "splits" / f"{split}.parquet")
    t = t[t["rating"] >= 7].assign(u=lambda d: d["ml_movie_id"].map(ml2u)).dropna(subset=["u"])
    targets = t.groupby("user_id")["u"].apply(lambda s: {int(x) for x in s})
    rng = np.random.default_rng(seed)
    ids = [u for u in targets.index if u in uid]
    rng.shuffle(ids)
    out = []
    for u in ids:
        r = train[uid[u]]
        liked = r.indices[r.data >= 8]
        tg = targets[u] - set(r.indices.tolist())
        if len(liked) and tg:
            out.append((int(rng.choice(liked)), set(r.indices.tolist()), tg))
        if len(out) >= n:
            break
    return universe, out


def fame_matched_hits(f, universe, samples, scorer, seed=0, negatives=100, k=10, per_user=5, bands=50):
    votes = f.fame[universe]
    band = np.minimum((np.argsort(np.argsort(votes)) * bands) // len(universe), bands - 1)
    members = [np.nonzero(band == b)[0] for b in range(bands)]
    rng, hits, cache = np.random.default_rng(seed), [], {}
    for a, seen, tg in samples:
        if a not in cache:
            cache[a] = scorer(int(universe[a]), universe)
        sc = cache[a]
        for t in [sorted(tg)[i] for i in rng.permutation(len(tg))[:per_user]]:
            neg = [x for x in rng.choice(members[band[t]], size=negatives + 20, replace=False)
                   if x not in seen and x not in tg and x != a][:negatives]
            ties = int((sc[neg] == sc[t]).sum())
            hits.append((sc[neg] > sc[t]).sum() + rng.integers(0, ties + 1) < k)
    return float(np.mean(hits))


def evaluate(f: S.SimilarFeatures) -> dict:
    movies, _ = load()
    cases = testset(f, movies)
    old, new = _old_scorer(f), _new_scorer(f, S.DEFAULT_WEIGHTS)
    res = {"weights": S.DEFAULT_WEIGHTS, "testset_missing_titles": {c["anchor"]: c["missing"] for c in cases if c["missing"]}}
    for split in ("tune", "test"):
        res[f"handwritten_{split}_recall@20"] = {
            "old_formula": recall(cases, old, f, split, same_type=False),
            "new": recall(cases, new, f, split)}
    universe, test_users = movielens_users(f, "test", 2000, seed=7)
    res["movielens_test_fame_matched_hit@10"] = {
        "random": 10 / 101, "old_formula": fame_matched_hits(f, universe, test_users, old, seed=3),
        "new": fame_matched_hits(f, universe, test_users, new, seed=3), "users": len(test_users)}
    res["examples"] = {}
    for c in cases:
        a = c["row"]
        cand = np.arange(f.n)[np.arange(f.n) != a]
        old_top = cand[np.argsort(-old(a, cand), kind="stable")[:10]]
        new_top = S.neighbours(f, a, S.DEFAULT_WEIGHTS, 10)[0]
        res["examples"][c["anchor"]] = {"old": [movies["title"][x] for x in old_top],
                                        "new": [movies["title"][x] for x in new_top]}
    write_json(ARTIFACTS / "metrics" / "similar_titles.json", res)
    log.info("hand-written test half recall@20: old %.3f new %.3f; MovieLens test hit@10: old %.3f new %.3f",
             res["handwritten_test_recall@20"]["old_formula"], res["handwritten_test_recall@20"]["new"],
             res["movielens_test_fame_matched_hit@10"]["old_formula"], res["movielens_test_fame_matched_hit@10"]["new"])
    return res


def tune(f: S.SimilarFeatures, trials: int = 400, seed: int = 0) -> list:
    """Random search over the weight grid on the tune half; a setting is kept only if it is not worse than the
    old formula on the MovieLens validation users (never the test split)."""
    movies, _ = load()
    cases = testset(f, movies)
    grid = {"keywords": [0.25, 0.5, 1, 1.5], "plot": [0.25, 0.5, 1], "topic": [0.25, 0.5, 1, 1.5], "genre": [0.1, 0.25, 0.5],
            "people": [0.25, 0.5, 1], "language": [0.1, 0.25, 0.5], "era": [0, 0.1, 0.2, 0.3], "quality": [0.1, 0.25, 0.4, 0.6]}
    rng = np.random.default_rng(seed)
    tried = []
    for _ in range(trials):
        w = {k: float(rng.choice(v)) for k, v in grid.items()}
        tried.append((recall(cases, _new_scorer(f, w), f, "tune"), w))
    tried.sort(key=lambda x: -x[0])
    universe, val_users = movielens_users(f, "val", 1500, seed=1)
    floor = fame_matched_hits(f, universe, val_users, _old_scorer(f))
    for r, w in tried[:20]:
        hit = fame_matched_hits(f, universe, val_users, _new_scorer(f, w))
        log.info("tune recall %.3f  validation hit %.3f (old %.3f)  %s", r, hit, floor, w)
        if hit >= floor:
            log.info("chosen: %s", w)
            return w
    return S.DEFAULT_WEIGHTS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--tune", action="store_true")
    a = ap.parse_args()
    f = build()
    if a.tune:
        tune(f)
    if a.evaluate:
        evaluate(f)


if __name__ == "__main__":
    main()
