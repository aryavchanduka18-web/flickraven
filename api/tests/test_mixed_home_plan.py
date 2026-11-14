"""The Home mix: nobody without liked anime or series changes; a fan gets some anime in the hero and first Top Picks."""
from types import SimpleNamespace

import numpy as np

from app.services import mixed_home_plan as mh

N_MOVIE, N_ANIME = 40, 40
ANIME_FILMS = {36, 37, 38, 39}                       # Japanese animated films among the films


def engine(anime_fan: bool):
    kind = np.array(["movie"] * N_MOVIE + ["anime"] * N_ANIME, dtype=object)
    lang = ["ja" if r in ANIME_FILMS else "en" for r in range(N_MOVIE)] + ["ja"] * N_ANIME
    genres = [["Animation"] if r in ANIME_FILMS else ["Drama"] for r in range(N_MOVIE)] + [["Drama"]] * N_ANIME
    cat = SimpleNamespace(kind=kind, language=lang, genres=genres)
    e = SimpleNamespace(cat=cat)
    e.engaged_rows = lambda st: set(st.liked)
    e.excluded = lambda st: np.array(sorted(set(st.liked) | set(st.ratings)), dtype=np.int64)
    e.kind_rank = lambda st, fmt: (np.arange(N_MOVIE, N_MOVIE + N_ANIME), np.linspace(0.95, 0.2, N_ANIME)) if fmt == "anime" else (np.array([], dtype=int), np.array([]))
    return e


def state(liked_anime=0, bad_anime=0):
    liked = list(range(N_MOVIE, N_MOVIE + liked_anime)) + list(range(3))          # a few films too
    ratings = {r: 3 for r in range(N_MOVIE + 25, N_MOVIE + 25 + bad_anime)}
    return SimpleNamespace(liked=liked, ratings=ratings, dislikes=set())


def plan():
    entries = {r: {"row": r, "score": 1.0 - r / 100, "match_pct": 80, "shares": {}} for r in range(30)}
    rail = np.full(N_MOVIE + N_ANIME, -np.inf)
    rail[:N_MOVIE] = np.linspace(0.9, 0.1, N_MOVIE)
    return {"rail_scores": rail, "hero": [entries[r] for r in range(5)],
            "rails": [{"key": "top_picks", "rows": list(range(5, 30)), "scored": {r: entries[r] for r in range(5, 30)}},
                      {"key": "romance", "rows": [31, 32], "scored": {}}]}


def test_someone_without_anime_or_series_history_is_unchanged():
    p = plan()
    assert mh.mix(engine(False), state(0), p, set()) is p


def test_an_anime_fan_gets_anime_in_hero_and_top_picks_without_dropping_films_or_repeating():
    out = mh.mix(engine(True), state(20), plan(), set())
    hero_rows = [e["row"] for e in out["hero"]]
    assert len(hero_rows) == 5
    top = next(r for r in out["rails"] if r["key"] == "top_picks")
    first = hero_rows + top["rows"][:10]
    anime = [r for r in first if r >= N_MOVIE]
    assert 2 <= len(anime) <= 7
    assert all(e.get("format") == "anime" and e["match_pct"] is None for e in out["hero"] if e["row"] >= N_MOVIE)
    every = hero_rows + top["rows"]
    assert len(every) == len(set(every))
    assert set(top["rows"]) <= set(top["scored"])                         # every row has an entry to build a card from
    assert out["rails"][1]["rows"] == [31, 32]                            # other rows are untouched


def test_hidden_titles_and_disliked_anime_fans_are_respected():
    skip = set(range(N_MOVIE, N_MOVIE + 40))
    out = mh.mix(engine(True), state(20), plan(), skip)                  # every anime hidden: films only
    assert all(e["row"] < N_MOVIE for e in out["hero"])
    weak = mh.mix(engine(True), state(6, bad_anime=10), plan(), set())   # 6 liked, 10 disliked: not enough evidence
    assert [e["row"] for e in weak["hero"]] == list(range(5))


def test_reason_text_is_honest_and_has_no_match():
    r = mh.reason("anime")[0]
    assert r["code"] == "cross_format" and "rated highly" in r["text"]


def test_titles_shown_on_earlier_days_go_behind_fresh_ones_in_every_lane():
    fresh = mh.mix(engine(True), state(20), plan(), set())
    first = [e["row"] for e in fresh["hero"]]
    shown = set(first) | set(range(N_MOVIE, N_MOVIE + 10))              # yesterday's hero plus the top 10 anime
    later = mh.mix(engine(True), state(20), plan(), set(), stale=shown)
    hero = [e["row"] for e in later["hero"]]
    assert not set(hero) & shown                                          # a new hero, films and anime alike


def test_anime_films_join_the_anime_lane_for_an_anime_fan():
    out = mh.mix(engine(True), state(20), plan(), set())
    top = next(r for r in out["rails"] if r["key"] == "top_picks")
    entries = {e["row"]: e for e in out["hero"]} | top["scored"]
    films = [r for r in out_first(out) if r in ANIME_FILMS]
    assert films, "a Japanese animated film should reach the first 15 for an anime fan"
    assert all(entries[r].get("format") == "anime" and entries[r]["match_pct"] is None for r in films)
    # someone who only likes series keeps anime films in the normal film list
    assert mh.evidence(engine(True), state(0))["anime"] == (0, 0)


def out_first(out):
    top = next(r for r in out["rails"] if r["key"] == "top_picks")
    return [e["row"] for e in out["hero"]] + top["rows"][:10]


# ---- Phase 2: one personal list per taxonomy lane -------------------------------------------------------------------

ALL = set(mh.ALL_LANES)      # every lane switched on, to test the lanes themselves; defaults are tested separately


def lane_engine():
    """40 English films, 10 Hindi films, 10 French films, 15 Korean series, 15 English series, 15 Hindi series."""
    kinds, langs, genres = [], [], []
    for n, k, l in ((40, "movie", "en"), (10, "movie", "hi"), (10, "movie", "fr"), (15, "series", "ko"), (15, "series", "en"), (15, "series", "hi")):
        kinds += [k] * n
        langs += [l] * n
        genres += [["Drama"]] * n
    cat = SimpleNamespace(kind=np.array(kinds, dtype=object), language=langs, genres=genres)
    e = SimpleNamespace(cat=cat)
    e.engaged_rows = lambda st: set(st.liked)
    e.excluded = lambda st: np.array(sorted(set(st.liked) | set(st.ratings)), dtype=np.int64)
    ks = [r for r in range(len(kinds)) if kinds[r] == "series"]
    e.kind_rank = lambda st, fmt: (np.array(ks), np.linspace(0.95, 0.2, len(ks))) if fmt == "series" else (np.array([], dtype=int), np.array([]))
    return e, {"ko": range(60, 75), "en_series": range(75, 90), "hi_series": range(90, 105), "hi_film": range(40, 50), "fr_film": range(50, 60)}


def lane_plan(n_rows):
    entries = {r: {"row": r, "score": 1.0 - r / 100, "match_pct": 80, "shares": {}} for r in range(30)}
    rail = np.full(n_rows, -np.inf)
    rail[:60] = np.linspace(0.9, 0.1, 60)
    return {"rail_scores": rail, "hero": [entries[r] for r in range(5)],
            "rails": [{"key": "top_picks", "rows": list(range(5, 30)), "scored": {r: entries[r] for r in range(5, 30)}}]}


def test_each_series_lane_counts_only_with_its_own_evidence():
    e, rows = lane_engine()
    st = SimpleNamespace(liked=list(rows["ko"])[:8], ratings={}, dislikes=set())            # eight Korean series, nothing else
    out = mh.mix(e, st, lane_plan(105), set(), lanes=ALL)
    shown = [x["row"] for x in out["hero"]] + out["rails"][0]["rows"][:10]
    assert any(r in rows["ko"] for r in shown)
    assert not any(r in rows["hi_series"] or r in rows["en_series"] for r in shown)      # no evidence: no Hindi or English series
    assert all(x["format"] == "korean_series" and x["match_pct"] is None for x in out["hero"] if x["row"] in rows["ko"])
    assert mh.reason("korean_series")[0]["text"] == "Based on the Korean series you have rated highly"


def test_a_hindi_film_fan_keeps_the_film_list_no_separate_film_lane():
    # Phase 5: Indian and international films compete inside the film list (same scale); no lane of their own.
    e, rows = lane_engine()
    plan = lane_plan(105)
    assert mh.mix(e, SimpleNamespace(liked=list(rows["hi_film"])[:8], ratings={}, dislikes=set()), plan, set()) is plan
    plan = lane_plan(105)
    assert mh.mix(e, SimpleNamespace(liked=[0, 1, 2], ratings={}, dislikes=set()), plan, set()) is plan      # English films only: unchanged


def test_disliking_a_lane_removes_it():
    e, rows = lane_engine()
    st = SimpleNamespace(liked=list(rows["fr_film"])[:5], ratings={r: 2 for r in list(rows["fr_film"])[5:10]}, dislikes=set())
    plan = lane_plan(105)
    assert mh.mix(e, st, plan, set()) is plan                  # 5 liked, 5 disliked: weight below the floor


def test_lane_titles_shown_on_earlier_days_go_behind_fresh_ones():
    e, rows = lane_engine()
    st = SimpleNamespace(liked=list(rows["ko"])[:8], ratings={}, dislikes=set())
    first = [x["row"] for x in mh.mix(e, st, lane_plan(105), set(), lanes=ALL)["hero"]]
    later = [x["row"] for x in mh.mix(e, st, lane_plan(105), set(), stale=set(first), lanes=ALL)["hero"]]
    assert not set(later) & set(first)


def test_a_film_is_in_exactly_one_lane_and_is_presented_by_that_lane():
    e, rows = lane_engine()
    fan = SimpleNamespace(liked=list(rows["hi_film"])[:8] + list(rows["ko"])[:8], ratings={}, dislikes=set())
    plan = lane_plan(105)
    # Hindi films 41, 42 are in the plan's own Top Picks with a Match %: they stay films, never relabelled as a lane.
    plan["rails"][0]["rows"] = [r for r in plan["rails"][0]["rows"]] + [41, 42]
    plan["rails"][0]["scored"] = plan["rails"][0]["scored"] | {r: {"row": r, "score": 0.99, "match_pct": 91, "shares": {}} for r in (41, 42)}
    out = mh.mix(e, fan, plan, set(), lanes=ALL)
    entries = {x["row"]: x for x in out["hero"]} | out["rails"][0]["scored"]
    shown = [x["row"] for x in out["hero"]] + out["rails"][0]["rows"][:10]
    assert any(r in rows["ko"] for r in shown)
    assert all(entries[r].get("format") is None for r in shown if r in rows["hi_film"])
    assert len(shown) == len(set(shown))


def test_lane_explanations_name_the_lane():
    assert mh.reason("hollywood_series")[0]["text"] == "Based on the Hollywood series you have rated highly"
    assert mh.reason("indian_film")[0]["text"] == "Based on the Indian films you have rated highly"
    assert mh.reason("anime")[0]["text"] == "Based on the anime you have rated highly"


def test_a_lane_that_is_not_switched_on_never_enters_the_page():
    e, rows = lane_engine()
    st = SimpleNamespace(liked=list(rows["ko"])[:8], ratings={}, dislikes=set())
    plan = lane_plan(105)
    assert mh.mix(e, st, plan, set(), lanes={"anime"}) is plan                       # K-drama fan, Korean lane off: today's Home
    on = mh.mix(e, st, lane_plan(105), set(), lanes={"korean_series"})
    assert any(x.get("format") == "korean_series" for x in on["hero"])


def test_hollywood_and_indian_series_enter_only_when_switched_on_and_never_without_evidence():
    e, rows = lane_engine()
    for key, lane in (("hi_series", "indian_series"), ("en_series", "hollywood_series")):
        fan = SimpleNamespace(liked=list(rows[key])[:10], ratings={}, dislikes=set())
        plan = lane_plan(105)
        assert mh.mix(e, fan, plan, set(), lanes={"anime"}) is plan                    # lane off: today's Home
        assert any(x.get("format") == lane for x in mh.mix(e, fan, lane_plan(105), set(), lanes={lane})["hero"])
        other = SimpleNamespace(liked=list(rows["ko"])[:10], ratings={}, dislikes=set())
        assert not any(x.get("format") == lane for x in mh.mix(e, other, lane_plan(105), set(), lanes=ALL)["hero"])    # no evidence: no lane


def test_film_lanes_need_the_strict_gate_even_when_switched_on():
    e, rows = lane_engine()
    plan = lane_plan(105)
    few = SimpleNamespace(liked=list(rows["hi_film"])[:8], ratings={}, dislikes=set())       # 8 liked: below the 10 needed
    assert mh.mix(e, few, plan, set(), lanes={"indian_film"}) is plan
    diluted = SimpleNamespace(liked=list(rows["hi_film"])[:10] + list(range(0, 12)), ratings={}, dislikes=set())   # not over half of their films
    assert mh.mix(e, diluted, plan, set(), lanes={"indian_film"}) is plan


def test_film_lane_gate_boundaries():
    assert not mh.film_lane_gate(9, 9)           # a pure fan, but under 10 titles
    assert mh.film_lane_gate(10, 10)
    assert not mh.film_lane_gate(10, 20)         # exactly half of their films is not over half
    assert mh.film_lane_gate(11, 20)
    assert not mh.film_lane_gate(0, 0)
