"""The anime model file: any structural problem is rejected (the site then keeps the earlier anime order)."""
import json
import math

import numpy as np
import pytest

from cinematch_engine import anime_model_file as amf


def arrays(**over):
    a = {"settings": np.array(json.dumps({"ratings": "x"}))}
    for t, votes in {"long": [(10, 11, 0.5)], "mid": [(10, 11, 0.4)], "short": [(10, 11, 0.3), (10, 12, 0.1)]}.items():
        a[f"{t}_src"] = np.array([v[0] for v in votes], dtype=np.int64)
        a[f"{t}_dst"] = np.array([v[1] for v in votes], dtype=np.int64)
        a[f"{t}_w"] = np.array([v[2] for v in votes], dtype=np.float32)
    a.update(over)
    return {k: v for k, v in a.items() if v is not None}


def save(tmp_path, a):
    p = tmp_path / "anime_model.npz"
    with open(p, "wb") as f:
        np.savez_compressed(f, **a)
    return p


def test_good_file_gives_three_catalog_matrices(tmp_path):
    p = save(tmp_path, arrays())
    m = amf.load(p, [10, 11, 12])
    assert set(m) == {"long", "mid", "short"}
    assert m["short"][0, 1] > m["short"][0, 2] > 0 and m["long"][1, 0] == 0
    assert amf.settings(p) == {"ratings": "x"}


def test_catalog_order_is_respected():
    m = amf.parse(arrays(), [12, 11, 10])            # tmdb 10 is row 2, 11 is row 1
    assert m["long"][2, 1] == pytest.approx(0.5) and m["long"].nnz == 1


@pytest.mark.parametrize("over", [
    {"mid_src": None}, {"mid_w": None}, {"long_dst": None},
    {"mid_src": np.array([10.0, 10.0])},                                    # length differs
    {"mid_src": np.array([10.5])}, {"mid_dst": np.array(["11"])},            # ids not integers
    {"mid_w": np.array([1], dtype=np.int64)}, {"mid_w": np.array(["0.4"])},  # votes not floats
    {"mid_w": np.array([math.nan], dtype=np.float32)}, {"mid_w": np.array([math.inf])},
    {"mid_w": np.array([-math.inf])}, {"mid_src": np.array([[10]])},          # not 1-D
    {"mid_w": np.array([1e300])},                                           # finite, but inf as float32
    {"mid_w": np.array([0.0], dtype=np.float32)}, {"mid_w": np.array([-0.4], dtype=np.float32)},
    {"mid_src": np.array([0])}, {"mid_dst": np.array([-11])},
    {"mid_src": np.array([2**64 - 1], dtype=np.uint64)},
])
def test_malformed_arrays_are_rejected(over):
    with pytest.raises(amf.BadModelFile):
        amf.parse(arrays(**over), [10, 11, 12])


def test_a_bad_vote_outside_the_catalog_still_rejects_the_file():
    a = arrays(mid_src=np.array([10, 98]), mid_dst=np.array([11, 99]), mid_w=np.array([0.4, math.nan]))
    with pytest.raises(amf.BadModelFile):
        amf.parse(a, [10, 11, 12])


def test_no_overlap_with_the_catalog_is_rejected():
    with pytest.raises(amf.BadModelFile):
        amf.parse(arrays(), [98, 99])
    with pytest.raises(amf.BadModelFile):
        amf.parse(arrays(), [])


def test_pickled_objects_are_refused(tmp_path):
    p = save(tmp_path, arrays(mid_src=np.array([10, None], dtype=object)))
    with pytest.raises(ValueError):          # np.load(allow_pickle=False) refuses object arrays
        amf.load(p, [10, 11, 12])


def test_known_inputs_are_rows_that_vote_in_the_reference_model():
    a = arrays(mid_src=np.array([11]), mid_dst=np.array([12]), mid_w=np.array([0.2], dtype=np.float32))
    m = amf.parse(a, [10, 11, 12])
    # catalog rows 0, 1, 2 = tmdb 10, 11, 12. 10 votes in "long"/"short" but not in "mid"; 12 only receives votes
    assert amf.known_inputs(m, [0, 1, 2]) == [1]
