"""Unit tests for the per-person preference model (api/app/services/preference.py). Pure maths, no database."""
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.services import preference as pf
from app.services.preference import Label, State, Title

T0 = datetime(2026, 1, 1)


def mk(i, genres, lang="en", year=2010, runtime=110):
    return Title(i, genres, lang, year, runtime)


def catalogue():
    """A catalogue of 600 titles with a spread of genres, plus the three kinds of crime film we test with."""
    gs = ["Drama", "Comedy", "Action", "Crime", "Romance", "Thriller"]
    out = []
    for i in range(600):
        g = [gs[i % 6]] + ([gs[(i * 7 + 1) % 6]] if i % 3 == 0 else [])
        out.append(mk(i, sorted(set(g)), lang=["en", "hi", "ko"][i % 3], year=1980 + (i * 3) % 45, runtime=70 + (i * 11) % 90))
    return out


@pytest.fixture(scope="module")
def world():
    titles = catalogue()
    return titles, pf.fit_space(titles)


def serious_crime(i):
    return mk(10_000 + i, ["Crime", "Thriller"])


def crime_comedy(i):
    return mk(20_000 + i, ["Crime", "Comedy"])


# ---- labels --------------------------------------------------------------------------------------
def test_one_label_per_film_even_with_many_actions():
    s = State(1, rating=9, rating_at=T0, reaction="like", reaction_at=T0 + timedelta(1), in_list=True, list_at=T0, watched=True)
    labels = pf.effective_labels([s])
    assert list(labels) == [1] and labels[1].alpha == 1.0 and labels[1].y == 1


def test_watched_alone_is_never_taste_and_list_alone_is_weak_interest():
    labels = pf.effective_labels([State(1, watched=True), State(2, in_list=True, list_at=T0)])
    assert 1 not in labels
    assert (labels[2].y, labels[2].alpha, labels[2].kind) == (1, 0.5, "interest")


def test_latest_explicit_opinion_wins_and_a_middling_rating_cancels_an_old_like():
    like_then_dislike = State(1, reaction="like", reaction_at=T0, rating=3, rating_at=T0 + timedelta(1))
    assert pf.effective_labels([like_then_dislike])[1].y == -1
    like_then_five = State(2, reaction="like", reaction_at=T0, rating=5, rating_at=T0 + timedelta(1), in_list=True, list_at=T0)
    assert 2 not in pf.effective_labels([like_then_five])        # an opinion that says nothing; list add is not interest then


@pytest.mark.parametrize("rating,expect", [(10, (1, 1.0)), (8, (1, 1.0)), (7, (1, 0.4)), (6, None), (5, None), (4, (-1, 1.0)), (1, (-1, 1.0))])
def test_rating_bands(rating, expect):
    got = pf.effective_labels([State(1, rating=rating, rating_at=T0)]).get(1)
    assert (None if got is None else (got.y, got.alpha)) == expect


def test_reset_and_pause_really_forget():
    states = [State(1, rating=9, rating_at=T0), State(2, rating=2, rating_at=T0 + timedelta(5))]
    assert set(pf.effective_labels(states, reset_at=T0 + timedelta(1))) == {2}       # only after the reset
    assert pf.effective_labels(states, reset_at=T0 + timedelta(30)) == {}
    assert pf.effective_labels(states, learning=False) == {}


def test_perfect_pick_reasons_reach_the_weights_only_when_they_are_about_taste():
    rej = lambda mid, reasons, kind="perfect_pick_reject": {"movie_id": mid, "kind": kind, "reasons": reasons, "created_at": T0}
    out = pf.pick_labels([rej(1, ["mood"]), rej(2, ["language"]), rej(3, ["time"]), rej(4, ["seen"]), rej(5, []),
                          rej(6, ["mood"], "perfect_pick_reroll"), rej(7, ["genre"]), rej(8, ["taste"]),
                          rej(9, ["mood", "genre"])], have={})
    assert set(out) == {7, 8, 9}
    assert out[7].genre_only and out[7].alpha == 0.5 and out[8].alpha == 0.3 and not out[8].genre_only
    assert pf.pick_labels([rej(7, ["genre"])], have={7: Label(7, 1, 1.0, "like")}) == {}      # a real opinion wins
    assert pf.pick_labels([rej(7, ["genre"])], have={}, learning=False) == {}


# ---- the maths -----------------------------------------------------------------------------------
def learn(world, liked, rejected, extra=None):
    titles, space = world
    by_id = {t.id: t for t in [*liked, *rejected, *(extra or [])]}
    labels = {t.id: Label(t.id, 1, 1.0, "like") for t in liked}
    labels.update({t.id: Label(t.id, -1, 1.0, "dislike") for t in rejected})
    return pf.fit(labels, by_id, space)


def test_learns_serious_crime_yes_crime_comedy_no(world):
    """The motivating case: likes serious crime thrillers, rejects crime comedies. Held-out films of each kind must be
    ranked the right way round (Thriller up, Comedy down), which a single 'likes Crime' weight could not do."""
    _, space = world
    prof = learn(world, [serious_crime(i) for i in range(6)], [crime_comedy(i) for i in range(6)])
    held_dark, held_comedy = serious_crime(50), crime_comedy(50)
    assert pf.score(prof, held_dark) > 0 > pf.score(prof, held_comedy)
    assert pf.score(prof, held_dark) - pf.score(prof, held_comedy) > 0.5
    names = {f["feature"]: f for f in pf.top_features(prof, 40)}
    assert any(k in names for k in ("g:Thriller", "g:Comedy"))      # told apart by their genres alone


def test_no_effect_below_three_distinct_films(world):
    prof = learn(world, [serious_crime(0), serious_crime(1)], [])
    assert pf.score(prof, serious_crime(50)) == 0.0
    assert (pf.effect(prof) == 0).all()


def test_repeated_actions_on_one_film_do_not_build_confidence(world):
    """Evidence counts distinct films. Three actions on one film are one label, so still no effect."""
    labels = pf.effective_labels([State(10_000, rating=10, rating_at=T0, reaction="like", reaction_at=T0, in_list=True, list_at=T0)])
    prof = pf.fit(labels, {10_000: serious_crime(0)}, world[1])
    assert prof.films == 1 and (pf.effect(prof) == 0).all()


def test_adjustment_is_bounded_and_grows_with_evidence(world):
    cap = pf.cap_for(list(np.linspace(0.0, 1.0, 50)))
    assert cap == pytest.approx(0.25 * 0.8, abs=0.01)
    assert pf.cap_for([1, 2]) == 0.0
    for s in (-50, -1, 0, 1, 50):
        assert abs(pf.adjustment(s, 100, cap)) <= cap + 1e-12
    assert abs(pf.adjustment(2.0, 5, cap)) < abs(pf.adjustment(2.0, 20, cap)) == pytest.approx(cap * np.tanh(2.0))


def test_same_events_same_profile(world):
    a = learn(world, [serious_crime(i) for i in range(5)], [crime_comedy(i) for i in range(5)])
    b = learn(world, [serious_crime(i) for i in range(5)], [crime_comedy(i) for i in range(5)])
    assert np.array_equal(a.theta, b.theta)


def test_that_is_not_me_zeroes_a_feature(world):
    prof = learn(world, [serious_crime(i) for i in range(6)], [crime_comedy(i) for i in range(6)])
    before = pf.score(prof, serious_crime(50))
    prof2 = pf.fit({}, {}, world[1])
    assert pf.score(prof2, serious_crime(50)) == 0.0               # nothing learned = no effect
    zeroed = pf.Profile(prof.space, prof.theta, prof.n, prof.films, {n for n in prof.space.names if n.startswith("g:")})
    assert abs(pf.score(zeroed, serious_crime(50))) < abs(before)


def test_genre_only_label_touches_genre_features_only(world):
    titles, space = world
    t = crime_comedy(1)
    labels = {1: Label(1, -1, 0.5, "wrong_genre", genre_only=True)}
    labels.update({i + 100: Label(i + 100, -1, 0.5, "wrong_genre", genre_only=True) for i in range(4)})
    by_id = {1: t, **{i + 100: crime_comedy(i + 100) for i in range(4)}}
    prof = pf.fit(labels, by_id, space)
    for i, name in enumerate(space.names):
        if not name.startswith("g:"):
            assert prof.theta[i] == 0.0 and prof.n[i] == 0
    assert any(prof.theta[i] != 0 for i, n in enumerate(space.names) if n.startswith("g:"))


def test_rare_feature_cannot_dominate(world):
    titles, space = world
    assert (space.scale >= pf.MIN_SCALE).all()
    rare = Title(99_999, ["Drama"], "xx", 1900, 70)
    labels = {99_999: Label(99_999, 1, 1.0, "like")}
    prof = pf.fit(labels, {99_999: rare}, space)
    assert abs(pf.score(prof, rare)) < 1e-9                         # one film = no effect, whatever its tags
