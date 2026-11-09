"""Series and anime: kept out of the movie rails, ranked for a user by content similarity plus popularity."""
from types import SimpleNamespace

import numpy as np
import scipy.sparse as sp

from cinematch_engine.online import Catalog, OnlineEngine, UserState


def cat(kinds, popularity, kind=True):
    n = len(kinds)
    return Catalog(
        movie_ids=np.arange(100, 100 + n), titles=[f"t{i}" for i in range(n)], genres=[["Drama"]] * n,
        keywords=[[]] * n, language=["en"] * n, runtime=np.full(n, 100.0), year=np.full(n, 2000.0),
        part=np.array(["D"] * n), popularity=np.array(popularity, dtype=float), votes=np.arange(n, dtype=float),
        has_award=np.zeros(n, dtype=bool), content=sp.identity(n, format="csr", dtype=np.float32),
        universe_rows=np.array([0]), recent=np.zeros(n, dtype=bool), kind=np.array(kinds, dtype=object) if kind else None)


def engine(c, content_scores=None):
    e = SimpleNamespace(cat=c)
    e.scores = lambda st: {"content": np.array(content_scores if content_scores is not None else [-np.inf] * c.n, dtype=np.float32)}
    e.excluded = lambda st: OnlineEngine.excluded(e, st)
    e.learned_series = lambda st, rows: OnlineEngine.learned_series(e, st, rows)
    return e


KINDS = ["movie", "series", "series", "anime", "series"]
POP = [9.0, 5.0, 8.0, 7.0, 6.0]


def test_movie_rails_never_pick_series_or_anime():
    c = cat(KINDS, POP)
    assert c.non_movie_rows.tolist() == [1, 2, 3, 4]
    assert OnlineEngine.excluded(engine(c), UserState()).tolist() == [1, 2, 3, 4]


def test_no_kind_given_means_all_movies():
    c = cat(KINDS, POP, kind=False)
    assert c.non_movie_rows.size == 0 and set(c.kind) == {"movie"}


def test_without_taste_signal_series_are_ranked_by_popularity():
    rows, scores = OnlineEngine.kind_rank(engine(cat(KINDS, POP)), UserState(), "series")
    assert rows.tolist() == [2, 4, 1] and scores[0] > scores[-1]


def test_taste_signal_moves_similar_series_up_and_hides_seen_ones():
    c = cat(KINDS, [9.0, 6.0, 6.5, 7.0, 5.5])
    e = engine(c, content_scores=[0.0, 0.9, 0.0, 0.0, 0.0])         # series row 1 is closest to what the user likes
    rows, _ = OnlineEngine.kind_rank(e, UserState(), "series")
    assert rows.tolist()[0] == 1
    seen, _ = OnlineEngine.kind_rank(e, UserState(watched={1}), "series")
    assert 1 not in seen.tolist()
    assert OnlineEngine.kind_rank(e, UserState(), "anime")[0].tolist() == [3]


def test_learned_series_similarity_lifts_covered_series_for_a_user_who_liked_a_neighbour():
    c = cat(["movie", "series", "series", "series", "series"], [9.0, 5.0, 8.0, 6.0, 7.0])
    sim = sp.lil_matrix((5, 5), dtype=np.float32)
    sim[1, 3] = sim[3, 1] = 0.9                                   # real viewers who liked 1 also liked 3
    c.series_sim = sim.tocsr()
    e = engine(c, content_scores=[0.0, 0.5, 0.3, 0.5, 0.2])
    rows, _ = OnlineEngine.kind_rank(e, UserState(likes={1}), "series")
    assert rows.tolist()[0] == 3                                   # the covered neighbour beats the more popular ones
    # a user with nothing the model knows about is ranked as before
    base, _ = OnlineEngine.kind_rank(engine(cat(["movie", "series", "series", "series", "series"], [9.0, 5.0, 8.0, 6.0, 7.0]),
                                            content_scores=[0.0, 0.5, 0.3, 0.5, 0.2]), UserState(likes={2}), "series")
    other, _ = OnlineEngine.kind_rank(e, UserState(likes={2}), "series")
    assert other.tolist() == base.tolist()
