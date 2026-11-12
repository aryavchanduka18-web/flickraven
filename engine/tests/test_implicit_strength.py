from cinematch_engine.online import OnlineEngine, UserState


def _engine():
    e = OnlineEngine.__new__(OnlineEngine)
    e.event_weights = {"detail_view": 0.5, "quick_view": 0.25, "search_click": 0.5, "hero_view": 0.5, "list_add": 2.0, "rate": 1.0}
    return e


def test_weak_events_are_not_taste():
    st = UserState()
    st.events = [("detail_view", 3)] * 10 + [("quick_view", 3), ("search_click", 3), ("hero_view", 3)]
    assert _engine().implicit_strength(st) == {}


def test_strong_and_confirmed_events_count_once_per_title():
    once, many = UserState(), UserState()
    once.events = [("list_add", 3)]
    many.events = [("list_add", 3)] * 5
    assert _engine().implicit_strength(many) == _engine().implicit_strength(once) == {3: 2.0}


def test_views_add_nothing_on_top_of_a_strong_action():
    st = UserState()
    st.events = [("detail_view", 3), ("detail_view", 3), ("list_add", 3)]
    assert _engine().implicit_strength(st) == {3: 2.0}


def test_only_ratings_of_7_or_more_are_interest():
    """Live ALS counts a rating as interest only from 7, as offline training does (sources.Profiles.implicit); a lower
    rating also cancels a save or watched mark on that title."""
    st = UserState()
    st.ratings = {1: 3.0, 2: 6.0, 3: 7.0, 4: 9.0, 5: 4.0}
    st.events = [("list_add", 5)]
    assert _engine().implicit_strength(st) == {3: 2.0, 4: 4.0}


def test_quantile_cap_keeps_order_and_stops_below_the_best_movielens_film():
    from types import SimpleNamespace
    import numpy as np
    import cinematch_engine.online as online
    from cinematch_engine.online import OnlineEngine
    from tests.test_kind_rank import cat
    c = cat(["movie"] * 6, [5] * 6)
    c.universe_of_row = np.array([0, 1, 2, -1, -1, -1])
    c.universe_rows = np.array([0, 1, 2])
    e = SimpleNamespace(cat=c)
    e.unavailable_rows = lambda: OnlineEngine.unavailable_rows(e)
    scores = {s: np.full(6, -np.inf, np.float32) for s in ("popularity", "content", "item_cf", "user_cf", "svd", "als")}
    scores["content"] = np.array([0.1, 0.2, 0.3, 0.9, 0.5, 0.1], np.float32)
    st = UserState(); st.behavioral_count = 30
    total = np.array([0.2, 0.5, 0.9, 0, 0, 0], np.float32)
    w = {"content": 1.0}
    saved = dict(online.UNAVAILABLE_QUANTILE_CAP)
    try:
        online.UNAVAILABLE_QUANTILE_CAP["established"] = 1.0
        full = OnlineEngine._quantile_unavailable(e, st, scores, total, w)
        online.UNAVAILABLE_QUANTILE_CAP["established"] = 0.5
        capped = OnlineEngine._quantile_unavailable(e, st, scores, total, w)
    finally:
        online.UNAVAILABLE_QUANTILE_CAP.update(saved)
    assert full[3] > full[4] > full[5] and capped[3] > capped[4] > capped[5]   # content order kept
    assert capped[3] < full[3] and capped[3] <= 0.5 + 1e-6                     # the cap holds them below the top
    assert (full[:3] == total[:3]).all()                                         # MovieLens films unchanged


def test_tiers():
    from cinematch_engine.profile import tier_of
    assert [tier_of(e) for e in ("detail_view", "search_click", "list_add", "like", "rate", "rec_feedback")] == [
        "weak", "weak", "strong", "strong", "confirmed", None]
