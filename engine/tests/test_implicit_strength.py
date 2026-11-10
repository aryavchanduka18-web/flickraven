from cinematch_engine.online import OnlineEngine, UserState


def _engine():
    e = OnlineEngine.__new__(OnlineEngine)
    e.event_weights = {"detail_view": 0.5, "list_add": 2.0, "rate": 1.0}
    return e


def test_repeated_views_do_not_add_up():
    once, many = UserState(), UserState()
    once.events = [("detail_view", 3)]
    many.events = [("detail_view", 3)] * 10
    assert _engine().implicit_strength(many) == _engine().implicit_strength(once) == {3: 0.5}


def test_different_kinds_still_add_up():
    st = UserState()
    st.events = [("detail_view", 3), ("detail_view", 3), ("list_add", 3)]
    assert _engine().implicit_strength(st) == {3: 2.5}
