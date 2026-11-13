import numpy as np

from cinematch_engine.mixed_home import compose, lane_weight, percentile


def lanes(n_movie=30, n_anime=30, n_series=30):
    movie = [(i, 1.0 - i / 100) for i in range(n_movie)]
    anime = [(100 + i, 0.9 - i / 100) for i in range(n_anime)]
    series = [(200 + i, 0.8 - i / 100) for i in range(n_series)]
    return {"movie": movie, "anime": anime, "series": series}


LANG = {r: "en" for r in range(300)} | {r: "ja" for r in range(100, 130)}
GEN = {r: ["Drama"] for r in range(300)}


def test_weight_needs_liked_titles_and_drops_with_dislikes():
    assert lane_weight(0, 0) == 0.0 and lane_weight(0, 20) == 0.0
    assert lane_weight(12, 0) == 1.0
    assert lane_weight(3, 0) < lane_weight(12, 0)
    assert lane_weight(50, 40) < 0.6 < lane_weight(50, 5)        # 50 liked, 40 disliked: not a fan
    assert lane_weight(3, 0) > 0.2                                # 3 liked and nothing disliked: a little


def test_percentile_is_rank_inside_the_list_not_the_raw_score():
    assert percentile([0.9, 0.1, 0.5]) == [1.0, 1 - 2 / 3, 1 - 1 / 3]
    assert percentile([]) == []


def test_no_evidence_means_exactly_the_film_list():
    got = compose(lanes(), {}, 10, LANG, GEN)
    assert [r for r, _ in got] == list(range(10)) and {f for _, f in got} == {"movie"}


def test_a_strong_anime_fan_gets_some_anime_but_not_only_anime():
    got = compose(lanes(), {"anime": 1.0}, 10, LANG, GEN)
    formats = [f for _, f in got]
    assert 2 <= formats.count("anime") <= 6 and formats.count("movie") >= 4
    assert len({r for r, _ in got}) == 10                              # no title twice


def test_weak_evidence_gives_less_anime_than_strong_evidence():
    strong = [f for _, f in compose(lanes(), {"anime": 1.0}, 10, LANG, GEN)].count("anime")
    weak = [f for _, f in compose(lanes(), {"anime": 0.35}, 10, LANG, GEN)].count("anime")
    assert weak <= strong


def test_the_quality_floor_keeps_low_ranked_titles_out():
    only_low = {"movie": lanes()["movie"], "anime": [(100 + i, 0.9 - i / 100) for i in range(30)]}
    got = compose(only_low, {"anime": 1.0}, 30, LANG, GEN, floor=0.9)
    assert all(row <= 103 for row, f in got if f == "anime")          # only about the top 10% of the anime list is eligible


def test_an_empty_or_short_lane_never_breaks_it():
    assert compose({"movie": [], "anime": []}, {"anime": 1.0}, 5, LANG, GEN) == []
    got = compose({"movie": [(1, 0.5)], "anime": [(100, 0.4)]}, {"anime": 1.0}, 5, LANG, GEN)
    assert len(got) <= 2


def test_lane_order_is_kept_even_when_scores_disagree():
    # A lane put in fresh-first order for Home: the first title has a LOWER score than the next ones. Its place must win.
    anime = [(129, 0.2)] + [(100 + i, 0.9 - i / 100) for i in range(29)]
    got = compose({"movie": lanes()["movie"], "anime": anime}, {"anime": 1.0}, 10, LANG, GEN)
    first_anime = next(r for r, f in got if f == "anime")
    assert first_anime == 129


def test_anime_films_and_anime_series_share_one_format_limit():
    split = {"movie": lanes()["movie"], "anime": lanes()["anime"][:15], "anime_film": [(300 + i, 0.9) for i in range(15)]}
    lang = LANG | {300 + i: "ja" for i in range(15)}
    gen = GEN | {300 + i: ["Animation"] for i in range(15)}
    both = [f for _, f in compose(split, {"anime": 1.0, "anime_film": 1.0}, 10, lang, gen)]
    one = [f for _, f in compose(lanes(), {"anime": 1.0}, 10, LANG, GEN)]
    assert both.count("anime") + both.count("anime_film") <= one.count("anime") + 1
