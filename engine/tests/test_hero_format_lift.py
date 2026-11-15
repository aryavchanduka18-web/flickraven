"""Strong anime fans get anime in the hero in proportion to their taste; nobody else changes."""
from cinematch_engine.mixed_home import hero_target, lift_in_hero


def test_target_follows_taste_share_and_needs_a_strong_fan():
    assert hero_target(50, 10, 1.0) == 3            # capped
    assert hero_target(12, 12, 1.0) == 3            # half of 5, rounded up
    assert hero_target(6, 30, 0.5) == 1
    assert hero_target(4, 0, 0.33) == 0             # casual fan: unchanged
    assert hero_target(0, 40, 0.0) == 0             # film-only: unchanged


def test_lift_replaces_lowest_films_only_above_the_floor_and_loses_nothing():
    picked = [(1, "movie"), (2, "movie"), (100, "anime"), (3, "movie"), (4, "movie"), (5, "movie"), (101, "anime")]
    lanes = {"anime": [(r, 1.0) for r in range(100, 110)]}
    out = lift_in_hero(picked, lanes, ("anime",), 3)
    head = out[:5]
    assert sum(1 for _, f in head if f == "anime") == 3
    assert head[:3] == picked[:3]                               # best films stay, lowest film places taken
    assert sorted(out) == sorted(set(out)) and {r for r, _ in picked} <= {r for r, _ in out}
    weak = {"anime": [(r, 1.0) for r in range(200, 210)]}      # only rows 200..203 clear the 0.6 floor
    got = lift_in_hero([(1, "movie")] * 0 + [(i, "movie") for i in range(5)], weak, ("anime",), 3)
    assert {r for r, _ in got[:5]} & {204, 205, 206, 207, 208, 209} == set()


def test_series_slides_are_never_displaced_and_no_target_changes_nothing():
    picked = [(1, "movie"), (50, "korean_series"), (2, "movie"), (51, "korean_series"), (3, "movie")]
    lanes = {"anime": [(r, 1.0) for r in range(100, 110)]}
    out = lift_in_hero(picked, lanes, ("anime",), 3)
    assert (50, "korean_series") in out[:5] and (51, "korean_series") in out[:5]
    assert lift_in_hero(picked, lanes, ("anime",), 0) == picked
