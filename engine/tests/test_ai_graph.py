import numpy as np

from cinematch_engine import ai_graph


def test_names_are_matched_by_kind_title_and_year_and_made_symmetric():
    ids = [10, 11, 12, 13, 14]
    titles = ["Alpha", "Beta", "Beta", "Gamma", "Alpha"]
    years = [2010.0, 2012.0, 2001.0, float("nan"), 2010.0]
    kinds = ["series", "series", "series", "anime", "movie"]
    named = {"10": ["beta (2013)", "Beta (2001)", "Gamma (2015)", "Nonsense", "Alpha (2010)"], "14": ["Beta (2012)"], "99": ["Beta (2012)"]}
    sim = ai_graph.build(ids, titles, years, kinds, named).toarray()
    assert sim[0, 1] == sim[1, 0] == 1.0                    # first name, year within one
    assert abs(sim[0, 2] - 0.85) < 1e-6                     # "Beta (2001)" is the second name: the other Beta, weight falls
    assert sim[0, 3] == 0                                   # Gamma is anime, seed is a series
    assert sim[0, 0] == 0 and sim[4].sum() == 0             # never itself; a film seed is ignored


def test_nothing_matches_gives_none_and_rank_weight_falls():
    assert ai_graph.build([1, 2], ["A", "B"], [2000.0, 2000.0], ["series", "series"], {"1": ["Z (2000)"]}) is None
    sim = ai_graph.build([1, 2, 3], ["A", "B", "C"], [2000.0] * 3, ["series"] * 3, {"1": ["B (2000)", "C (2000)"]}).toarray()
    assert sim[0, 1] > sim[0, 2] >= ai_graph.LAST - 1e-6
