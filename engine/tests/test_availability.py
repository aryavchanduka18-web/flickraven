"""Films without collaborative factors: "unavailable" is not "low" (cinematch_engine/availability.py)."""
import numpy as np
import pytest

from cinematch_engine.availability import AvailabilityMap, renormalized

W = {"popularity": 0.0, "content": 0.1, "item_cf": 0.1, "user_cf": 0.1, "svd": 0.0, "als": 0.7}
NAN = np.nan


def test_renormalized_is_average_of_available_sources_not_sum_with_zeros():
    p = {"content": np.array([0.9, 0.9], np.float32), "als": np.array([0.9, NAN], np.float32),
         "item_cf": np.array([0.9, NAN], np.float32), "user_cf": np.array([0.9, NAN], np.float32)}
    out = renormalized(p, W, np.array([0, 1]))
    assert np.allclose(out, [0.9, 0.9])          # the old rule would give 0.09 for the second film


def test_renormalized_all_unavailable_is_zero_not_nan():
    out = renormalized({"content": np.array([NAN], np.float32)}, W, np.array([0]))
    assert out.tolist() == [0.0]


def curves():
    # known films: score 0.2 -> 40% chance of a 7+, 0.8 -> 80%. unavailable films: 0.5 -> 60%, 1.0 -> 90%.
    return {"established": {"known": {"x": [0.2, 0.8], "y": [0.4, 0.8]}, "new": {"x": [0.0, 0.5, 1.0], "y": [0.3, 0.6, 0.9]}}}


def test_map_matches_probabilities_and_is_monotone():
    m = AvailabilityMap(curves())
    out = m.map_unavailable("established", np.array([0.0, 0.5, 0.75, 1.0], np.float32))
    assert (np.diff(out) >= 0).all()
    # 60% for an unavailable film = the score at which a known film also has 60% (0.5 on the straight part)
    assert abs(out[1] - 0.5) < 1e-6
    assert out[0] == np.float32(0.2) and out[-1] == np.float32(0.8)     # clipped to the known curve's range


def test_missing_stage_falls_back_to_warming():
    c = curves()
    c["warming"] = c.pop("established")
    out = AvailabilityMap(c).map_unavailable("cold", np.array([0.5], np.float32))
    assert abs(out[0] - 0.5) < 1e-6


@pytest.mark.parametrize("mapping", ["quantile", "probability"])
def test_engine_scores_film_without_factors_by_available_sources(mapping):
    """An established user, a film MovieLens never rated with a strong content match: scored on the MovieLens scale
    by content, not 0.1 (content weight x percentile). Both the quantile mapping (default) and the old probability map."""
    from types import SimpleNamespace
    from cinematch_engine.online import OnlineEngine, UserState
    from tests.test_kind_rank import cat
    c = cat(["movie"] * 4, [5, 5, 5, 5])
    c.universe_of_row = np.array([0, 1, -1, -1])
    c.universe_rows = np.array([0, 1])
    e = SimpleNamespace(cat=c, weights={"established": W}, availability=AvailabilityMap(curves()),
                        unavailable_mapping=mapping)
    e.unavailable_rows = lambda: OnlineEngine.unavailable_rows(e)
    e._quantile_unavailable = lambda *a: OnlineEngine._quantile_unavailable(e, *a)
    e.excluded = lambda st: np.array([], dtype=np.int64)
    n = c.n
    scores = {s: np.full(n, -np.inf, np.float32) for s in ("popularity", "content", "item_cf", "user_cf", "svd", "als")}
    scores["content"] = np.array([0.1, 0.2, 0.9, 0.3], np.float32)
    scores["als"][:2] = [0.3, 0.9]
    st = UserState(); st.behavioral_count = 30
    base = np.array([0.0, 0.7, 0.0, 0.0], np.float32)                       # what the old rule gave
    out = OnlineEngine._score_unavailable(e, st, scores, base)
    assert out[2] > out[3] > 0.0 and out[2] > 0.1                          # strong content match is no longer capped at 0.1
    assert out[0] == base[0] and out[1] == base[1]                          # MovieLens films keep their score
