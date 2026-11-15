"""The first hero slide changes every day: one of the hero's strong picks leads, the rest keep their order."""
import numpy as np

from cinematch_engine.rerank import lead_of_day


def test_no_rng_or_one_item_changes_nothing():
    assert lead_of_day([1, 2, 3], None) == [1, 2, 3]
    assert lead_of_day([7], np.random.default_rng(0)) == [7]
    assert lead_of_day([], np.random.default_rng(0)) == []


def test_same_seed_same_lead_and_nothing_added_or_lost():
    items = list(range(5))
    for s in range(30):
        a = lead_of_day(items, np.random.default_rng(s))
        assert a == lead_of_day(items, np.random.default_rng(s))         # same day, same page
        assert sorted(a) == items                                         # order only
        assert a[1:] == [x for x in items if x != a[0]]                   # the others keep their order


def test_lead_rotates_among_the_first_five_with_a_lean_to_the_top():
    items = list(range(8))
    leads = [lead_of_day(items, np.random.default_rng(s))[0] for s in range(2000)]
    counts = np.bincount(leads, minlength=8)
    assert counts[5:].sum() == 0                                          # never beyond the first five
    assert all(c > 0 for c in counts[:5])                                 # every strong pick gets days
    assert counts[0] > counts[4]                                          # the best leads most often
    assert counts[0] < 0.4 * len(leads)                                   # but not most days
