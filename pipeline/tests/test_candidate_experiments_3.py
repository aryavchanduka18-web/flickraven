"""Round-3 candidate experiments: guard groups, distinct bootstrap, strict acceptance, usable users (synthetic data)."""
import numpy as np
import pandas as pd
import pytest

from pipeline import candidate_experiments_2 as c2
from pipeline import candidate_experiments_3 as c3

LANG = ["en"] * 6 + ["hi", "en"]
GEN = [["Drama"]] * 8
FAME = np.array([99, 99, 99, 10, 20, 99, 30, 99], float)       # rows 3, 4, 6 are long tail (< 80)


def test_ci95():
    assert c3.ci95(0.1, 0.01) == [pytest.approx(0.0804), pytest.approx(0.1196)]


def test_tail_rare_extra_and_frequencies():
    freq = c3.frequencies([[0, 1], [0, 2], [0, 3]])
    assert freq == {0: 3, 1: 1, 2: 1, 3: 1}
    extra = c3.tail_rare_extra(FAME, 80, freq)
    assert extra(0) == set()                 # popular, shown to 3 users
    assert extra(1) == {"rare"}
    assert extra(3) == {"tail", "rare"}
    assert extra(7) == {"rare"}              # never shown by baseline


def test_guard_with_extra_keeps_long_tail_count():
    base = [0, 3, 4]                         # two long-tail films
    arm = [0, 1, 2]                          # none
    freq = c3.frequencies([[0, 1, 2]] * 3)   # 0, 1, 2 shown to many users: not rare
    extra = c3.tail_rare_extra(FAME, 80, freq)
    out = c2.mix_guard(arm, base, ranked=[5, 6, 3, 4], language=LANG, genres=GEN, extra=extra)
    assert sum(FAME[r] < 80 for r in out) >= 2
    plain = c2.mix_guard(arm, base, ranked=[5, 6, 3, 4], language=LANG, genres=GEN)
    assert plain == arm                      # without the extra groups nothing is missing (all English Drama)


def test_distinct_delta():
    base = [[1, 2], [1, 2], [1, 3]]
    arm = [[1, 2], [4, 5], [6, 7]]
    d, se, _ = c3.distinct_delta(base, arm, n_boot=200)
    assert d == 6 - 3 and se > 0             # arm shows {1,2,4,5,6,7}, base {1,2,3}
    same, se0, _ = c3.distinct_delta(base, base, n_boot=50)
    assert same == 0 and se0 == 0


def _m(**over):
    m = {k: {"delta": 0.0, "se": 0.01} for k in c3.METRICS + ("distinct",)}
    m["nonml_recall"] = {"delta": 0.1, "se": 0.01}
    for k, v in over.items():
        m[k] = {"delta": v, "se": 0.01}
    return m


def test_accept_is_strict():
    assert c3.accept(_m()) == (True, [])
    assert c3.accept(_m(nonml_recall=0.01))[1] == ["non-ML recall not up"]
    assert c3.accept(_m(hi=-0.05))[1] == ["hi down"]
    assert c3.accept(_m(distinct=-0.05))[1] == ["distinct down"]
    assert c3.accept(_m(ndcg=0.05))[0]      # better is fine


def test_usable_users():
    before = pd.DataFrame({"user_id": [1] * 11 + [2] * 3 + [3] * 11,
                           "ml_movie_id": list(range(11)) + [0, 1, 2] + list(range(11)),
                           "rating": [8] * 25, "timestamp": [1] * 25})
    after = pd.DataFrame({"user_id": [1, 2, 3, 3], "ml_movie_id": [50, 51, 0, 60], "rating": [9, 9, 9, 5],
                          "timestamp": [5] * 4})
    # user 1: ok. user 2: too few ratings before. user 3: its later positive is a film already rated; 60 is not positive
    assert c3.usable_users(before, after).tolist() == [1]
