"""IMDb ratings are matched by imdb_id only; films IMDb does not list get nothing."""
import pandas as pd

from pipeline.imdb_ratings import match


def test_match_keeps_only_catalog_films():
    ratings = pd.DataFrame({"tconst": ["tt0468569", "tt9999999", "tt0111161"],
                            "averageRating": [9.0, 5.0, 9.3], "numVotes": [3000000, 12, 3100000]})
    got = match(ratings, pd.Series(["tt0468569", "tt0111161", None, "tt0000001"]))
    assert got.set_index("imdb_id").to_dict("index") == {
        "tt0468569": {"imdb_rating": 9.0, "imdb_votes": 3000000},
        "tt0111161": {"imdb_rating": 9.3, "imdb_votes": 3100000}}
