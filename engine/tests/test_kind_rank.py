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
    e.learned_series = lambda st, rows, sim="learned": OnlineEngine.learned_series(e, st, rows, sim)
    e.engaged_rows = lambda st: OnlineEngine.engaged_rows(e, st)
    e.language_floor = lambda st, rows, base: OnlineEngine.language_floor(e, st, rows, base)
    e.anime_interest = lambda st: OnlineEngine.anime_interest(e, st)
    e.anime_scores = lambda st: OnlineEngine.anime_scores(e, st)
    e.anime_liked = lambda st: OnlineEngine.anime_liked(e, st)
    e.anime_known = lambda: OnlineEngine.anime_known(e)
    e.anime_order = lambda st, rows: OnlineEngine.anime_order(e, st, rows)
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


def test_gemini_neighbours_lift_series_for_a_user_who_liked_the_seed_and_filters_still_win():
    c = cat(["movie", "series", "series", "series", "series"], [9.0, 5.0, 8.0, 6.0, 7.0])
    g = sp.lil_matrix((5, 5), dtype=np.float32)
    g[1, 3] = g[3, 1] = 1.0                                       # Gemini named 3 as similar to 1
    c.gemini_sim = g.tocsr()
    e = engine(c, content_scores=[0.0, 0.5, 0.3, 0.5, 0.2])
    assert OnlineEngine.kind_rank(e, UserState(likes={1}), "series")[0].tolist()[0] == 3
    assert 3 not in OnlineEngine.kind_rank(e, UserState(likes={1}, dislikes={3}), "series")[0].tolist()
    assert 3 not in OnlineEngine.kind_rank(e, UserState(likes={1}, watched={3}), "series")[0].tolist()
    # a user who liked something Gemini has no list for is ranked as without the graph
    c0 = cat(["movie", "series", "series", "series", "series"], [9.0, 5.0, 8.0, 6.0, 7.0])
    base = OnlineEngine.kind_rank(engine(c0, content_scores=[0.0, 0.5, 0.3, 0.5, 0.2]), UserState(likes={2}), "series")[0].tolist()
    assert OnlineEngine.kind_rank(e, UserState(likes={2}), "series")[0].tolist() == base


def test_gemini_and_learned_lists_together():
    c = cat(["movie", "series", "series", "series", "series"], [9.0, 5.0, 5.5, 6.0, 7.0])
    s = sp.lil_matrix((5, 5), dtype=np.float32); s[1, 3] = s[3, 1] = 0.9
    g = sp.lil_matrix((5, 5), dtype=np.float32); g[1, 4] = g[4, 1] = 1.0; g[1, 3] = g[3, 1] = 0.5
    c.series_sim, c.gemini_sim = s.tocsr(), g.tocsr()
    rows, sc = OnlineEngine.kind_rank(engine(c, content_scores=[0.0, 0.5, 0.3, 0.5, 0.2]), UserState(likes={1}), "series")
    assert set(rows.tolist()) == {2, 3, 4} and rows.tolist()[0] == 3 and np.all(np.diff(sc) <= 0)


def test_without_a_gemini_graph_the_learned_ranking_is_unchanged():
    c = cat(["movie", "series", "series", "series", "series"], [9.0, 5.0, 8.0, 6.0, 7.0])
    s = sp.lil_matrix((5, 5), dtype=np.float32); s[1, 3] = s[3, 1] = 0.9
    c.series_sim = s.tocsr()
    e = engine(c, content_scores=[0.0, 0.5, 0.3, 0.5, 0.2])
    none = OnlineEngine.kind_rank(e, UserState(likes={1}), "series")
    c.gemini_sim = sp.csr_matrix((5, 5), dtype=np.float32)
    empty = OnlineEngine.kind_rank(e, UserState(likes={1}), "series")
    assert none[0].tolist() == empty[0].tolist() and np.allclose(none[1], empty[1])
    # and the learned part is not counted twice when only the learned lists exist
    assert none[0].tolist()[0] == 3 and none[1][0] <= 1.0


def test_chosen_language_ranks_its_best_titles_alongside_the_top_without_removing_others():
    n = 12
    kinds = ["movie"] + ["series"] * (n - 1)
    c = cat(kinds, [9.0] + [float(i) for i in range(1, n)])        # series rows 1..11, popularity 1..11
    c.language = ["en"] * n
    for r in (1, 2, 3):                                             # three weak Hindi series, the best is row 3
        c.language[r] = "hi"
    e = engine(c)
    plain, ps = OnlineEngine.kind_rank(e, UserState(), "series")
    assert plain.tolist() == list(range(11, 0, -1))
    hindi, hs = OnlineEngine.kind_rank(e, UserState(languages=["hi"]), "series")
    assert set(hindi.tolist()) == set(plain.tolist())              # nothing removed
    assert hindi.tolist().index(3) < plain.tolist().index(3)       # the best Hindi series moves up
    assert hindi.tolist()[:3] == [11, 10, 3] or hindi.tolist().index(3) <= 3
    rest = [r for r in plain.tolist() if r not in (1, 2, 3)]
    assert [r for r in hindi.tolist() if r not in (1, 2, 3)] == rest         # other languages keep their order
    assert np.all(np.diff(hs) <= 0)
    assert OnlineEngine.kind_rank(e, UserState(languages=["fr"]), "series")[0].tolist() == plain.tolist()   # no title in it: no change


def test_language_in_the_persons_history_counts_in_proportion():
    n = 12
    c = cat(["movie"] * 4 + ["series"] * (n - 4), [9.0] * 4 + [float(i) for i in range(1, n - 3)])
    c.language = ["hi", "hi", "hi", "en"] + ["hi"] * 4 + ["en"] * 4      # the Hindi series are the least popular
    e = engine(c)
    plain, _ = OnlineEngine.kind_rank(e, UserState(), "series")
    hist, _ = OnlineEngine.kind_rank(e, UserState(likes={0, 1, 2}), "series")     # three liked Hindi films
    top_hi = lambda rows: next(i for i, r in enumerate(rows.tolist()) if c.language[r] == "hi")
    assert top_hi(hist) < top_hi(plain)
    one, _ = OnlineEngine.kind_rank(e, UserState(likes={0, 1}), "series")          # fewer than 3: no inference
    assert one.tolist() == plain.tolist()


def test_anime_interest_counts_only_engaged_anime():
    c = cat(["movie", "anime", "anime", "series", "anime"], [9.0, 5.0, 8.0, 6.0, 7.0])
    e = engine(c)
    e.engaged_rows = lambda st: OnlineEngine.engaged_rows(e, st)
    assert OnlineEngine.anime_interest(e, UserState(likes={1, 3}, ratings={2: 9.0, 4: 3.0})) == 2


def test_japanese_language_choice_is_not_anime_interest_and_does_not_reorder_anime():
    c = cat(["movie", "anime", "anime", "series", "series"], [9.0, 5.0, 8.0, 6.0, 7.0])
    c.language = ["en", "ja", "ja", "ja", "en"]
    e = engine(c)
    st = UserState(languages=["ja"])
    assert OnlineEngine.anime_interest(e, st) == 0
    assert OnlineEngine.kind_rank(e, st, "anime")[0].tolist() == OnlineEngine.kind_rank(e, UserState(), "anime")[0].tolist()
    assert OnlineEngine.anime_interest(e, UserState(likes={3})) == 0       # a liked Japanese live-action series
    assert OnlineEngine.anime_interest(e, UserState(likes={1})) == 1


# ------------------------------------------------------------------ the anime model (series and films, learned from real lists)
def anime_cat():
    #          0        1        2        3        4        5 (new anime, unknown to the model)   6 anime film
    c = cat(["movie", "anime", "anime", "anime", "anime", "anime", "movie"], [9.0, 5.0, 8.0, 7.0, 6.0, 9.5, 6.0])
    sim = sp.lil_matrix((7, 7), dtype=np.float32)
    sim[1, 4], sim[1, 3], sim[1, 6] = 0.9, 0.2, 0.5            # people who liked anime 1 liked 4 most, then film 6, then 3
    sim[2, 3] = 0.1
    c.anime_sim = {"long": sim.tocsr(), "mid": sim.tocsr(), "short": sim.tocsr()}
    return c


def test_anime_model_reorders_known_anime_inside_their_places_and_leaves_unknown_ones():
    e = engine(anime_cat())
    before, s0 = OnlineEngine.kind_rank(e, UserState(), "anime")              # nothing liked: the earlier order
    assert before.tolist() == [5, 2, 4, 3, 1]
    rows, s1 = OnlineEngine.kind_rank(e, UserState(likes={1}), "anime")
    assert rows.tolist() == [5, 4, 3, 2]            # 5 (unknown to the model) keeps first place; 4 > 3 > 2 by the model
    assert list(s1) == sorted(s1, reverse=True)     # scores stay with the places


def test_anime_model_is_ignored_without_a_file_or_without_a_liked_anime_it_knows():
    c = anime_cat()
    e = engine(c)
    assert OnlineEngine.anime_order(e, UserState(likes={5}), [2, 3, 4]) == [2, 3, 4]      # liked anime unknown to the model
    assert OnlineEngine.anime_order(e, UserState(ratings={1: 6.0}), [2, 3, 4]) == [2, 3, 4]   # rated under 7: not a like
    assert OnlineEngine.anime_order(e, UserState(watched={1}, in_list={1}), [2, 3, 4]) == [2, 3, 4]   # watched / saved: not taste
    c.anime_sim = None
    assert OnlineEngine.anime_order(e, UserState(likes={1}), [2, 3, 4]) == [2, 3, 4]


def test_anime_model_orders_anime_films_too_and_ties_keep_their_order():
    e = engine(anime_cat())
    assert OnlineEngine.anime_order(e, UserState(ratings={1: 9.0}), [0, 3, 6, 2]) == [0, 6, 3, 2]   # row 0 unknown: stays; 6 > 3 > 2
    assert OnlineEngine.anime_order(e, UserState(likes={2}), [4, 6, 3]) == [3, 4, 6]               # 4 and 6 tie at zero: order kept


def test_anime_model_tier_follows_the_number_of_liked_anime_it_knows():
    from cinematch_engine import online
    c = anime_cat()
    n = 7
    big = sp.lil_matrix((n, n), dtype=np.float32)
    big[1, 3] = 1.0                               # "long" prefers 3 over 4
    big[1, 4] = 0.5
    mid = sp.lil_matrix((n, n), dtype=np.float32)
    mid[1, 4] = 1.0                               # "mid" prefers 4 over 3
    mid[1, 3] = 0.5
    short = sp.lil_matrix((n, n), dtype=np.float32)
    short[1, 4] = 1.0                             # "short" prefers 4 over 3 as well
    short[1, 3] = 0.2
    c.anime_sim = {"long": big.tocsr(), "mid": mid.tocsr(), "short": short.tocsr()}
    e = engine(c)
    st = UserState(likes={1})
    assert OnlineEngine.anime_scores(e, st)[0] == "short"
    assert OnlineEngine.anime_order(e, st, [3, 4]) == [4, 3]
    old = online.ANIME_SHORT_MAX, online.ANIME_MID_MAX
    try:
        online.ANIME_SHORT_MAX, online.ANIME_MID_MAX = 0, 0       # one liked anime now counts as a long list
        assert OnlineEngine.anime_scores(e, st)[0] == "long"
        assert OnlineEngine.anime_order(e, st, [4, 3]) == [3, 4]
    finally:
        online.ANIME_SHORT_MAX, online.ANIME_MID_MAX = old


def test_anime_model_tier_is_deterministic_and_follows_the_current_ratings():
    from cinematch_engine import online
    c = anime_cat()
    e = engine(c)
    st = UserState(ratings={1: 9.0, 2: 8.0})
    first = OnlineEngine.anime_order(e, st, [3, 4, 6])
    assert all(OnlineEngine.anime_order(e, st, [3, 4, 6]) == first for _ in range(5))       # same state, same order
    old = online.ANIME_SHORT_MAX
    try:
        online.ANIME_SHORT_MAX = 1                                  # 2 liked anime -> "mid"; delete one rating -> "short"
        assert OnlineEngine.anime_scores(e, st)[0] == "mid"
        del st.ratings[2]
        assert OnlineEngine.anime_scores(e, st)[0] == "short"
        st.likes.add(1)                                             # liking the same title again counts it once
        assert OnlineEngine.anime_scores(e, st)[0] == "short"
    finally:
        online.ANIME_SHORT_MAX = old


def test_the_real_user_tier_count_uses_the_engines_own_tier():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pipeline.anime_tier_counts import tier_of
    from cinematch_engine import anime_model_file
    n = 40
    sim = sp.lil_matrix((n, n), dtype=np.float32)
    for i in range(30):
        sim[i, i + 1] = 0.5                                      # rows 0..29 vote; 30..39 only get votes or nothing
    c = cat(["anime"] * n, [5.0] * n)
    c.anime_sim = {"long": sim.tocsr(), "mid": sim.tocsr(), "short": sim.tocsr()}
    e = engine(c)
    for st in (UserState(), UserState(likes={35}), UserState(ratings={0: 9.0, 1: 6.0}, likes={0}),
               UserState(likes=set(range(0, 8)), watched={9}), UserState(likes=set(range(0, 9))),
               UserState(ratings={r: 8.0 for r in range(25)}, picks={39}), UserState(ratings={r: 8.0 for r in range(30)})):
        got = OnlineEngine.anime_scores(e, st)
        n_known = len(anime_model_file.known_inputs(c.anime_sim, OnlineEngine.anime_liked(None, st)))
        want = "none 0" if got is None else {"short": "short 1-7", "mid": "mid 8-24", "long": "long 25+"}[got[0]]
        assert tier_of(n_known) == want
