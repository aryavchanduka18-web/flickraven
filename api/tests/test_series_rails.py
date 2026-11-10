"""Themed series rows: the rules, the ordering and the mix."""
from app.services import series_rails as sr


def s(i, **kw):
    base = {"id": i, "lang": "en", "countries": ["US"], "seasons": 1, "episodes": 10, "runtime": 45, "status": "Ended",
            "genres": ["Drama"], "popularity": 7.0, "has_art": True}
    return {**base, **kw}


def test_theme_rules():
    assert sr.in_theme("kdrama", s(1, lang="ko", countries=["KR"])) and not sr.in_theme("kdrama", s(1))
    assert sr.in_theme("east_asian", s(1, countries=["JP"])) and not sr.in_theme("east_asian", s(1, countries=["JP"], genres=["Animation"]))
    assert sr.in_theme("binge", s(1, seasons=5, episodes=60, popularity=8.2)) and not sr.in_theme("binge", s(1, seasons=1, episodes=60, popularity=8.2))
    assert sr.in_theme("quick_comedy", s(1, genres=["Comedy"], runtime=22, episodes=236, popularity=8.0))
    assert not sr.in_theme("quick_comedy", s(1, genres=["Comedy", "Animation"], runtime=22, episodes=60))     # cartoons are not sitcoms
    assert not sr.in_theme("quick_comedy", s(1, genres=["Comedy"], runtime=55, episodes=60))                  # too long
    assert sr.in_theme("rewatch", s(1, seasons=9, status="Ended", popularity=8.3)) and not sr.in_theme("rewatch", s(1, seasons=9, status="Returning Series", popularity=8.3))


def test_acclaimed_and_weekend_rules():
    assert sr.in_theme("acclaimed", s(1, popularity=8.7, votes=5000)) and not sr.in_theme("acclaimed", s(1, popularity=8.7, votes=300))
    assert not sr.in_theme("acclaimed", s(1, popularity=8.7, votes=5000, genres=["Animation", "Drama"]))
    assert sr.in_theme("weekend", s(1, seasons=1, episodes=8, popularity=8.0)) and not sr.in_theme("weekend", s(1, seasons=6, episodes=100, popularity=8.0))
    assert not sr.in_theme("weekend", s(1, seasons=1, episodes=8, status="Returning Series", popularity=8.0))
    assert not sr.in_theme("weekend", s(1, seasons=3, episodes=36, runtime=45, popularity=8.0))     # 27 hours is not a weekend
    assert not sr.in_theme("weekend", s(1, seasons=1, episodes=8, runtime=None, popularity=8.0))    # unknown length


def test_drama_rows_hold_dramas_only():
    assert not sr.in_theme("kdrama", s(1, lang="ko", countries=["KR"], genres=["Comedy"]))         # e.g. a variety show
    assert not sr.in_theme("east_asian", s(1, countries=["JP"], genres=[]))


def test_rows_follow_the_users_ranking_and_need_enough_titles():
    series = [s(i, lang="ko", countries=["KR"]) for i in range(1, 13)] + [s(99)]
    rows = sr.build(series, [5, 3, 99, 1, 2, 4, 6, 7, 8, 9, 10, 11, 12])
    kd = next(r for r in rows if r["key"] == "kdrama")
    assert kd["ids"][:4] == [5, 3, 1, 2] and 99 not in kd["ids"]          # the user's order, only Korean series
    assert [r["key"] for r in rows] == ["east_asian", "kdrama"]            # themes with fewer than 8 titles are left out
    assert sr.build(series, [1, 2, 3]) == []                               # series the user already saw are not offered


def test_series_without_artwork_are_skipped():
    series = [s(i, lang="ko", countries=["KR"], has_art=(i != 1)) for i in range(1, 11)]
    assert 1 not in sr.build(series, list(range(1, 11)))[0]["ids"]


def test_mix_alternates_films_and_series_without_repeats():
    assert sr.interleave([1, 2, 3], [10, 11, 12]) == [1, 10, 2, 11, 3, 12]
    assert sr.interleave([1, 2], [2, 3]) == [1, 2, 3]
    assert len(sr.interleave(list(range(30)), list(range(100, 130)), n=20)) == 20
