"""Metric helpers of the phase 5 mixed Home replay (pipeline/mixed_home_replay.py)."""
import numpy as np

from pipeline.mixed_home_replay import DISC, first_screen, paired, screen_metrics


def test_first_screen_is_hero_then_ten_top_picks():
    plan = {"hero": [{"row": r} for r in (1, 2, 3, 4, 5)],
            "rails": [{"key": "because", "rows": [99]}, {"key": "top_picks", "rows": list(range(10, 30))}]}
    assert first_screen(plan) == [1, 2, 3, 4, 5] + list(range(10, 20))


def test_screen_metrics_counts_hidden_titles_found():
    lst = list(range(15))
    m = screen_metrics(lst, {0, 14, 99})
    assert m["hit15"] == 1.0
    assert m["recall15"] == 2 / 3                      # 2 of the 3 hidden titles are on the first screen
    assert np.isclose(m["ndcg10"], DISC[0] / DISC[:3].sum())   # slot 15 is outside the NDCG@10 window
    assert screen_metrics(lst, {99})["hit15"] == 0.0


def test_paired_difference_and_interval():
    rows = [{"current": {"x": 0.0}, "mixed": {"x": 1.0}}, {"current": {"x": 1.0}, "mixed": {"x": 1.0}}]
    p = paired(rows, "x")
    assert p["current"] == 0.5 and p["mixed"] == 1.0 and p["diff"] == 0.5
    assert p["ci95"][0] < 0.5 < p["ci95"][1]
