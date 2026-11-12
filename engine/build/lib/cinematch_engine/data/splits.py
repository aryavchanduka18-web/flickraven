"""Load the rating splits into index-based sparse matrices (the evaluation universe).

The evaluation universe is part A of the catalog minus the new-movie holdout films
(spec section 4.2 and 12): only films with MovieLens ratings that the models are allowed to see.
"""
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp


@dataclass
class SplitData:
    user_ids: np.ndarray          # MovieLens user id per user index
    item_ids: np.ndarray          # MovieLens movie id per item index
    item_tmdb: np.ndarray         # TMDB id per item index
    train: sp.csr_matrix          # users x items, ratings 1..10 (float32), 0 = not rated
    eval_df: pd.DataFrame         # held-out ratings: columns u, i, rating (index space)
    split: str

    @property
    def n_users(self) -> int:
        return self.train.shape[0]

    @property
    def n_items(self) -> int:
        return self.train.shape[1]

    def train_indicator(self) -> sp.csr_matrix:
        ind = self.train.copy()
        ind.data = np.ones_like(ind.data)
        return ind

    def user_means(self) -> np.ndarray:
        counts = np.diff(self.train.indptr)
        sums = np.asarray(self.train.sum(axis=1)).ravel()
        return np.where(counts > 0, sums / np.maximum(counts, 1), 0).astype(np.float32)

    def item_counts(self) -> np.ndarray:
        return np.diff(self.train.tocsc().indptr)


def build_split(train: pd.DataFrame, held: pd.DataFrame, items: pd.DataFrame, split: str) -> SplitData:
    """train/held: user_id, ml_movie_id, rating. items: ml_movie_id, tmdb_id (the universe)."""
    items = items.sort_values("ml_movie_id").reset_index(drop=True)
    item_index = pd.Series(np.arange(len(items)), index=items["ml_movie_id"].to_numpy())
    train = train[train["ml_movie_id"].isin(item_index.index)]
    user_ids = np.sort(train["user_id"].unique())
    user_index = pd.Series(np.arange(len(user_ids)), index=user_ids)
    rows = user_index.loc[train["user_id"].to_numpy()].to_numpy()
    cols = item_index.loc[train["ml_movie_id"].to_numpy()].to_numpy()
    mat = sp.csr_matrix((train["rating"].to_numpy(np.float32), (rows, cols)),
                        shape=(len(user_ids), len(items)), dtype=np.float32)
    held = held[held["user_id"].isin(user_index.index) & held["ml_movie_id"].isin(item_index.index)]
    eval_df = pd.DataFrame({
        "u": user_index.loc[held["user_id"].to_numpy()].to_numpy(),
        "i": item_index.loc[held["ml_movie_id"].to_numpy()].to_numpy(),
        "rating": held["rating"].to_numpy(np.float32),
    })
    return SplitData(user_ids, items["ml_movie_id"].to_numpy(), items["tmdb_id"].to_numpy(), mat, eval_df, split)


SITE_FEEDBACK_ENV = "FLICKRAVEN_SITE_FEEDBACK"


def site_feedback_ratings(processed: Path) -> pd.DataFrame | None:
    """Ratings made on the live site (pipeline/export_site_feedback.py), in the MovieLens layout, or None.

    Used only when the environment variable FLICKRAVEN_SITE_FEEDBACK=1 is set, so a normal build is unchanged.
    Site users have ids from 100,000,000 up, so they never collide with MovieLens users. They are added to the
    TRAINING ratings only; the held-out ratings that every metric is measured on stay MovieLens-only, so a build
    with and without site feedback can be compared on exactly the same test.
    """
    path = processed / "site_feedback" / "ratings.parquet"
    if os.environ.get(SITE_FEEDBACK_ENV) != "1" or not path.exists():
        return None
    df = pd.read_parquet(path)[["user_id", "ml_movie_id", "rating"]]
    return df if len(df) else None


def load_split(processed: Path, split: str = "val", train_parts: tuple[str, ...] = ("train",),
               include_holdout_items: bool = False) -> SplitData:
    """Train on the concatenation of `train_parts`, evaluate on `<split>.parquet`.

    Universe = part A, minus the new-movie holdout films unless `include_holdout_items` (the
    new-movie experiment needs them as candidates; nobody has rated them in training).
    """
    splits = processed / "splits"
    catalog = pd.read_csv(processed / "catalog_ids.csv")
    holdout = set(pd.read_parquet(splits / "holdout_films.parquet")["ml_movie_id"])
    items = catalog[catalog["catalog_part"] == "A"]
    if not include_holdout_items:
        items = items[~items["ml_movie_id"].isin(holdout)]
    items = items[["ml_movie_id", "tmdb_id"]].astype({"ml_movie_id": "int64"})
    train = pd.concat([pd.read_parquet(splits / f"{p}.parquet") for p in train_parts], ignore_index=True)
    site = site_feedback_ratings(processed)
    if site is not None:
        train = pd.concat([train, site.astype({c: train[c].dtype for c in site.columns if c in train.columns})], ignore_index=True)
    held = pd.read_parquet(splits / f"{split}.parquet")
    return build_split(train, held, items, split)