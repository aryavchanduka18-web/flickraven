from app.services import taste_evolution as ev


def e(month, *genres):
    return (month, list(genres))


def test_months_are_counted_oldest_first_and_capped():
    events = [e(f"2026-0{m}", "Drama") for m in range(1, 8)] + [e("2026-07", "Drama", "Crime")]
    out = ev.by_month(events)
    assert [m["month"] for m in out] == [f"2026-0{m}" for m in range(2, 8)]
    assert out[-1]["titles"] == 2 and out[-1]["top"][0] == {"genre": "Drama", "titles": 2, "share": 1.0}


def test_a_shift_needs_five_titles_on_each_side():
    few = [e("2026-01", "Drama")] * 4 + [e("2026-03", "Comedy")] * 6
    assert ev.shift(few) is None
    assert ev.shift([e("2026-03", "Comedy")] * 8) is None                       # one month only


def test_rising_and_falling_genres_are_named_with_shares():
    events = [e("2026-01", "Drama")] * 6 + [e("2026-02", "Comedy")] * 6
    s = ev.shift(events + [e("2026-03", "Comedy")] * 2)
    assert s["rising"]["genre"] == "Comedy" and s["falling"]["genre"] == "Drama"
    assert s["falling"]["from"] == 1.0 and s["falling"]["to"] == 0.0
