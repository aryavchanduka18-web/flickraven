"""Candidate-recall harness on a tiny synthetic dataset (no artifacts, no database)."""
import numpy as np
import pandas as pd
import pytest

from cinematch_engine import online
from cinematch_engine.sources import SOURCES
from pipeline import candidate_recall as cr

ML2ROW = {101: 0, 102: 1, 103: 2, 104: 3, 105: 4, 106: 5}      # MovieLens id -> catalog row; 999 is not in the catalog


def ratings(rows):
    return pd.DataFrame(rows, columns=["user_id", "ml_movie_id", "rating", "timestamp"])


def test_split_time_and_recent_profile():
    tr = ratings([(1, 101, 8, 10), (1, 102, 6, 30), (1, 103, 9, 20)])
    assert cr.split_time(tr) == 30
    assert list(cr.recent_profile(tr, 2).ml_movie_id) == [103, 102]       # the two most recent, oldest first
    assert len(cr.recent_profile(tr, None)) == 3


def test_strict_relevant_is_temporal_positive_and_eligible():
    before = ratings([(1, 101, 8, 10), (1, 102, 4, 20)])
    after = ratings([
        (1, 103, 9, 40),     # positive, later, eligible -> relevant
        (1, 104, 6, 40),     # later but not positive
        (1, 105, 8, 15),     # positive but at/before T -> seen, not relevant
        (1, 101, 10, 50),    # re-rated later, but already seen before T
        (1, 999, 9, 50),     # not in the catalog
        (1, 106, 7, 60),     # positive, later, but hidden by the engine
    ])
    assert cr.strict_relevant(before, after, 20, ML2ROW, excluded=[5]) == {2}


def test_strict_relevant_boundary_is_strictly_after():
    before = ratings([(1, 101, 8, 10)])
    after = ratings([(1, 102, 8, 10), (1, 103, 8, 11)])
    assert cr.strict_relevant(before, after, 10, ML2ROW) == {2}


def test_recall_and_ndcg():
    assert cr.recall({1, 2, 3, 4}, [9, 1, 2, 8]) == 0.5
    assert cr.recall({1, 2}, [9, 1, 2], k=2) == 0.5
    assert np.isnan(cr.recall(set(), [1]))
    assert cr.ndcg([1, 2], {1, 2}) == pytest.approx(1.0)
    assert cr.ndcg([9, 1], {1}) == pytest.approx(1 / np.log2(3))


def test_buckets():
    assert cr.popularity_bucket(99) == "head"
    assert cr.popularity_bucket(85) == "torso"
    assert cr.popularity_bucket(10) == "long_tail"
    assert cr.decade(1994.0) == "1990s"
    assert cr.decade(float("nan")) == "unknown"


def test_ranked_pool_and_overlap():
    pool = np.array([10, 11, 12, 13])
    norm = np.zeros((len(SOURCES), 4), np.float32)
    norm[SOURCES.index("als"), [0, 1]] = [0.5, 1.0]
    norm[SOURCES.index("popularity"), [1, 2]] = [1.0, 0.5]
    ranked, proposed = cr.ranked_pool(pool, norm, np.array([0.1, 0.9, 0.5, 0.0]), SOURCES)
    assert ranked.tolist() == [11, 12, 10, 13]
    assert proposed["als"] == {10, 11} and proposed["popularity"] == {11, 12} and proposed["svd"] == set()
    ov = cr.source_overlap({10, 11, 99}, proposed)
    assert ov["per_source"]["als"] == (2, 1)            # finds 10 and 11; only it finds 10
    assert ov["per_source"]["popularity"] == (1, 0)
    assert ov["by_n_sources"] == {1: 1, 2: 1, 0: 1}


def test_micro_breakdown_pools_small_buckets():
    items = pd.DataFrame({"language": ["en"] * 40 + ["hi"] * 5, "in_pool": [True] * 10 + [False] * 30 + [True] * 5})
    t = cr.micro_breakdown(items, "language", min_n=30)
    assert t.loc["en", "relevant"] == 40 and t.loc["en", "recall"] == pytest.approx(0.25)
    assert t.loc["other", "relevant"] == 5 and "hi" not in t.index


def test_label_steps_attribute_each_protocol_change():
    tr = ratings([(1, 101, 8, 10), (1, 102, 6, 20)])
    va = ratings([(1, 103, 9, 25)])                     # validation positive: only the strict labels have it
    te = ratings([(1, 104, 8, 40), (1, 101, 8, 45)])    # 101 was seen in training: the audit kept it
    nm = ratings([(1, 105, 9, 5), (1, 106, 9, 50)])     # 105 rated before T: the audit kept it
    s = cr.label_steps(tr, va, te, nm, ML2ROW, profile_rows={1}, excluded=[])
    assert s["audit"] == {0, 3, 4, 5}
    assert s["1_minus_everything_seen_before_T"] == {3, 5}
    assert s["3_plus_validation_positives"] == {2, 3, 5}
    assert s["strict"] == {2, 3, 5}


class StubEngine:
    """Calls candidate_pool through the online module, as OnlineEngine.top_picks does."""

    def __init__(self, n=400):
        rng = np.random.default_rng(0)
        self.scores = {s: rng.random(n) for s in SOURCES}
        for v in self.scores.values():
            v[390:] = -np.inf                           # films no source can score (like films without MovieLens data)
        self.seen_per_source = []

    def _add_unavailable_candidates(self, st, scores, excl, pool, norm, final, w, per_source=50, rows=None):
        self.seen_per_source.append(per_source)
        extra = np.array([n for n in range(390, 390 + per_source // 50) if n not in pool])
        return (np.concatenate([pool, extra]), np.concatenate([norm, np.zeros((norm.shape[0], len(extra)))], axis=1),
                np.concatenate([final, np.full(len(extra), -1.0)]))

    def top_picks(self, st, mode, k=10, scores=None):
        pool, norm = online.candidate_pool({s: v[None, :] for s, v in self.scores.items()}, [np.array([0, 1])])
        p, nm = pool[0], norm[:, 0]
        final = nm.sum(axis=0)
        p, nm, final = self._add_unavailable_candidates(st, None, None, p, nm, final, {})
        return [{"row": int(r)} for r in p[np.argsort(-final)][:k]]


def test_instrumented_sets_pool_size_records_pool_and_restores():
    eng = StubEngine()
    orig = online.candidate_pool
    r50, prop50, picks = cr.pool_and_picks(eng, None, None, 50)
    r100, prop100, _ = cr.pool_and_picks(eng, None, None, 100)
    assert online.candidate_pool is orig and "_add_unavailable_candidates" not in eng.__dict__
    assert eng.seen_per_source == [50, 100]
    assert all(len(prop100[s]) == 100 for s in SOURCES) and all(len(prop50[s]) == 50 for s in SOURCES)
    assert len(r100) > len(r50) and not ({0, 1} & set(r100.tolist()))     # exclusions respected
    assert prop50["non_movielens_extra"] == {390} and r50[-1] == 390      # added film ranked by its own score
    assert len(picks) == 10 and set(picks.tolist()) <= set(r50.tolist())
