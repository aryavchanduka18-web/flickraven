"""Discover "Recommended for you": the novelty and Tune bonuses re-rank near neighbours but never beat taste on long lists.

Bug (12 Nov): over all 27,000 films the +0.05 novelty bonus moved a film ~1,350 places, so little-known films (mostly
non-MovieLens, for many people Hindi) filled the whole top of the list whatever the person liked."""
from types import SimpleNamespace

import numpy as np

from app.routers import catalog as catalog_router
from cinematch_engine.online import Tuning


def fake_engine(n, novelty):
    cat = SimpleNamespace(row_of={i: i for i in range(n)}, novelty=np.asarray(novelty, np.float32))
    rail = np.linspace(0.0, 1.0, n, dtype=np.float32)            # film i's taste score grows with i: n-1 is best
    return SimpleNamespace(cat=cat, rail_scores=lambda st: rail, _tuning_boost=lambda r, t: np.zeros(len(r), np.float32))


def run(monkeypatch, n, novelty):
    e = fake_engine(n, novelty)
    monkeypatch.setattr(catalog_router.rec, "load_engine", lambda db: e)
    monkeypatch.setattr(catalog_router.rec, "user_state", lambda db, uid, eng: SimpleNamespace(stage="warming"))
    monkeypatch.setattr(catalog_router.rec, "user_tuning", lambda db, uid: Tuning())
    ranked, *_ = catalog_router.personal_order(None, 1, list(range(n)), "recommended")
    return ranked


def test_long_list_top_is_led_by_taste_not_obscurity(monkeypatch):
    n = 27000
    novelty = np.zeros(n)
    novelty[n - 1500:n - 400] = 1.0          # 1,100 little-known films just below the 400 best matches
    top = run(monkeypatch, n, novelty)[:40]
    assert all(i >= n - 400 for i in top)    # the 40 best matches, not little-known films from further down
    assert top[0] == n - 1


def test_short_list_keeps_the_full_novelty_reorder(monkeypatch):
    n = 400                                   # a filtered genre list: bonus keeps its old size
    novelty = np.zeros(n)
    novelty[n - 15] = 1.0                    # 14 places below the top; +0.05 is worth 20 places here
    assert run(monkeypatch, n, novelty)[0] == n - 15
