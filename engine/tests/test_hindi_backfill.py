"""Hindi cold-start short-list backfill (online.OnlineEngine.backfill_short_list). Fakes stand in for the engine, so no data is needed."""
from types import SimpleNamespace

import numpy as np

from cinematch_engine.online import BACKFILL_PERCENTILE, OnlineEngine, UserState


def pick(row, score):
    return {"row": row, "score": score, "match_pct": 50, "shares": {}, "reranked": False}


def fake_engine(second_pass):
    """`second_pass` is what the no-tail pass over the pool returns; calls are recorded."""
    calls = []

    def top_picks(st, mode, k=20, extra_exclude=(), scores=None, tuning=None, no_tail=False):
        calls.append(dict(mode=mode, k=k, extra_exclude=tuple(extra_exclude), no_tail=no_tail))
        return list(second_pass)
    return SimpleNamespace(top_picks=top_picks, calls=calls)


def run(existing, second_pass, k=10, **kw):
    eng = fake_engine(second_pass)
    out = OnlineEngine.backfill_short_list(eng, UserState(languages=["hi"]), "balanced", k, existing, kw.get("extra_exclude", ()), None, None)
    return out, eng


def pool_of(n=100):
    return [pick(1000 + i, 1.0 - i / n) for i in range(n)]      # scores 1.00 down to 0.01, already ranked


def test_percentile_is_90():
    assert BACKFILL_PERCENTILE == 90


def test_existing_films_and_order_are_kept_and_only_top_decile_is_added():
    pool = pool_of()
    existing = [pick(5, 0.9), pick(6, 0.8)]
    out, eng = run(existing, pool)
    assert [p["row"] for p in out[:2]] == [5, 6]
    added = out[2:]
    thr = np.percentile([p["score"] for p in pool], 90)
    assert added and all(p["score"] >= thr for p in added)
    assert len(out) == 10 or len(added) == sum(p["score"] >= thr for p in pool)
    assert eng.calls[0]["no_tail"] is True and eng.calls[0]["k"] == 100 and eng.calls[0]["mode"] == "balanced"


def test_weak_candidates_are_never_forced_in():
    """With room for 50 films, only the films that clear the cut are added; the list is not padded to k."""
    pool = pool_of()
    thr = np.percentile([p["score"] for p in pool], 90)
    out, _ = run([pick(5, 0.9)], pool, k=50)
    added = out[1:]
    assert 0 < len(added) < 49 and len(added) == sum(p["score"] >= thr for p in pool)
    assert all(p["score"] >= thr for p in added)


def test_no_duplicates_and_never_more_than_k():
    pool = pool_of()
    existing = [pick(1000, 0.9), pick(1001, 0.9)]            # already listed films that are also in the pool
    out, _ = run(existing, pool)
    rows = [p["row"] for p in out]
    assert len(rows) == len(set(rows)) <= 10
    out3, _ = run([pick(i, 0.5) for i in range(9)], pool)
    assert len(out3) == 10                                   # one slot left, one film added


def test_extra_exclusions_are_passed_to_the_second_pass():
    _, eng = run([pick(5, 0.9)], pool_of(), extra_exclude=(42, 43))
    assert eng.calls[0]["extra_exclude"] == (42, 43)


def test_empty_pool_leaves_list_alone():
    existing = [pick(5, 0.9)]
    out, _ = run(existing, [])
    assert out == existing


def applies(languages, behavioral, mode="balanced", picks=0):
    st = UserState(languages=languages, behavioral_count=behavioral)
    return OnlineEngine.hindi_cold_backfill_applies(SimpleNamespace(), st, mode)


def test_only_cold_hindi_balanced_users_are_covered():
    assert applies(["hi"], 0) and applies(["hi", "en"], 2)
    assert not applies(["ko"], 0) and not applies([], 0)           # Korean and users with no language
    assert not applies(["hi"], 5) and not applies(["hi"], 20)       # warming and established
    assert not applies(["hi"], 0, "discover") and not applies(["hi"], 0, "familiar")
