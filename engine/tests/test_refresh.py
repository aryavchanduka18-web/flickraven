"""Daily refresh and language spreading: pure list helpers."""
import numpy as np

from cinematch_engine.rerank import MODES, refresh, spread_languages


def test_refresh_keeps_the_best_and_is_repeatable_for_a_seed():
    items = list(range(100))
    a = refresh(items, 20, np.random.default_rng(1))
    b = refresh(items, 20, np.random.default_rng(1))
    c = refresh(items, 20, np.random.default_rng(2))
    assert a == b and a != c                      # same seed, same day; another seed, another list
    assert a[:3] == [0, 1, 2]                     # the very best always stay
    assert len(a) == 20 and a == sorted(a) and len(set(a)) == 20     # best-first order kept, no repeats
    assert max(a) < 60                            # drawn only from the top k * 3


def test_refresh_with_short_lists():
    assert refresh([5, 6], 20, np.random.default_rng(0)) == [5, 6]
    assert refresh(list(range(25)), 20, np.random.default_rng(0)) == list(range(20)) or len(refresh(list(range(25)), 20, np.random.default_rng(0))) == 20


def test_days_overlap_but_differ():
    items = list(range(60))
    day1 = set(refresh(items, 20, np.random.default_rng(10)))
    day2 = set(refresh(items, 20, np.random.default_rng(11)))
    assert 5 <= len(day1 & day2) < 20            # strong core stays, part of the row changes


def test_no_language_takes_over_the_first_twelve():
    langs = ["ko"] * 15 + ["ja"] * 5 + ["hi"] * 5
    out = spread_languages(list(range(25)), langs, cap=0.5, window=12)
    assert sum(1 for i in out[:12] if langs[i] == "ko") == 6
    assert sorted(out) == list(range(25))        # nothing lost
    assert out[:6] == [0, 1, 2, 3, 4, 5]         # order inside the allowed ones is kept


def test_modes_are_ordered_by_diversity():
    assert MODES["familiar"]["lambda"] > MODES["balanced"]["lambda"] > MODES["discover"]["lambda"]
    assert MODES["familiar"]["tail_share"] < MODES["balanced"]["tail_share"] < MODES["discover"]["tail_share"]
