"""Perfect Pick: how three answers become three picks."""
import pytest

from app.services import perfect_pick as pp
from app.services.perfect_pick import Cand


def pool():
    # id, percentile, novelty: 1 is the safest best, 6 the most novel
    return [Cand(1, 1.0, 0.1), Cand(2, 0.9, 0.2), Cand(3, 0.8, 0.3), Cand(4, 0.7, 0.9), Cand(5, 0.6, 0.5), Cand(6, 0.2, 1.0)]


def test_familiar_is_the_top_three_by_score():
    assert [c.id for c in pp.choose(pool(), "familiar")] == [1, 2, 3]


def test_adventurous_leans_on_novelty_but_never_goes_below_the_floor():
    ids = [c.id for c in pp.choose(pool(), "adventurous")]
    assert 4 in ids and 6 not in ids                 # 6 is the most novel but scores 0.2, under the 0.35 floor
    assert all(c.role == "step_out" for c in pp.choose(pool(), "adventurous"))


def test_balanced_has_two_close_picks_and_one_surprise():
    got = pp.choose(pool(), "balanced")
    assert [c.id for c in got] == [1, 2, 4]          # best two, then the most novel title that still scores
    assert [c.role for c in got] == ["close", "close", "surprise"]


def test_small_pools_return_what_exists_and_bad_answers_fail():
    assert [c.id for c in pp.choose([Cand(7, 1.0, 0.5)], "balanced")] == [7]
    assert pp.choose([], "familiar") == []
    with pytest.raises(ValueError):
        pp.choose(pool(), "wild")


def test_percentiles_and_reasons():
    assert pp.pct_of([0.1, 0.9, 0.5]) == [1 / 3, 1.0, 2 / 3]
    exact = pp.reasons("surprise", "Feel-good", True, "1h 40m, 90-120 minutes", 81)
    assert exact[0]["text"] == 'Fits "feel-good"' and "surprise" in exact[2]["text"]
    near = pp.reasons("close", "Scary", False, "x", None)
    assert near[0]["text"].startswith("Not a perfect fit") and near[2]["text"].startswith("High in your own ranking")
    assert "81% match" in pp.reasons("close", "Funny", True, "x", 81)[2]["text"]


# ---- the six-question version ------------------------------------------------------------------------------

def mood_match(film, rule):
    return bool(set(film["genres"]) & set(rule.get("genres", [])))


def item(i, kind="movie", genres=("Drama",), lang="en", minutes=100.0, seasons=None, status=None, rec=0.5, novelty=0.3):
    return pp.Item(i, kind, list(genres), [], lang, minutes, seasons, status, rec, novelty)


def test_shows_never_return_films_and_films_never_return_shows():
    items = [item(1), item(2), item(3), item(11, "series", minutes=300.0, seasons=1), item(12, "series", minutes=300.0, seasons=1),
             item(13, "series", minutes=300.0, seasons=2)]
    got = pp.select(items, pp.Prefs(kind="series"), None, mood_match).exact
    assert {i.id for i in got} == {11, 12, 13}
    got = pp.select(items, pp.Prefs(kind="movie"), None, mood_match).exact
    assert {i.id for i in got} == {1, 2, 3}
    got = pp.select(items, pp.Prefs(kind="either"), None, mood_match).exact
    assert len(got) == 6


def test_time_limits_use_real_minutes_and_one_season_means_one_season():
    films = [item(1, minutes=80), item(2, minutes=100), item(3, minutes=150), item(4, minutes=None)]
    assert [i.id for i in pp.select(films, pp.Prefs(kind="movie", time="lt90"), None, mood_match).exact] == [1]
    assert [i.id for i in pp.select(films, pp.Prefs(kind="movie", time="90_120"), None, mood_match).exact] == [2]
    assert [i.id for i in pp.select(films, pp.Prefs(kind="movie", time="120_180"), None, mood_match).exact] == [3]
    assert {i.id for i in pp.select(films, pp.Prefs(kind="movie", time="any"), None, mood_match).exact} == {1, 2, 3, 4}
    shows = [item(11, "series", minutes=500, seasons=1), item(12, "series", minutes=500, seasons=3), item(13, "series", minutes=2000, seasons=1), item(14, "series", minutes=None, seasons=1)]
    assert {i.id for i in pp.select(shows, pp.Prefs(kind="series", time="season"), None, mood_match).exact} == {11, 13, 14}
    assert [i.id for i in pp.select(shows, pp.Prefs(kind="series", time="h10"), None, mood_match).exact] == [11, 12]   # unknown length is never "under 10 hours"
    mixed = shows + films
    assert {i.id for i in pp.select(mixed, pp.Prefs(kind="either", time="e120"), None, mood_match).exact} == {1, 2}


def test_completed_or_airing():
    shows = [item(11, "series", minutes=300, status="Ended"), item(12, "series", minutes=300, status="Returning Series"), item(13, "series", minutes=300, status="Canceled")]
    assert {i.id for i in pp.select(shows, pp.Prefs(kind="series", status="completed"), None, mood_match).exact} == {11, 13}
    assert [i.id for i in pp.select(shows, pp.Prefs(kind="series", status="airing"), None, mood_match).exact] == [12]


def test_languages_are_never_relaxed_and_misses_are_kept_apart():
    rule = {"genres": ["Comedy"]}
    hi = [item(i, genres=("Comedy",), lang="hi") for i in (1, 2, 3)]
    en_drama = [item(i, genres=("Drama",), lang="en") for i in (4, 5, 6, 7)]
    items = hi + en_drama
    sel = pp.select(items, pp.Prefs(mood="Funny", languages=["hi"]), rule, mood_match)
    assert {i.id for i in sel.exact} == {1, 2, 3} and sel.near == []
    # Funny + Drama in Hindi: no title has both, so nothing is exact; the Hindi comedies miss only the genre
    sel = pp.select(items, pp.Prefs(mood="Funny", genres=["Drama"], languages=["hi"]), rule, mood_match)
    assert sel.exact == [] and {(i.id, tuple(m)) for i, m in sel.near} == {(1, ("genres",)), (2, ("genres",)), (3, ("genres",))}
    # nothing in Japanese: no silent switch to other languages, only a count for the offer
    sel = pp.select(items, pp.Prefs(mood="Funny", languages=["ja"]), rule, mood_match)
    assert sel.exact == [] and sel.near == [] and sel.other_languages == 7
    other = [item(8, lang="de")]
    assert [i.id for i in pp.select(other, pp.Prefs(languages=["other"]), None, mood_match).exact] == [8]
    assert pp.select(other, pp.Prefs(languages=["en", "hi"]), None, mood_match).exact == []


def test_exact_matches_elsewhere_are_counted_not_shown():
    rule = {"genres": ["Comedy"]}
    items = [item(1, genres=("Comedy",), lang="hi"), item(2, genres=("Drama",), lang="hi"), item(3, genres=("Comedy",), lang="en"),
             item(4, genres=("Comedy",), lang="en")]
    sel = pp.select(items, pp.Prefs(mood="Funny", languages=["hi"]), rule, mood_match)
    assert [i.id for i in sel.exact] == [1] and sel.exact_elsewhere == 2
    assert "2 titles in other languages" in pp.message(1, 1, pp.Prefs(mood="Funny", languages=["hi"]), 0, 2)


def test_alternatives_missing_one_answer_come_before_those_missing_both():
    near = [(item(1, rec=0.9), ["mood", "genres"]), (item(2, rec=0.1), ["mood"]), (item(3, rec=0.2), ["genres"])]
    got = pp.pick_alternatives(near, pp.Prefs(mood="Funny", genres=["Comedy"], adventure="familiar"), {"genres": ["Comedy"]}, mood_match, 2)
    assert {c.id for c, _ in got} == {2, 3}                 # the higher-scoring title misses both answers, so it waits
    got = pp.pick_alternatives(near, pp.Prefs(mood="Funny", genres=["Comedy"], adventure="familiar"), {"genres": ["Comedy"]}, mood_match, 3)
    assert [c.id for c, _ in got][-1] == 1 and dict((c.id, m) for c, m in got)[1] == ["mood", "genres"]
    assert pp.pick_alternatives(near, pp.Prefs(), None, mood_match, 0) == []


def test_messages_say_what_was_kept_and_what_was_missed():
    pf = pp.Prefs(kind="series", mood="Romantic", genres=["Romance"], languages=["en", "ko"])
    assert pp.message(3, 0, pf, 0) is None
    assert pp.message(2, 1, pf, 0).startswith("Only 2 titles meet every answer")
    assert "type, length and languages" in pp.message(0, 3, pf, 0)
    assert "Include other languages" in pp.message(0, 0, pf, 12) and "12 titles" in pp.message(0, 0, pf, 12)


def test_series_get_romance_horror_thriller_from_keywords():
    g, added = pp.series_genres(["Drama", "Comedy"], ["first love", "high school"])
    assert "Romance" in g and added == {"Romance"}
    assert pp.series_genres(["Drama"], ["bromance", "slight romance", "ghost", "supernatural"])[1] == frozenset()
    assert pp.series_genres(["Crime"], ["Serial Killer"])[1] == {"Thriller"}
    # a romantic K-drama now fits the Romantic mood and the Romance genre, and the card says where Romance came from
    g, added = pp.series_genres(["Drama", "Comedy"], ["romance"])
    show = pp.Item(9, "series", g, ["romance"], "ko", 960.0, 1, "Ended", 0.5, 0.3, 16, added)
    pf = pp.Prefs(kind="series", mood="Romantic", genres=["Romance"], languages=["ko"], time="h20")
    sel = pp.select([show], pf, {"genres": ["Romance"]}, mood_match)
    assert [i.id for i in sel.exact] == [9]
    rs = pp.reasons_v2(show, "close", pf, [], mood_match, {"genres": ["Romance"]}, None)
    assert any("Romance from TMDB keywords" in r["text"] for r in rs) and any(r["text"] == 'Fits "romantic"' for r in rs)


def test_rank_prefers_picked_genres_and_relevance_and_reasons_are_true():
    a = item(1, genres=("Thriller", "Mystery"), rec=0.4)
    b = item(2, genres=("Comedy",), rec=0.5)
    c = item(3, genres=("Thriller",), rec=0.3)
    cands = pp.rank([a, b, c], pp.Prefs(genres=["Thriller", "Mystery"]), None, mood_match)
    best = max(cands, key=lambda x: x.pct)
    assert best.id == 1
    rs = pp.reasons_v2(a, "close", pp.Prefs(genres=["Thriller", "Mystery"], time="any"), [], mood_match, None, 80)
    assert any("Thriller, Mystery" in r["text"] for r in rs)
    rs = pp.reasons_v2(b, "close", pp.Prefs(genres=["Thriller"]), ["genres"], mood_match, None, 80)
    assert any("outside the genres you picked" in r["text"] for r in rs)


def test_three_picks_are_not_three_clones():
    pool = [Cand(1, 1.0, 0.1), Cand(2, 0.98, 0.1), Cand(3, 0.97, 0.1), Cand(4, 0.9, 0.2)]
    genres = {1: {"Action", "Thriller"}, 2: {"Action", "Thriller"}, 3: {"Action", "Thriller"}, 4: {"Comedy"}}
    ids = [c.id for c in pp.choose(pool, "familiar", genres=genres)]
    assert 4 in ids and ids[0] == 1


def test_anime_is_a_hard_limit_and_other_genres_stay_soft():
    items = [pp.Item(1, "series", ["Animation", "Action"], [], "ja", 300.0, 1, None, 0.9, 0.3, anime=True),
             pp.Item(2, "series", ["Animation", "Drama"], [], "ja", 300.0, 1, None, 0.8, 0.3, anime=True),
             pp.Item(3, "series", ["Action"], [], "en", 300.0, 1, None, 0.95, 0.3),
             pp.Item(4, "movie", ["Animation", "Fantasy"], [], "ja", 120.0, None, None, 0.7, 0.3, anime=pp.is_anime_film(["Animation"], "ja"))]
    sel = pp.select(items, pp.Prefs(kind="series", genres=["Anime", "Action"]), None, mood_match)
    # live-action Action is never offered, not even as a broader alternative; anime without Action misses "genres"
    assert [i.id for i in sel.exact] == [1] and [(i.id, m) for i, m in sel.near] == [(2, ["genres"])]
    either = pp.select(items, pp.Prefs(kind="either", genres=["Anime"]), None, mood_match)
    assert {i.id for i in either.exact} == {1, 2, 4} and not either.near
    assert any(r["text"] == "Anime, which you picked" for r in pp.reasons_v2(items[0], "close", pp.Prefs(genres=["Anime"]), [], mood_match, None, None))
    assert not pp.is_anime_film(["Animation"], "en")


def test_show_more_messages_are_honest():
    pf = pp.Prefs(kind="series", genres=["Anime"])
    assert pp.message(3, 0, pf, 0, more=True) is None
    assert pp.message(1, 0, pf, 0, more=True) == "That is the last of the titles that meet every answer."
    assert pp.message(1, 2, pf, 0, more=True).startswith("Only 1 more title meets every answer")
    assert "type, length and anime" in pp.message(0, 3, pf, 0, more=True)
    assert pp.message(0, 0, pf, 0, more=True).startswith("That is everything")
