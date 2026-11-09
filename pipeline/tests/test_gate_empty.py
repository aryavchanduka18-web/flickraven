"""A candidate list with no rows (a monthly run that found nothing new) is gated to an empty result, not a crash."""
from datetime import date
from importlib import import_module

import pandas as pd

clean = import_module("pipeline.05_clean")


def test_empty_candidate_list():
    cand = pd.DataFrame(columns=["tmdb_id", "tmdb_vote_count", "part", "found_on"])
    gated, details = clean.gate(cand)
    assert gated.empty and details == {}
    # the selection code that reads the gated frame works on it
    kept = gated[gated["passed"].fillna(False).astype(bool) & (gated["status"] == "Released")
                 & (pd.to_datetime(gated["release_date"]).dt.date <= date.today())
                 & ~gated["tmdb_id"].isin([1, 2])].drop_duplicates("tmdb_id")
    assert kept.empty and {"part", "found_on"} <= set(kept.columns)
