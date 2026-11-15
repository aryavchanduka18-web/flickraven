"""Regression tests for the 2026-11-15 black-box fix brief (issues 1 to 4). Synthetic catalogues: no real titles."""
from types import SimpleNamespace

import numpy as np
import scipy.sparse as sp

from cinematch_engine.online import Catalog, OnlineEngine, UserState, language_floor_order


def catalog(content, genres=None, language=None, popularity=None):
    content = sp.csr_matrix(content, dtype=np.float32)
    n = content.shape[0]
    return Catalog(
        movie_ids=np.arange(100, 100 + n), titles=[f"t{i}" for i in range(n)], genres=genres or [["Drama"]] * n,
        keywords=[[]] * n, language=language or ["en"] * n, runtime=np.full(n, 100.0), year=np.full(n, 2000.0),
        part=np.array(["D"] * n), popularity=np.array(popularity or [7.5] * n, dtype=float), votes=np.arange(n, dtype=float),
        has_award=np.zeros(n, dtype=bool), content=content, universe_rows=np.array([], dtype=np.int64),
        recent=np.zeros(n, dtype=bool), kind=np.array(["movie"] * n, dtype=object))


def engine(cat):
    e = OnlineEngine.__new__(OnlineEngine)
    e.src = SimpleNamespace(item_cf=None, user_cf_scores=None, svd_scores=None, als_scores=None)
    e.cat, e.event_weights = cat, {"list_add": 3, "list_remove": -2, "watched": 2, "like": 4, "dislike": -5, "rate": 1}
    return e


# ---------------------------------------------------------------- issue 3: two low ratings must not flip the taste
# Columns: 0 Japanese animation, 1-5 what is specific to each liked film, 6 franchise of disliked film A,
# 7 what is specific to disliked film B, 8 English live action, 9 something else.
def _taste_catalogue():
    rows = []
    for i in range(5):                                   # 0-4: five liked films, Japanese animation plus their own traits
        v = np.zeros(10); v[0], v[1 + i] = 0.6, 0.8; rows.append(v)
    for j, col in ((5, 6), (6, 7)):                      # 5, 6: two disliked films, also Japanese animation
        v = np.zeros(10); v[0], v[col] = 0.8, 0.6; rows.append(v)
    cands = {"anime": (1.0, 0), "franchise": (0.8, 6), "english": (0, 8), "mild": (0.5, 9)}
    for _, (a, col) in cands.items():                    # 7-10: candidates
        v = np.zeros(10); v[0] = a
        if col:
            v[col] = np.sqrt(1 - a * a)
        rows.append(v)
    return catalog(np.array(rows)), {name: 7 + i for i, name in enumerate(cands)}


def _content(e, ratings):
    return e.scores(UserState(ratings=ratings))["content"]


def test_two_low_ratings_demote_close_titles_but_keep_the_shared_taste():
    cat, c = _taste_catalogue()
    e = engine(cat)
    pos = {0: 10.0, 1: 10.0, 2: 10.0, 3: 9.0, 4: 9.0}
    b = _content(e, pos)
    after = _content(e, {**pos, 5: 1.0, 6: 1.0})
    # The language/genre the person rated highly five times still scores above an unrelated English film.
    assert after[c["anime"]] > after[c["english"]]
    assert after[c["anime"]] > 0
    # The title close to a disliked one (same franchise) drops relative to a plain title of the liked kind.
    assert after[c["franchise"]] / after[c["anime"]] < b[c["franchise"]] / b[c["anime"]]


def test_many_dislikes_keep_the_old_full_strength_profile():
    """The damping is only for a few dislikes among many likes; 4 or more dislikes (or none) change nothing."""
    cat, c = _taste_catalogue()
    e = engine(cat)
    liked, disliked = [(0, 4.0), (1, 4.0), (2, 3.0)], [(5, 5.0), (6, 5.0), (5, 4.0), (6, 4.0)]
    full = e._content_scores(liked, disliked)
    L = np.asarray((sp.csr_matrix(np.array([[4, 4, 3]]) / 11.0) @ cat.content[[0, 1, 2]]).todense()).ravel()
    D = np.asarray((sp.csr_matrix(np.array([[5, 5, 4, 4]]) / 18.0) @ cat.content[[5, 6, 5, 6]]).todense()).ravel()
    assert np.allclose(full, np.asarray(cat.content @ (L - D)).ravel(), atol=1e-5)
    assert np.array_equal(e._content_scores(liked, []), np.asarray(cat.content @ L).ravel().astype(np.float32))


def test_profile_without_dislikes_is_unchanged_in_order():
    cat, c = _taste_catalogue()
    e = engine(cat)
    s = _content(e, {0: 10.0, 1: 8.0})
    liked = np.asarray(cat.content[[0, 1]].T @ np.array([4.0, 2.0])).ravel()
    expect = np.asarray(cat.content @ liked).ravel()
    assert np.array_equal(np.argsort(-s, kind="stable"), np.argsort(-expect, kind="stable"))


def test_language_floor_keeps_every_chosen_language_in_the_row():
    language = ["en"] * 30 + ["ja"] * 10                   # English films all score higher
    rows = list(range(40))
    out = language_floor_order(rows, language, ["ja", "en"])[:20]
    assert sum(language[r] == "ja" for r in out) >= 5     # a quarter of the row at least (2 languages)
    assert sorted(out[:3]) == out[:3]                     # otherwise best-first
    assert language_floor_order(rows, language, ["en"]) == rows    # one language: unchanged


# ---------------------------------------------------------------- issue 4: high ratings overrule an old genre dislike
def _genre_catalogue():
    genres = [["Horror"]] * 8 + [["Animation"]] * 4
    return catalog(np.eye(12), genres=genres)


def test_three_high_ratings_lift_a_disliked_genre_and_deleting_them_restores_it():
    e = engine(_genre_catalogue())
    st = e.lift_disliked_genres(UserState(ratings={0: 10, 1: 10, 2: 9}, disliked_genres=["Horror", "War"]))
    assert st.disliked_genres == ["War"] and st.lifted_genres == ["Horror"]
    assert set(e.excluded(st).tolist()) == {0, 1, 2}        # only the rated titles: horror is no longer filtered
    two = e.lift_disliked_genres(UserState(ratings={0: 10, 1: 10}, disliked_genres=["Horror"]))
    assert two.disliked_genres == ["Horror"]               # two is not enough
    mixed = e.lift_disliked_genres(UserState(ratings={0: 10, 1: 10, 2: 9, 3: 2, 4: 3, 5: 1}, disliked_genres=["Horror"]))
    assert mixed.disliked_genres == ["Horror"]             # as many low as high: the dislike stands
    gone = e.lift_disliked_genres(UserState(ratings={}, disliked_genres=["Horror"]))
    assert gone.disliked_genres == ["Horror"]              # ratings deleted: the filter is back


def _home_engine(genres, nb, n=60):
    """A tiny engine for home(): every title scores, anchors have item-CF neighbours `nb` (list per universe row)."""
    rng = np.random.default_rng(0)
    cat = catalog(sp.identity(n, format="csr"), genres=genres, language=["en"] * n)
    cat.universe_rows = np.arange(n)
    cat.universe_of_row = np.arange(n)
    score = rng.random(n).astype(np.float32)
    e = engine(cat)
    e.nb_idx = np.array([row + [0] * (30 - len(row)) for row in nb])
    e.nb_vals = np.array([[1.0] * len(row) + [0.0] * (30 - len(row)) for row in nb])
    e.scores = lambda st: {"content": score, "svd": score, "user_cf": score}
    e.rail_scores = lambda st, scores=None: np.where(np.isin(np.arange(n), OnlineEngine.excluded(e, st)), -np.inf, score)
    e.phase = lambda *a, **k: None
    e._new_notable = lambda st, scores: []
    e.top_picks = lambda st, mode, k=25, scores=None, extra_exclude=None, tuning=None: []
    return e


def test_because_you_liked_skips_anchors_in_a_still_disliked_genre_and_thin_rows():
    n = 60
    genres = [["Horror"]] * 20 + [["Drama"]] * 40
    nb = [[] for _ in range(n)]
    nb[0] = list(range(1, 21))            # horror anchor: horror neighbours
    nb[20] = list(range(1, 15)) + list(range(21, 27))   # drama anchor: 14 horror + 6 drama neighbours: thin after the filter
    nb[30] = list(range(31, 55))          # drama anchor with plenty of drama neighbours
    e = _home_engine(genres, nb)
    st = UserState(ratings={0: 10, 20: 10, 30: 10}, disliked_genres=["Horror"])
    st.events = [("rate", 30), ("rate", 20), ("rate", 0)]
    keys = [r["key"] for r in OnlineEngine.home(e, st)["rails"]]
    assert "because_you_liked:100" not in keys        # anchor in a disliked genre
    assert "because_you_liked:120" not in keys        # only 6 of its 20 neighbours survive the filter
    assert "because_you_liked:130" in keys


# ---------------------------------------------------------------- issue 1: what was undone no longer counts
def test_cleared_like_removed_save_and_unwatched_do_not_count():
    e = engine(_genre_catalogue())
    st = UserState()
    st.events = [("like", 1), ("list_add", 2), ("watched", 3), ("list_add", 4)]
    st.in_list = {4}                                    # 1 un-liked, 2 removed from the list, 3 unwatched
    assert e.implicit_strength(st) == {4: 3.0}


# ---------------------------------------------------------------- issue 2: Discover Something Different is different
def test_different_row_caps_top_language_and_top_genres():
    n = 200
    language = ["ja" if i < 120 else ("fr" if i % 2 else "ko") for i in range(n)]
    genres = [["Animation", "Fantasy"] if i < 120 else (["Drama"] if i % 3 else ["Comedy"]) for i in range(n)]
    cat = catalog(sp.identity(n, format="csr"), genres=genres, language=language)
    e = engine(cat)
    rail = np.linspace(1, 0, n).astype(np.float32)        # the person's own taste ranks the anime first
    st = UserState(ratings={0: 10, 1: 10, 2: 9}, languages=["ja", "en"])
    rail[[0, 1, 2]] = -np.inf
    for rng in (None, np.random.default_rng(3)):
        out = OnlineEngine.different_rows(e, st, list(range(3, 40)), set(range(3, 10)), rail, 20, rng)
        assert len(out) == 20
        assert sum(language[r] == "ja" for r in out) <= 6
        assert sum(bool({"Animation", "Fantasy"} & set(genres[r])) for r in out) <= 6
        assert not set(out) & set(range(10))               # nothing already on the page or rated
