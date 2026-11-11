"""Home with a daily seed: a different page each day, the same page within a day, no repeats, new Feel-good and Romance rows."""
from types import SimpleNamespace

import numpy as np
import scipy.sparse as sp

from cinematch_engine.online import Catalog, OnlineEngine, UserState

N = 400
GENRES = [["Comedy", "Romance"], ["Drama"], ["Action"], ["Romance", "Drama"], ["Horror"], ["Family", "Comedy"], ["Thriller"], ["Science Fiction"]]


def make(seed_free=True):
    rng = np.random.default_rng(0)
    cat = Catalog(
        movie_ids=np.arange(1000, 1000 + N), titles=[f"t{i}" for i in range(N)], genres=[GENRES[i % len(GENRES)] for i in range(N)],
        keywords=[[]] * N, language=["en" if i % 4 else "hi" for i in range(N)], runtime=np.full(N, 105.0), year=np.full(N, 2010.0),
        part=np.array(["D"] * N), popularity=np.linspace(6.0, 9.0, N), votes=np.arange(N, dtype=float),
        has_award=np.array([i % 7 == 0 for i in range(N)]), content=sp.identity(N, format="csr", dtype=np.float32),
        universe_rows=np.array([0]), recent=np.array([i % 5 == 0 for i in range(N)]), kind=np.array(["movie"] * N, dtype=object))
    score = rng.random(N).astype(np.float32)
    e = SimpleNamespace(cat=cat)
    e.rail_scores = lambda st, scores=None: score
    e.scores = lambda st: {"content": score, "svd": score, "user_cf": score}
    e.excluded = lambda st: np.array([], dtype=int)
    e._recent_likes = lambda st: []
    e.phase = lambda st, recent, k=60, scores=None: None
    e._new_notable = lambda st, scores: np.argsort(-score)[:80].tolist()
    order = np.argsort(-score)

    def top_picks(st, mode, k=25, scores=None, extra_exclude=None, tuning=None):
        skip = set(extra_exclude or ())
        return [{"row": int(r), "score": float(score[r]), "match_pct": 80, "shares": {}} for r in order if int(r) not in skip][:k]
    e.top_picks = top_picks
    return e


def plan(seed):
    return OnlineEngine.home(make(), UserState(), "balanced", seed=seed)


def rows_of(p):
    return {r["key"]: r["rows"] for r in p["rails"]}


def test_same_seed_same_page_and_other_seed_other_page():
    a, b, c = plan(1), plan(1), plan(2)
    assert rows_of(a) == rows_of(b) and [h["row"] for h in a["hero"]] == [h["row"] for h in b["hero"]]
    assert rows_of(a) != rows_of(c) or [h["row"] for h in a["hero"]] != [h["row"] for h in c["hero"]]
    assert [r["key"] for r in plan(1)["rails"]] == [r["key"] for r in plan(1)["rails"]]


def test_no_seed_is_deterministic_and_seed_changes_order_of_themed_rows():
    base = OnlineEngine.home(make(), UserState(), "balanced")
    again = OnlineEngine.home(make(), UserState(), "balanced")
    assert rows_of(base) == rows_of(again)
    orders = {tuple(r["key"] for r in plan(s)["rails"]) for s in range(8)}
    assert len(orders) > 1


def test_no_title_twice_on_one_page_and_new_rows_exist():
    for seed in (3, 4, 5):
        p = plan(seed)
        every = [h["row"] for h in p["hero"]] + [r for rail in p["rails"] for r in rail["rows"]]
        assert len(every) == len(set(every))
        keys = {r["key"] for r in p["rails"]}
        assert {"feel_good", "romance"} <= keys
        light = {r for r in rows_of(p)["feel_good"]}
        assert all(not {"Horror", "Thriller"} & set(make().cat.genres[r]) for r in light)
        assert all("Romance" in make().cat.genres[r] for r in rows_of(p)["romance"])
