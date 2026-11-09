"""The widened catalog keeps the saved models valid: every addition run gets its own content stage."""
import numpy as np
import pandas as pd

from pipeline.catalog import original_gate_mask
from pipeline.models_io import catalog_stage
from pipeline.widen_catalog import queries


def movies():
    return pd.DataFrame({
        "relaxed_gate": [False, True, False, False, False, False],
        "franchise_rule": [False, False, True, False, False, False],
        "added_on": [None, None, None, "2026-11-09", "2026-11-10", "2026-11-09"],
    })


def test_stage_is_first_build_relaxed_franchise_then_one_per_run_date():
    assert catalog_stage(movies()).tolist() == [0, 1, 2, 3, 4, 3]


def test_added_films_are_outside_the_vocabulary_fit():
    assert original_gate_mask(movies()).tolist() == [True, False, False, False, False, False]


def test_a_later_run_never_moves_an_earlier_stage():
    later = pd.concat([movies(), pd.DataFrame({"relaxed_gate": [False], "franchise_rule": [False],
                                               "added_on": ["2026-12-01"]})], ignore_index=True)
    assert catalog_stage(later).tolist()[:6] == catalog_stage(movies()).tolist() and catalog_stage(later)[-1] == 5


def test_every_discover_query_is_bounded_and_keyed():
    qs = queries()
    assert len({k for _, k, *_ in qs}) == len(qs)                 # cache keys are unique
    assert all(0 < limit <= 10000 for _, _, limit, _, _ in qs)     # TMDB returns at most 10,000 per query
    assert {g for g, *_ in qs} == {"indian", "hollywood", "korean_japanese", "everything_else"}


def test_series_run_gets_a_stage_after_widened_films_of_the_same_day():
    m = pd.DataFrame({"relaxed_gate": [False] * 4, "franchise_rule": [False] * 4,
                      "added_on": ["2026-11-09", "2026-11-10", "2026-11-10~series", "2026-12-10"]})
    assert catalog_stage(m).tolist() == [3, 4, 5, 6]
