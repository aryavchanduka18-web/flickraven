"""Candidates from outside the recommender (Gemini's similar series) are filtered and ordered by the user's taste."""
from types import SimpleNamespace

import numpy as np
import scipy.sparse as sp

from cinematch_engine.online import OnlineEngine, UserState


def engine(content, genres=None):
    n = len(content)
    cat = SimpleNamespace(n=n, genres=genres or [["Drama"]] * n)
    e = SimpleNamespace(cat=cat)
    e.scores = lambda st: {"content": np.array(content, dtype=np.float32)}
    return e


def fit(e, st, rows):
    return OnlineEngine.personal_fit(e, st, rows)


def test_disliked_low_rated_and_disliked_genre_titles_are_dropped():
    e = engine([0.5, 0.4, 0.3, 0.2], genres=[["Drama"], ["Drama"], ["Drama"], ["Crime"]])
    st = UserState(dislikes={0}, ratings={1: 3.0}, disliked_genres=["Crime"])
    keep, _, has = fit(e, st, [0, 1, 2, 3])
    assert keep.tolist() == [False, False, True, False] and has       # the Peaky Blinders case: disliked means never shown


def test_titles_closer_to_what_was_disliked_than_liked_are_dropped_and_others_ranked_by_taste():
    e = engine([-0.4, -0.3, 0.1, 0.5, 0.2, 0.3])
    keep, f, _ = fit(e, UserState(likes={5}), [0, 1, 2, 3, 4, 5])
    assert keep.tolist() == [False, False, True, True, True, True]   # the negative, weakest-third ones go
    assert f[3] > f[5] > f[4] > f[2]


def test_no_taste_signal_means_neutral_fit_and_nothing_dropped():
    e = engine([-np.inf, -np.inf, -np.inf])
    keep, f, has = fit(e, UserState(), [0, 1, 2])
    assert keep.all() and f.tolist() == [0.5, 0.5, 0.5] and not has


def test_a_disliked_genre_that_would_empty_the_list_is_ignored_but_real_dislikes_still_apply():
    # Anime pages: every neighbour is "Animation". Disliking that genre must not hide the whole More Like This list.
    e = engine([0.5, 0.4, 0.3, 0.2, 0.1], genres=[["Animation"]] * 5)
    st = UserState(dislikes={0}, ratings={1: 3.0}, disliked_genres=["Animation"])
    keep, _, _ = fit(e, st, [0, 1, 2, 3, 4])
    assert keep.tolist() == [False, False, True, True, True]
