"""The anime model file: any structural problem is rejected (the site then keeps the earlier anime order)."""
import math

import pytest

from cinematch_engine import anime_model_file as amf

GOOD = {"long": {"10": [[11, 0.5]]}, "mid": {"10": [[11, 0.4]]}, "short": {"10": [[11, 0.3], [12, 0.1]]}}


def test_good_file_gives_three_catalog_matrices():
    m = amf.parse({"models": GOOD}, [10, 11, 12])
    assert set(m) == {"long", "mid", "short"}
    assert m["short"][0, 1] > m["short"][0, 2] > 0 and m["long"][1, 0] == 0


@pytest.mark.parametrize("data", [
    None, [], "x", {}, {"models": None}, {"models": []}, {"models": "x"},
    {"models": {**GOOD, "mid": None}}, {"models": {**GOOD, "mid": []}}, {"models": {"long": GOOD["long"]}},
    {"models": {**GOOD, "mid": {"10": None}}}, {"models": {**GOOD, "mid": {"10": {"11": 0.4}}}},
    {"models": {**GOOD, "mid": {"ten": [[11, 0.4]]}}},
    {"models": {**GOOD, "mid": {"10": [[11]]}}}, {"models": {**GOOD, "mid": {"10": [[11, 0.4, 1]]}}},
    {"models": {**GOOD, "mid": {"10": [11, 0.4]}}}, {"models": {**GOOD, "mid": {"10": [["11", 0.4]]}}},
    {"models": {**GOOD, "mid": {"10": [[11, "0.4"]]}}}, {"models": {**GOOD, "mid": {"10": [[11, None]]}}},
    {"models": {**GOOD, "mid": {"10": [[11, True]]}}}, {"models": {**GOOD, "mid": {"10": [[11.5, 0.4]]}}},
    {"models": {**GOOD, "mid": {"10": [[11, math.nan]]}}}, {"models": {**GOOD, "mid": {"10": [[11, math.inf]]}}},
    {"models": {**GOOD, "mid": {"10": [[11, -math.inf]]}}},
])
def test_malformed_structure_or_votes_are_rejected(data):
    with pytest.raises(amf.BadModelFile):
        amf.parse(data, [10, 11, 12])


def test_a_bad_vote_outside_the_catalog_still_rejects_the_file():
    bad = {**GOOD, "mid": {"10": [[11, 0.4]], "98": [[99, math.nan]]}}
    with pytest.raises(amf.BadModelFile):
        amf.parse({"models": bad}, [10, 11, 12])


def test_no_overlap_with_the_catalog_is_rejected():
    with pytest.raises(amf.BadModelFile):
        amf.parse({"models": GOOD}, [98, 99])


def test_known_inputs_are_rows_that_vote_in_the_reference_model():
    m = amf.parse({"models": {**GOOD, "mid": {"11": [[12, 0.2]]}}}, [10, 11, 12])
    # catalog rows 0, 1, 2 = tmdb 10, 11, 12. 10 votes in "long"/"short" but not in "mid"; 12 only receives votes
    assert amf.known_inputs(m, [0, 1, 2]) == [1]
