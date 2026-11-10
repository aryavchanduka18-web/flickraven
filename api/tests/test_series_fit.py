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
