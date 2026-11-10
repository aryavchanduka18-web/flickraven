"""Series Commitment Matcher: what fits a time budget, and the finish estimate."""
from app.services import series_fit as fit


def s(episodes, runtime, status="Ended"):
    return {"episodes": episodes, "runtime": runtime, "status": status}


def test_hours_and_budget():
    assert fit.hours(7, 60) == 7.0 and fit.hours(None, 60) is None
    assert fit.fits(s(5, 60), "5") and not fit.fits(s(10, 60), "5")
    assert fit.fits(s(100, 22), "long") and not fit.fits(s(5, 60), "long")
    assert not fit.fits(s(0, 60))                                          # unknown length is never guessed


def test_status_and_episode_length():
    assert fit.fits(s(8, 45, "Returning Series"), status="airing") and not fit.fits(s(8, 45), status="airing")
    assert fit.fits(s(20, 22), episode_length="short") and not fit.fits(s(20, 55), episode_length="short")


def test_plan_text():
    p = fit.plan(7, 60, 2)
    assert (p["hours"], p["days"]) == (7.0, 4) and "4 days" in p["text"]
    assert "one weekend" in fit.plan(4, 50, 2)["text"] and "one day" in fit.plan(2, 50, 2)["text"]
    assert "weeks" in fit.plan(236, 22, 2)["text"]


def full(episodes=8, runtime=45, status="Ended", genres=("Crime",), lang="en"):
    return {"episodes": episodes, "runtime": runtime, "status": status, "genres": list(genres), "lang": lang}


def test_series_type_genre_and_language_filters():
    assert fit.fits(full(8), series_type="mini") and not fit.fits(full(11), series_type="mini")
    assert fit.fits(full(25), series_type="short") and fit.fits(full(120), series_type="long")
    assert fit.fits(full(), genre="Crime") and not fit.fits(full(), genre="Comedy")
    assert fit.fits(full(lang="ko"), language="ko") and not fit.fits(full(), language="ko")


def test_ordering_and_ties_follow_the_users_ranking():
    items = [{"id": 1, "hours": 10.0, "status": "Returning Series", "rating": 8.0, "rank": 0},
             {"id": 2, "hours": 5.0, "status": "Ended", "rating": None, "rank": 1},
             {"id": 3, "hours": 5.0, "status": "Ended", "rating": 9.0, "rank": 2}]
    ids = lambda sort: [i["id"] for i in fit.order(items, sort)]
    assert ids("best") == [1, 2, 3]
    assert ids("shortest") == [2, 3, 1] and ids("longest")[0] == 1
    assert ids("rated") == [3, 1, 2]                       # no IMDb score goes last
    assert ids("completed") == [2, 3, 1]


def test_flexible_pace_has_no_schedule():
    p = fit.plan(8, 45, 0)
    assert p["days"] is None and p["finish"] is None and p["hours"] == 6.0
    assert fit.plan(8, 45, 2)["finish"] == "4 days at 2 a day"
