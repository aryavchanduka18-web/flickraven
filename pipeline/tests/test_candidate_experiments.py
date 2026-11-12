"""Candidate-source experiments: arm selectors, verdict rule, summary and pool injection on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from cinematch_engine import online
from cinematch_engine.sources import SOURCES
from pipeline import candidate_experiments as ce
from pipeline import candidate_recall as cr


def test_recent_rows_window_kind_blocked_and_order():
    year = np.array([2019, 2020, 2021, 2021, 2022, 2010, np.nan])
    kind = ["movie", "movie", "movie", "tv", "movie", "movie", "movie"]
    pop = np.array([5.0, 4.0, 9.0, 99.0, 1.0, 50.0, 7.0])
    # t_year 2021 -> window 2019..2021; row 3 is a series, row 4 is after T, row 5 too old, row 6 no year; row 0 blocked
    assert ce.recent_rows(year, kind, pop, 2021, 5, blocked=[0]).tolist() == [2, 1]
    assert ce.recent_rows(year, kind, pop, 2021, 1, blocked=[]).tolist() == [2]


def test_nonml_rows_needs_positive_similarity():
    content = np.array([0.9, -0.1, 0.5, np.nan, 0.7, 0.0])
    assert ce.nonml_rows([0, 1, 2, 3, 4, 5], content, 10, blocked=[4]).tolist() == [0, 2]
    assert ce.nonml_rows([0, 1, 2, 3, 4, 5], content, 1, blocked=[]).tolist() == [0]


def test_strong_ratings():
    r = {1: 10.0, 2: 9.0, 3: 8.0, 4: 7.0, 5: 6.0, 6: 9.0, 7: 3.0}
    assert ce.strong_ratings(r, "strong9") == {1: 10.0, 2: 9.0, 6: 9.0}
    assert set(ce.strong_ratings(r, "top5")) == {1, 2, 6, 3, 4}
    with pytest.raises(ValueError):
        ce.strong_ratings(r, "nope")


def test_paired_and_verdict():
    d, se = ce.paired([0.1, 0.1, 0.1, 0.1])
    assert d == pytest.approx(0.1) and se == pytest.approx(0.0)
    assert ce.verdict(0.0, 0.0, 0, 0, 0, 0) == "no change"
    assert ce.verdict(0.03, 0.01, 0.0, 0.01, 0.0, 0.01) == "win"
    assert ce.verdict(0.03, 0.01, -0.05, 0.01, 0.0, 0.01) == "regresses diversity/tail"     # ILD drop > 2 SE
    assert ce.verdict(0.015, 0.01, 0.0, 0.01, 0.0, 0.01) == "no significant change"         # under 2 SE
    assert ce.verdict(-0.03, 0.01, 0.0, 0.01, 0.0, 0.01) == "worse"


def test_top10_mix():
    language = ["en", "hi", "ko", "ja", "fr", "en"]
    nonml = np.array([False, True, True, False, False, False])
    unhit = np.array([False, True, False, False, False, False])
    m = ce.top10_mix([1, 0, 2, 3], language, nonml, unhit)
    assert m["english"] == 0.25 and m["non_english"] == 0.75
    assert m["hi"] == m["ko"] == m["ja"] == 0.25
    assert m["nonml_top10"] == 0.5 and m["nonml_at_1"] == 1.0 and m["unhittable_top10"] == 0.25


def _rows(arm, ndcgs, ilds, tails):
    out = []
    for u, (n, i, t) in enumerate(zip(ndcgs, ilds, tails)):
        r = {"stage": "established", "arm": arm, "user": u, "relevant": 10, "pool_size": 260, "seconds": 0.05,
             "arm_added": 5 if arm != "baseline" else 0, "arm_hits": 1 if arm != "baseline" else 0,
             "pool_recall": 0.4, "recent_recall": np.nan, "nonml_recall": 0.2,
             **{f"recall@{k}": 0.2 for k in cr.RECALL_AT}}
        for m in ce.MODES:
            r.update({f"ndcg_{m}": n, f"ild_{m}": i, f"tail_{m}": t, f"rows_{m}": [u, u + 1]})
            r.update({f"{k}_{m}": 0.0 for k in ("english", "non_english", "hi", "ko", "ja", "nonml_top10",
                                               "nonml_at_1", "unhittable_top10")})
        out.append(r)
    return out


def test_summarise_pairs_against_baseline():
    rng = np.random.default_rng(0)
    base = rng.random(50) * 0.2
    R = pd.DataFrame(_rows("baseline", base, [0.8] * 50, [0.1] * 50)
                     + _rows("better", base + 0.05 + rng.normal(0, 0.005, 50), [0.8] * 50, [0.1] * 50)
                     + _rows("narrower", base + 0.05, [0.7] * 49 + [0.71], [0.1] * 50))
    s = ce.summarise(R, pd.DataFrame())["established"]
    assert s["baseline"]["balanced"]["verdict"] == "baseline"
    assert s["better"]["balanced"]["verdict"] == "win"
    assert s["better"]["balanced"]["ndcg_delta"] == pytest.approx(0.05, abs=0.005)
    assert s["narrower"]["familiar"]["verdict"] == "regresses diversity/tail"
    assert s["better"]["relevant_found_via_arm_share"] == pytest.approx(0.1)


class StubEngine:
    """Calls candidate_pool through the online module and adds films the way OnlineEngine does (top per_source by score)."""

    def __init__(self, n=400):
        rng = np.random.default_rng(1)
        self.scores = {s: rng.random(n) for s in SOURCES}
        for v in self.scores.values():
            v[380:] = -np.inf                           # rows 380+: no source can propose them
        self.rail = rng.random(n)

    def _add_unavailable_candidates(self, st, scores, excl, pool, norm, final, w, per_source=50, rows=None):
        rows = np.arange(390, 392) if rows is None else np.asarray(rows)
        rows = rows[~np.isin(rows, pool)]
        top = rows[np.argsort(-self.rail[rows], kind="stable")[:per_source]]
        return (np.concatenate([pool, top]), np.concatenate([norm, np.zeros((norm.shape[0], len(top)))], axis=1),
                np.concatenate([final, np.full(len(top), -1.0)]))

    def top_picks(self, st, mode, k=10, scores=None):
        pool, norm = online.candidate_pool({s: v[None, :] for s, v in self.scores.items()}, [np.array([0, 1])])
        p, nm = pool[0], norm[:, 0]
        p, nm, final = self._add_unavailable_candidates(st, None, None, p, nm, nm.sum(axis=0), {})
        return [{"row": int(r)} for r in p[np.argsort(-final)][:k]]


def test_inject_adds_rows_through_the_engine_and_leaves_baseline_alone():
    eng = StubEngine()
    base, prop0, _ = cr.pool_and_picks(eng, None, None, 50)
    seen = {}

    def inj(st, sc, excl, pool):
        seen["pool"] = len(pool)
        return np.array([383, 384, 390])                 # 390 is already in the pool via the normal channel

    arm, prop1, _ = cr.pool_and_picks(eng, None, None, 50, inject=inj)
    assert prop0["arm"] == set() and prop1["arm"] == {383, 384}
    assert seen["pool"] == len(base)                      # inject sees the pool after the normal additions
    assert set(arm.tolist()) == set(base.tolist()) | {383, 384}
    assert "_add_unavailable_candidates" not in eng.__dict__
