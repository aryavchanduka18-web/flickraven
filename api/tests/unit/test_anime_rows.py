"""Anime page rows: anime only, the person's order kept, no repeats, small rows dropped."""
from app.services import anime_rows as ar


def s(i, **kw):
    return ar.Title(id=i, kind="series", **{"genres": ["Animation", "Action & Adventure"], "quality": 8.0, "fame": 50.0, **kw})


def f(i, **kw):
    return ar.Title(id=i, kind="film", **{"genres": ["Animation", "Fantasy"], "quality": 8.0, "fame": 50.0, **kw})


def test_anime_film_rule():
    assert ar.is_anime_film(["Animation", "Drama"], "ja")
    assert not ar.is_anime_film(["Animation"], "en")          # Pixar is not anime
    assert not ar.is_anime_film(["Drama"], "ja")              # Japanese live-action is not anime


def test_series_and_film_rows_keep_the_persons_order():
    series = [s(i) for i in (5, 3, 1, 2, 4, 6, 7)]
    films = [f(i) for i in (105, 103, 101, 102, 104, 106)]
    rows = {r["key"]: r["ids"] for r in ar.build(series, films)}
    assert rows["series"] == [5, 3, 1, 2, 4, 6, 7]
    assert rows["films"] == [105, 103, 101, 102, 104, 106]


def test_no_title_repeats_and_rows_only_hold_given_titles():
    series = [s(i, fame=float(i)) for i in range(1, 60)]
    films = [f(i, fame=float(i)) for i in range(100, 160)]
    rows = ar.build(series, films)
    ids = [i for r in rows for i in r["ids"]]
    assert len(ids) == len(set(ids))
    assert set(ids) <= set(range(1, 60)) | set(range(100, 160))


def test_because_row_comes_first_and_drops_unknown_titles():
    series = [s(i) for i in range(1, 30)]
    rows = ar.build(series, [], because=("Naruto", [999, 7, 8, 9, 10, 11, 12, 13]))   # 999: seen or not anime
    assert rows[0]["key"] == "because" and rows[0]["title"] == "Because you liked Naruto"
    assert rows[0]["ids"] == [7, 8, 9, 10, 11, 12, 13]
    assert 7 not in next(r for r in rows if r["key"] == "series")["ids"]


def test_small_rows_and_titles_without_art_are_left_out():
    rows = ar.build([s(i) for i in range(1, 4)], [f(i, has_art=False) for i in range(100, 120)])
    assert rows == []


def test_hits_rank_by_fame_and_themes_mix_series_and_films():
    series = [s(i, fame=float(i)) for i in range(1, 40)]
    films = [f(i, genres=["Animation", "Romance"], fame=float(i)) for i in range(100, 200)]
    rows = {r["key"]: r["ids"] for r in ar.build(series, films)}
    hits = rows["series_hits"]
    assert hits == sorted(hits, reverse=True)
    assert "romance" in rows and all(i >= 100 for i in rows["romance"])     # only films are romantic here
    assert ar.mix([1, 2, 3], [10]) == [1, 10, 2, 3]


def test_romance_from_keywords_for_tv_anime():
    assert ar.romantic(s(1, keywords=["first love"])) and not ar.romantic(s(1))
