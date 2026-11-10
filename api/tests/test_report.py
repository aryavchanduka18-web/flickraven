"""Recommendation report: nothing reliable below 10 rated recommendations; then outcomes, genres and reasons."""
from collections import Counter

from app.services.report import summarize


def row(rating, match=80, genres=("Drama",)):
    return {"rating": rating, "match_pct": match, "genres": list(genres)}


def test_too_few_ratings_shows_only_the_count():
    out = summarize([row(9)] * 4, Counter())
    assert out == {"rated": 4, "needed": 10, "ready": False}


def test_report_numbers():
    rows = [row(9, 90, ["Mystery"])] * 6 + [row(4, 70, ["Action"])] * 4
    out = summarize(rows, Counter({"predictable": 3, "slow": 1}))
    assert out["ready"] and out["positive_pct"] == 60 and out["avg_rating"] == 7.0 and out["avg_predicted_match"] == 82
    assert out["best_genres"] == ["Mystery"] and out["missed_genres"] == ["Action"]
    assert out["top_reasons"][0] == "too predictable"
