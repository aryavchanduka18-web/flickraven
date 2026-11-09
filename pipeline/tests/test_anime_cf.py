"""Anime lists are read into the same format as the drama lists, and anime are matched to TMDB by title."""
import pandas as pd

from pipeline.anime_cf import as_pairs, match_anime
from pipeline.drama_cf import weights


def test_rating_file_becomes_scored_and_unscored_completed_entries():
    p = as_pairs(pd.DataFrame({"user_id": [1, 1, 1, 1], "anime_id": [10, 11, 12, 13], "rating": [9, -1, 5, 7]}))
    assert p["score"].tolist() == [9.0, 0.0, 5.0, 7.0] and p["completed"].tolist() == [False, True, False, False]
    assert weights(p).round(2).tolist() == [0.87, 0.5, 0.0, 0.6]          # 9 liked, unrated watched 0.5, 5 ignored, 7 liked


def test_match_by_english_original_or_alternative_title_and_tv_only():
    anime = pd.DataFrame({"anime_id": [1, 2, 3], "name": ["Shingeki no Kyojin", "Death Note", "Death Note"],
                          "type": ["TV", "TV", "Movie"], "members": [900, 800, 5000]})
    catalog = pd.DataFrame({"tmdb_id": [10, 11, 12], "title": ["Attack on Titan", "Death Note", "Unknown"],
                            "original_title": ["進撃の巨人", "DEATH NOTE", "x"], "title_type": ["anime"] * 3})
    got = match_anime(anime, catalog, {10: ["Shingeki no Kyojin"]})
    assert got.to_dict("records") == [{"tmdb_id": 10, "sid": 1}, {"tmdb_id": 11, "sid": 2}]   # the Movie entry is ignored
