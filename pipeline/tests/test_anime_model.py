"""The anime model: seasons of one series count once, EASE and the vote cut behave, the id map links ids not titles."""
import numpy as np
import pandas as pd

from pipeline import anime_model as am


def test_several_seasons_of_one_series_are_one_title_with_the_best_weight():
    pairs = am.as_pairs(pd.DataFrame({"user_id": [1, 1, 1, 1], "anime_id": [101, 102, 200, 300], "rating": [7, 10, 8, -1]}))
    x = am.matrix(pairs, {101: 0, 102: 0, 200: 1, 300: 2}, 3)          # 101 and 102 are two seasons of title 0
    assert x.shape == (1, 3) and x.nnz == 3
    assert round(float(x[0, 0]), 2) == 1.0                              # the 10, not 7 + 10
    assert round(float(x[0, 2]), 2) == 0.5                              # watched without a score


def test_ease_has_no_self_vote_and_sparsify_keeps_the_strongest_positive_votes():
    rng = np.random.default_rng(0)
    x = (rng.random((300, 12)) < 0.3).astype(float)
    import scipy.sparse as sp
    b = am.ease(sp.csr_matrix(x), 10.0)
    assert np.allclose(np.diag(b), 0)
    s = am.sparsify(b, 3)
    assert all(s[i].nnz <= 3 for i in range(12)) and (s.data > 0).all()
    i = 0
    assert set(s[i].indices) == set(np.argsort(-b[i])[:3][b[i, np.argsort(-b[i])[:3]] > 0])


def test_the_id_map_links_tv_and_movie_ids_and_ignores_ambiguous_films():
    entries = [{"type": "TV", "mal_id": 5114, "themoviedb_id": {"tv": 31911}},
               {"type": "TV", "mal_id": 5115, "themoviedb_id": {"tv": 31911}},            # a second season, same show
               {"type": "MOVIE", "mal_id": 32281, "themoviedb_id": {"movie": [372058]}},
               {"type": "MOVIE", "mal_id": 9, "themoviedb_id": {"movie": [1, 2]}},       # two catalog films: skipped
               {"type": "OVA", "mal_id": 7, "themoviedb_id": {"tv": 31911}}]             # not a series type
    got = am.id_matches(entries, {am.TV_OFFSET + 31911}, {372058, 1, 2})
    assert got == [{"tmdb_id": am.TV_OFFSET + 31911, "sid": 5114, "format": "series"},
                   {"tmdb_id": am.TV_OFFSET + 31911, "sid": 5115, "format": "series"},
                   {"tmdb_id": 372058, "sid": 32281, "format": "film"}]
