import numpy as np

from cinematch_engine.rerank import mmr, spread, tail_slots


def test_slots_never_exceed_half_the_list():
    assert tail_slots(10, 0.1) == 1 and tail_slots(20, 0.1) == 2 and tail_slots(10, 0.0) == 0
    assert tail_slots(10, 0.9) == 5 and tail_slots(1, 0.5) == 0


def test_spread_places_tail_picks_apart():
    out = spread(np.arange(8), np.array([100, 101]))
    assert len(out) == 10 and sorted(out.tolist()) == [0, 1, 2, 3, 4, 5, 6, 7, 100, 101]
    assert out[:2].tolist() == [0, 1] and abs(int(np.nonzero(out == 100)[0][0]) - int(np.nonzero(out == 101)[0][0])) >= 3


def test_mmr_respects_allowed_and_already():
    items = np.arange(6)
    rel = np.array([1.0, 0.9, 0.8, 0.7, 0.6, 0.5], dtype=np.float32)
    sim = np.eye(6, dtype=np.float32)
    novelty = np.zeros(6, dtype=np.float32)
    tail = np.array([False, False, False, False, True, True])
    first = mmr(items, rel, sim, novelty, 1, 0.9, 0.0, allowed=tail)
    assert first.tolist() == [4]
    rest = mmr(items, rel, sim, novelty, 2, 0.9, 0.0, allowed=~tail, already=np.array([4]))
    assert rest.tolist() == [0, 1]
