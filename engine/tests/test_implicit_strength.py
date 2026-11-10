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


def test_tiers():
    from cinematch_engine.profile import tier_of
    assert [tier_of(e) for e in ("detail_view", "search_click", "list_add", "like", "rate", "rec_feedback")] == [
        "weak", "weak", "strong", "strong", "confirmed", None]
