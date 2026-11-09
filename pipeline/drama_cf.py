"""Series-to-series similarities learned from real MyDramaList user lists (collaborative signal for Asian dramas).

    python -m pipeline.drama_cf

Data: the Kaggle "MyDramaList ratings" dataset (data/raw/mydramalist/df_pairs.parquet and df_shows.parquet, ~14M
ratings, ~80k users; Kaggle licence tag CDLA-Permissive 1.0 by the uploader; the lists originate from
MyDramaList.com, a leftover licence risk the site owner has accepted, see docs/decisions-log.md and the About page
credit). The user table (names) is never read. Nothing from the dataset is stored on the site: only the learned
series-to-series similarities (top 30 neighbours per series) are written, to artifacts/models/drama_neighbors.json,
and the offline check to artifacts/metrics/drama_cf_eval.json.

Only series that can be matched to the TMDB series of the catalog are used: normalized title (English, original or
any TMDB alternative title) and first-aired year within one year. The dataset covers Asian dramas up to about 2023,
so Western and newer series have no similarities and keep using content similarity and popularity.

A list entry counts as: scored 7 to 10 = liked (weight 0.6 to 1); completed without a score = 0.5; anything else is
ignored. Each user's row is scaled by 1/sqrt(items) so heavy users do not dominate, then item-item cosine with a
co-count shrinkage. The check hides one liked series per held-out user and asks whether it is in the top 10, against
plain popularity and against content similarity (the recommender's own content features).
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

from pipeline.common import ARTIFACTS, PROCESSED, RAW, get_logger, write_json
from pipeline.models_io import MODELS

log = get_logger("drama_cf")
SRC = RAW / "mydramalist"
NEIGHBORS = MODELS / "drama_neighbors.json"
EVAL = ARTIFACTS / "metrics" / "drama_cf_eval.json"
K = 30                 # neighbours kept per series
SHRINK = 25.0          # co-count shrinkage: similarity * c / (c + SHRINK)
MIN_ITEMS = 5          # a user needs this many usable entries
COMPLETED_WEIGHT = 0.5
ASIA = {"KR", "JP", "CN", "TW", "HK", "TH", "PH", "SG"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower().replace("&", "and")).strip()


def weights(pairs: pd.DataFrame) -> pd.Series:
    """List entry -> weight: score 7..10 liked (0.6..1), completed without a score 0.5, else 0 (ignored)."""
    score = pairs["score"].fillna(0)
    liked = 0.6 + 0.4 * (score.clip(upper=10) - 7) / 3
    return pd.Series(np.where(score >= 7, liked, np.where((score == 0) & pairs["completed"], COMPLETED_WEIGHT, 0.0)),
                     index=pairs.index)


def user_item_matrix(pairs: pd.DataFrame, items: list[int]) -> tuple[sp.csr_matrix, np.ndarray]:
    """Users x items matrix of entry weights for the given show ids; users with fewer than MIN_ITEMS entries are
    dropped; each row is scaled by 1/sqrt(entries). Returns (matrix, kept user ids)."""
    col = {a: i for i, a in enumerate(items)}
    r = pairs[pairs["sid"].isin(col)].copy()
    r["w"] = weights(r)
    r = r[r["w"] > 0]
    n = r.groupby("uid")["sid"].transform("size")
    r = r[n >= MIN_ITEMS]
    users = np.sort(r["uid"].unique())
    row = {u: i for i, u in enumerate(users)}
    x = sp.csr_matrix((r["w"].to_numpy(), (r["uid"].map(row).to_numpy(), r["sid"].map(col).to_numpy())),
                      shape=(len(users), len(items)))
    scale = 1 / np.sqrt(np.asarray((x > 0).sum(axis=1)).ravel())
    return (sp.diags(scale) @ x).tocsr(), users


def similarities(x: sp.csr_matrix) -> sp.csr_matrix:
    """Item-item cosine of the weighted matrix, shrunk by how many users have both shows, diagonal zero."""
    norms = np.sqrt(np.asarray(x.multiply(x).sum(axis=0)).ravel())
    xn = x @ sp.diags(1 / np.maximum(norms, 1e-9))
    cos = (xn.T @ xn).tocsr()
    present = (x > 0).astype(np.float32)
    both = (present.T @ present).tocsr()
    shrink = both.copy()
    shrink.data = shrink.data / (shrink.data + SHRINK)
    s = cos.multiply(shrink).tocsr()
    s.setdiag(0)
    s.eliminate_zeros()
    return s


def top_k(s: sp.csr_matrix, k: int = K) -> list[list[tuple[int, float]]]:
    out = []
    for i in range(s.shape[0]):
        row = s.getrow(i)
        order = np.argsort(-row.data)[:k]
        out.append([(int(row.indices[j]), float(row.data[j])) for j in order if row.data[j] > 0])
    return out


def evaluate(pairs: pd.DataFrame, items: list[int], content: sp.csr_matrix | None = None, seed: int = 7) -> dict:
    """Hide one liked series per held-out user; hit@10 of the learned similarities against plain popularity and,
    when `content` (one row per item) is given, against content similarity. 80% of users learn, 20% are tested."""
    x, users = user_item_matrix(pairs, items)
    rng = np.random.default_rng(seed)
    test = rng.random(len(users)) < 0.2
    s = similarities(x[~test])
    pop = np.asarray((x[~test] > 0).sum(axis=0)).ravel().astype(float)
    csim = None if content is None else (content @ content.T).tocsr()
    names = ["learned", "popularity"] + (["content"] if csim is not None else [])
    hits = dict.fromkeys(names, 0)
    n = 0
    for u in np.nonzero(test)[0]:
        row = x[u]
        entries = len(row.indices)
        original = row.data * np.sqrt(entries)                      # undo the 1/sqrt(entries) scaling
        liked = row.indices[original > COMPLETED_WEIGHT + 1e-6]     # scored 7+, not only completed
        if len(liked) < 5:
            continue
        held = int(rng.choice(liked))
        keep = row.indices[row.indices != held]
        seen = np.zeros(len(items), dtype=bool)
        seen[keep] = True
        scores = {"learned": np.asarray(s[keep].sum(axis=0)).ravel(), "popularity": pop.copy()}
        if csim is not None:
            scores["content"] = np.asarray(csim[keep].sum(axis=0)).ravel()
        for name, score in scores.items():
            score = np.where(seen, -np.inf, score)
            hits[name] += int(held in np.argpartition(-score, min(10, len(score) - 1))[:10])
        n += 1
    return {"test_users": n, **{f"hit@10_{k}": round(v / max(n, 1), 4) for k, v in hits.items()},
            "items": len(items), "train_users": int((~test).sum())}


def match_shows(shows: pd.DataFrame, series: pd.DataFrame, alts: dict[int, list[str]]) -> pd.DataFrame:
    """TMDB series -> MyDramaList id: normalized title (English, original or alternative) and year within one."""
    sh = shows[shows["kind"].isin(["Drama", "TV Show"])].copy()
    sh["n"] = sh["title"].map(norm)
    idx: dict[str, list] = {}
    for r in sh.itertuples():
        idx.setdefault(r.n, []).append(r)
    rows = []
    for r in series.itertuples():
        best = None
        for t in [r.title, r.original_title, *alts.get(int(r.tmdb_id), [])]:
            for c in idx.get(norm(t), []):
                if (pd.isna(r.year) or abs(c.year - r.year) <= 1) and (best is None or c.ratings > best.ratings):
                    best = c
        if best is not None:
            rows.append({"tmdb_id": int(r.tmdb_id), "sid": int(best.sid)})
    return pd.DataFrame(rows, columns=["tmdb_id", "sid"]).drop_duplicates("sid")


def content_rows(tmdb_ids: list[int]) -> sp.csr_matrix:
    """The recommender's content features of these series, one L2-normalized row each, in the order given."""
    x = sp.load_npz(MODELS / "content_matrix.npz").tocsr()
    rows = pd.read_parquet(MODELS / "content_rows.parquet")
    row_of = dict(zip(rows["tmdb_id"], rows["row"]))
    return x[[row_of[t] for t in tmdb_ids]]


def main() -> None:
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet",
                             columns=["tmdb_id", "title", "original_title", "year", "title_type", "countries"])
    series = movies[(movies["title_type"] == "series") & movies["countries"].map(lambda c: bool(ASIA & set(c)))]
    alts = {}
    for tid in series["tmdb_id"]:
        f = RAW / "tmdb_alt_titles" / f"{tid}.json"
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        alts[int(tid)] = [x["title"] for x in (d or {}).get("results", [])]
    shows = pd.read_parquet(SRC / "df_shows.parquet")
    for c in ("kind", "title"):
        shows[c] = shows[c].astype(str)
    pairs = pd.read_parquet(SRC / "df_pairs.parquet", columns=["uid", "sid", "score", "completed"])
    shows["ratings"] = shows["sid"].map(pairs["sid"].value_counts()).fillna(0)
    mapping = match_shows(shows, series, alts)
    mapping.to_csv(PROCESSED / "drama_mdl_map.csv", index=False)
    log.info("matched %d of %d Asian series to the dataset", len(mapping), len(series))
    items = mapping["sid"].tolist()
    result = evaluate(pairs, items, content=content_rows(mapping["tmdb_id"].tolist()))
    log.info("offline check: %s", result)
    x, users = user_item_matrix(pairs, items)
    tmdb_of = dict(zip(mapping["sid"], mapping["tmdb_id"]))
    neighbors = {str(tmdb_of[items[i]]): [[tmdb_of[items[j]], round(v, 4)] for j, v in nb]
                 for i, nb in enumerate(top_k(similarities(x)))}
    MODELS.mkdir(parents=True, exist_ok=True)
    write_json(NEIGHBORS, {"settings": {"k": K, "shrink": SHRINK, "min_items": MIN_ITEMS,
                                        "completed_weight": COMPLETED_WEIGHT},
                           "series": len(neighbors), "neighbors": neighbors})
    write_json(EVAL, {**result, "matched_series": len(mapping), "users_used": int(len(users))})
    log.info("wrote similarities for %d series (no users kept)", len(neighbors))


if __name__ == "__main__":
    main()
