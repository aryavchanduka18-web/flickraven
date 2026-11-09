"""MyDramaList similarities: entry weights, matching, and that viewers who liked the same shows make them similar."""
import numpy as np
import pandas as pd

from pipeline.drama_cf import COMPLETED_WEIGHT, evaluate, match_shows, similarities, user_item_matrix, weights


def pairs(rows):
    return pd.DataFrame(rows, columns=["uid", "sid", "score", "completed"])


def test_entry_weights():
    p = pairs([(1, 1, 7.0, True), (1, 2, 10.0, True), (1, 3, 0.0, True), (1, 4, 6.5, True), (1, 5, np.nan, True), (1, 6, 0.0, False)])
    assert weights(p).round(2).tolist() == [0.6, 1.0, COMPLETED_WEIGHT, 0.0, COMPLETED_WEIGHT, 0.0]


def test_viewers_who_liked_the_same_shows_make_them_similar():
    rows = []
    for u in range(40):                         # group A likes shows 1-5, group B likes shows 6-10
        group = range(1, 6) if u < 20 else range(6, 11)
        rows += [(u, s, 9.0, True) for s in group]
    items = list(range(1, 13))                  # two extra shows nobody watched
    x, users = user_item_matrix(pairs(rows), items)
    s = similarities(x).toarray()
    assert s[0, 1] > 0 and s[0, 6] == 0         # show 1 is similar to show 2, never to show 7
    assert (np.diag(s) == 0).all()
    r = evaluate(pairs(rows), items)
    assert r["test_users"] > 0 and r["hit@10_learned"] >= r["hit@10_popularity"]   # tiny catalogue: every method finds it


def test_users_with_few_entries_are_dropped():
    x, users = user_item_matrix(pairs([(1, 1, 9.0, True), (1, 2, 9.0, True)]), [1, 2])
    assert x.shape[0] == 0


def test_match_by_title_alternative_title_and_year():
    shows = pd.DataFrame({"sid": [10, 11, 12], "title": ["Goblin", "Goblin", "Crash Landing on You"], "kind": ["Drama"] * 3,
                          "year": [2016, 1999, 2019], "ratings": [500, 900, 800]})
    series = pd.DataFrame({"tmdb_id": [1, 2, 3], "title": ["Guardian: The Lonely and Great God", "Unknown Show", "Crash Landing on You"],
                           "original_title": ["도깨비", "x", "사랑의 불시착"], "year": [2016, 2020, 2019]})
    got = match_shows(shows, series, {1: ["Goblin"]})                  # alternative title; the 1999 namesake is too far off
    assert got.to_dict("records") == [{"tmdb_id": 1, "sid": 10}, {"tmdb_id": 3, "sid": 12}]
