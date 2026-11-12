"""Round-2 candidate experiments: content blend, mix guard, recent row, D verdict, on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from pipeline import candidate_experiments_2 as c2

LANG = ["en", "en", "hi", "ko", "en", "ja", "en", "en", "fr", "hi"]
GEN = [["Drama"], ["Comedy"], ["Drama"], ["Crime"], ["Drama"], ["Animation"], ["Comedy"], [], ["Drama"], ["Romance"]]


def test_blend_content_handles_missing_sides():
    full = np.array([1.0, 0.0, np.nan, -np.inf])
    strong = np.array([0.0, 1.0, 0.4, np.nan])
    out = c2.blend_content(full, strong, 0.25)
    assert out[:2] == pytest.approx([0.75, 0.25])
    assert out[2] == pytest.approx(0.4)          # only strong is finite
    assert not np.isfinite(out[3])                # neither finite: stays non-finite


def test_groups_of():
    assert c2.groups_of(2, LANG, GEN) == {"lang:non_en", "lang:hi", "genre:Drama"}
    assert c2.groups_of(7, LANG, GEN) == {"lang:en"}


def test_mix_guard_restores_language_and_genre_counts():
    base = [0, 2, 3]                              # en Drama, hi Drama, ko Crime
    arm = [0, 1, 4]                               # en Drama, en Comedy, en Drama: lost hi, ko, Crime
    out = c2.mix_guard(arm, base, [6, 9, 3, 2, 8], LANG, GEN)
    assert 0 in out and len(out) == 3
    count = lambda rows, g: sum(g in c2.groups_of(r, LANG, GEN) for r in rows)
    for g in ("lang:hi", "lang:ko", "genre:Crime", "genre:Drama"):
        assert count(out, g) >= count(base, g)


def test_mix_guard_leaves_a_list_that_already_matches():
    assert c2.mix_guard([0, 2, 3], [0, 2, 3], [5, 6], LANG, GEN) == [0, 2, 3]


def test_top_recent():
    score = np.array([0.1, 0.9, 0.5, np.nan, 0.8, 0.7])
    mask = np.array([True, True, True, True, False, True])
    assert c2.top_recent(score, mask, excluded=[1], k=3).tolist() == [5, 2, 0]
    assert c2.top_recent(score, np.zeros(6, bool), excluded=[], k=3).tolist() == []


def test_row_metrics():
    nonml = np.zeros(10, bool)
    nonml[2] = True
    m = c2.row_metrics([2, 3, 4, 5], {2, 9}, top_picks=[4, 7], language=LANG, nonml_mask=nonml)
    assert m["recall"] == 0.5 and m["hit"] == 1.0 and m["size"] == 4
    assert m["hi"] == 0.25 and m["ko"] == 0.25 and m["ja"] == 0.25 and m["non_english"] == 0.75
    assert m["nonml"] == 0.25 and m["overlap_top_picks"] == 0.25
    assert c2.row_metrics([1], set(), [], LANG, nonml) == {}


def _mode(**kw):
    m = {f"{k}_delta": 0.0 for k in c2.MIX_KEYS} | {f"{k}_se": 0.01 for k in c2.MIX_KEYS}
    m["distinct_films"] = 100
    m.update(kw)
    return m


def test_d_verdict():
    base = {"distinct_films": 100}
    assert c2.d_verdict(_mode(), base, 0.1, 0.01) == "win"
    assert c2.d_verdict(_mode(), base, 0.01, 0.01) == "no: non-ML recall"
    assert c2.d_verdict(_mode(ndcg_delta=-0.05), base, 0.1, 0.01) == "no: NDCG"
    assert c2.d_verdict(_mode(non_english_delta=-0.05), base, 0.1, 0.01) == "no: mix/diversity"
    assert c2.d_verdict(_mode(distinct_films=80), base, 0.1, 0.01) == "no: distinct films"


def test_summarise_d_on_synthetic_rows():
    rows = []
    rng = np.random.default_rng(0)
    for arm, shift in (("baseline", 0.0), ("D1_0.5", 0.2)):
        for u in range(30):
            r = {"stage": "established", "arm": arm, "user": u, "relevant": 10, "seconds": 0.05,
                 "pool_recall": 0.4, "nonml_recall": 0.2 + shift + rng.normal(0, 0.01),
                 **{f"recall@{k}": 0.2 for k in (50, 100, 200)}}
            for m in ("familiar", "balanced"):
                r.update({f"{k}_{m}": 0.5 for k in c2.MIX_KEYS})
                r[f"ndcg_{m}"] = 0.1 + rng.normal(0, 0.001)
                r[f"rows_{m}"] = [u, u + 100]
            rows.append(r)
    s = c2.summarise_d(pd.DataFrame(rows), pd.DataFrame())["established"]
    assert s["D1_0.5"]["nonml_recall_delta"] == pytest.approx(0.2, abs=0.01)
    assert s["D1_0.5"]["balanced"]["verdict"] == "win"
    assert s["baseline"]["familiar"]["verdict"] == "baseline"
