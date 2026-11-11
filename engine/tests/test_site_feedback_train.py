"""Site ratings join the training ratings only when asked to, and never the held-out ratings."""
import pandas as pd

from cinematch_engine.data import splits
from cinematch_engine.data.splits import SITE_FEEDBACK_ENV, load_split


def _write(processed, with_site=True):
    out = processed / "splits"
    out.mkdir(parents=True)
    pd.DataFrame({"ml_movie_id": [99]}).to_parquet(out / "holdout_films.parquet")
    pd.DataFrame({"ml_movie_id": [1, 2, 3], "tmdb_id": [11, 22, 33], "catalog_part": ["A"] * 3}).to_csv(processed / "catalog_ids.csv", index=False)
    pd.DataFrame({"user_id": [1, 1, 2], "ml_movie_id": [1, 2, 3], "rating": [8, 6, 10], "timestamp": [1, 2, 3]}).to_parquet(out / "train.parquet")
    pd.DataFrame({"user_id": [1], "ml_movie_id": [3], "rating": [8], "timestamp": [4]}).to_parquet(out / "val.parquet")
    if with_site:
        site = processed / "site_feedback"
        site.mkdir()
        pd.DataFrame({"user_id": [100_000_001], "ml_movie_id": [2], "rating": [9], "timestamp": [5]}).to_parquet(site / "ratings.parquet")


def test_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(SITE_FEEDBACK_ENV, raising=False)
    _write(tmp_path)
    assert load_split(tmp_path, "val").n_users == 2


def test_on_adds_site_users_to_training_only(tmp_path, monkeypatch):
    monkeypatch.setenv(SITE_FEEDBACK_ENV, "1")
    _write(tmp_path)
    d = load_split(tmp_path, "val")
    assert d.n_users == 3 and 100_000_001 in d.user_ids
    assert len(d.eval_df) == 1                       # held-out ratings are the same MovieLens ones


def test_on_without_a_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(SITE_FEEDBACK_ENV, "1")
    _write(tmp_path, with_site=False)
    assert load_split(tmp_path, "val").n_users == 2
