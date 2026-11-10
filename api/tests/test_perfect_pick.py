"""Perfect Pick: how three answers become three picks."""
import pytest

from app.services import perfect_pick as pp
from app.services.perfect_pick import Cand


def pool():
    # id, percentile, novelty: 1 is the safest best, 6 the most novel
    return [Cand(1, 1.0, 0.1), Cand(2, 0.9, 0.2), Cand(3, 0.8, 0.3), Cand(4, 0.7, 0.9), Cand(5, 0.6, 0.5), Cand(6, 0.2, 1.0)]


def test_familiar_is_the_top_three_by_score():
    assert [c.id for c in pp.choose(pool(), "familiar")] == [1, 2, 3]


def test_adventurous_leans_on_novelty_but_never_goes_below_the_floor():
    ids = [c.id for c in pp.choose(pool(), "adventurous")]
    assert 4 in ids and 6 not in ids                 # 6 is the most novel but scores 0.2, under the 0.35 floor
    assert all(c.role == "step_out" for c in pp.choose(pool(), "adventurous"))


def test_balanced_has_two_close_picks_and_one_surprise():
    got = pp.choose(pool(), "balanced")
    assert [c.id for c in got] == [1, 2, 4]          # best two, then the most novel title that still scores
    assert [c.role for c in got] == ["close", "close", "surprise"]


def test_small_pools_return_what_exists_and_bad_answers_fail():
    assert [c.id for c in pp.choose([Cand(7, 1.0, 0.5)], "balanced")] == [7]
    assert pp.choose([], "familiar") == []
    with pytest.raises(ValueError):
        pp.choose(pool(), "wild")


def test_percentiles_and_reasons():
    assert pp.pct_of([0.1, 0.9, 0.5]) == [1 / 3, 1.0, 2 / 3]
    exact = pp.reasons("surprise", "Feel-good", True, "1h 40m, 90-120 minutes", 81)
    assert exact[0]["text"] == 'Fits "feel-good"' and "surprise" in exact[2]["text"]
    near = pp.reasons("close", "Scary", False, "x", None)
    assert near[0]["text"].startswith("Not a perfect fit") and near[2]["text"].startswith("High in your own ranking")
    assert "81% match" in pp.reasons("close", "Funny", True, "x", 81)[2]["text"]
