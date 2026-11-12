"""Shared romantic / feel-good classes (app/services/title_class.py). Keyword and genre sets are the real TMDB ones of
the named titles (laptop catalogue, 2026-11-12)."""
from app.services import anime_rows as ar
from app.services import series_rails as sr
from app.services import title_class as tc

# (genres, keywords) of real series
HANNIBAL = (["Drama", "Crime"], ["cannibal", "fbi", "gothic romance", "psychiatrist", "serial killer", "lgbt"])
PRESUMED_INNOCENT = (["Drama", "Mystery"], ["courtroom", "female lover", "infidelity", "legal thriller", "married man"])
LOVECRAFT_COUNTRY = (["Drama", "Mystery", "Science Fiction", "Fantasy"], ["lovecraftian", "racism", "monster"])
BETTER_CALL_SAUL = (["Crime", "Drama"], ["lawyer", "romance", "prequel"])
WEAK_HERO = (["Action", "Adventure", "Drama"], ["bromance", "school bullying"])
BABY_REINDEER = (["Drama"], ["love", "stalker", "comedian"])
BRIDGERTON = (["Drama"], ["romance", "period romance", "regency era"])
HEARTSTOPPER = (["Drama"], ["boys' love (bl)", "first love", "romance", "lgbt"])
CRASH_LANDING = (["Drama", "Comedy"], ["love triangle", "romance", "star crossed lovers", "north korea"])
QUEEN_CHARLOTTE = (["Drama"], ["enduring love", "love", "royalty"])
SEX_AND_THE_CITY = (["Drama", "Comedy"], ["dating", "love", "new york city"])
ELITE = (["Crime", "Mystery", "Drama"], ["boys' love (bl)", "love triangle", "murder", "school"])
REALITY_DATING = (["Reality"], ["romance", "dating show"])


def test_crime_and_mystery_shows_with_a_stray_tag_are_not_romantic():
    for g, k in (HANNIBAL, PRESUMED_INNOCENT, LOVECRAFT_COUNTRY, BETTER_CALL_SAUL, WEAK_HERO, BABY_REINDEER):
        assert not tc.is_romantic(g, k), k


def test_real_romances_pass_including_a_crime_show_with_a_real_romance_thread():
    for g, k in (BRIDGERTON, HEARTSTOPPER, CRASH_LANDING, QUEEN_CHARLOTTE, SEX_AND_THE_CITY, ELITE):
        assert tc.is_romantic(g, k), k


def test_letters_inside_other_words_never_count():
    for word in ("female lover", "bromance", "lovecraftian", "death of a loved one", "necromancer", "self love"):
        assert tc.romance_points([word]) == 0, word


def test_live_action_needs_a_supporting_genre_but_anime_does_not():
    assert not tc.is_romantic(*REALITY_DATING)
    anime = ["Animation", "Comedy", "Science Fiction", "Fantasy"]       # TMDB's coarse TV anime genres
    assert tc.is_romantic(["Animation", "Science Fiction", "Fantasy"], ["romance", "school"], anime=True)
    assert not tc.is_romantic(anime, ["bromance", "volleyball"], anime=True)       # Haikyu!!
    assert tc.is_romantic(["Romance", "Animation"], [], anime=True)                 # a film with the real genre


def test_romance_genre_or_soap_is_enough_and_clear():
    assert tc.clear_romance(["Romance", "Drama"], [])
    assert tc.clear_romance(["Soap"], [])
    assert tc.is_romantic(*QUEEN_CHARLOTTE) and not tc.clear_romance(*QUEEN_CHARLOTTE)   # 3 points: in, not leading


def test_series_rail_romance_and_evidence_order():
    def s(i, gk, **kw):
        g, k = gk
        return dict(id=i, lang="en", countries=["US"], seasons=2, episodes=20, runtime=50, status="Ended", genres=g,
                    keywords=k, popularity=8.0, votes=5000, has_art=True, **kw)
    series = [s(1, HANNIBAL), s(2, PRESUMED_INNOCENT), s(3, QUEEN_CHARLOTTE), s(4, BRIDGERTON), s(5, SEX_AND_THE_CITY),
              s(6, HEARTSTOPPER), s(7, CRASH_LANDING), s(8, ELITE)]
    assert not sr.in_theme("romance", series[0]) and not sr.in_theme("romance", series[1])
    assert all(sr.in_theme("romance", x) for x in series[2:])
    old, themes = sr.MIN_ROW, sr.THEMES
    sr.MIN_ROW, sr.THEMES = 3, {"romance": sr.THEMES["romance"]}      # only this row, so no other row takes titles first
    try:
        rows = {r["key"]: r["ids"] for r in sr.build(series, [1, 2, 3, 5, 4, 6, 7, 8])}
    finally:
        sr.MIN_ROW, sr.THEMES = old, themes
    ids = rows["romance"]
    assert 1 not in ids and 2 not in ids
    assert ids[:4] == [4, 6, 7, 8] and set(ids[4:]) == {3, 5}    # clear romances lead, each group in personal order


def test_feelgood_drops_dark_comedies_and_gore():
    def s(k, g=("Comedy",)):
        return dict(id=1, lang="en", countries=["US"], seasons=3, episodes=30, runtime=25, status="Ended", genres=list(g),
                    keywords=k, popularity=8.0, votes=5000, has_art=True)
    assert sr.in_theme("feelgood", s(["workplace comedy", "mockumentary"]))       # The Office
    assert not sr.in_theme("feelgood", s(["dark comedy", "superhero"], ("Action", "Comedy")))   # Peacemaker
    assert not sr.in_theme("feelgood", s(["horror", "deadites"]))                  # Ash vs Evil Dead
    assert not ar.feelgood(ar.Title(1, "series", ["Animation", "Comedy"], ["gore"], quality=8.0))
    assert ar.feelgood(ar.Title(1, "series", ["Animation", "Comedy"], ["slice of life"], quality=8.0))


def test_anime_rows_use_the_shared_rule():
    assert not ar.romantic(ar.Title(1, "series", ["Animation", "Drama", "Science Fiction"], ["bromance", "mecha"]))
    assert ar.romantic(ar.Title(2, "series", ["Animation", "Comedy"], ["high school romance"]))


def test_romantic_chip_sql_matches_the_python_rule(test_engine):
    """The genre-page / Discover chip (SQL) agrees with is_romantic on the same titles."""
    from sqlalchemy import text
    cases = {"hannibal": HANNIBAL, "presumed": PRESUMED_INNOCENT, "saul": BETTER_CALL_SAUL, "bridgerton": BRIDGERTON,
             "queen": QUEEN_CHARLOTTE, "elite": ELITE, "satc": SEX_AND_THE_CITY, "reality": REALITY_DATING}
    ids = {}
    with test_engine.begin() as conn:
        for n, (key, (gs, ks)) in enumerate(cases.items()):
            mid = conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, title_type)
                VALUES (:t, :n, 2015, 'en', ARRAY['US'], 'series') RETURNING id"""), {"t": 991100 + n, "n": f"TC {key}"}).scalar()
            ids[key] = mid
            for g in gs:
                gid = conn.execute(text("""INSERT INTO genres (name, slug) VALUES (:n, :s)
                    ON CONFLICT (name) DO UPDATE SET slug = genres.slug RETURNING id"""), {"n": g, "s": g.lower()}).scalar()
                conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": mid, "g": gid})
            for k in ks:
                kid = conn.execute(text("""INSERT INTO keywords (name) VALUES (:n)
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"""), {"n": k}).scalar()
                conn.execute(text("INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (:m, :k)"), {"m": mid, "k": kid})
    try:
        sql, p = tc.romance_sql("m")
        with test_engine.connect() as conn:
            got = set(conn.execute(text(f"SELECT m.id FROM movies m WHERE m.id = ANY(:ids) AND {sql}"),
                                   {"ids": list(ids.values()), **p}).scalars())
        want = {ids[k] for k, (g, kw) in cases.items() if tc.is_romantic(g, kw)}
        assert got == want and ids["hannibal"] not in got and ids["bridgerton"] in got
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": list(ids.values())})


def test_numpy_arrays_from_the_catalog_work():
    import numpy as np
    assert tc.is_romantic(np.array(["Drama"]), np.array(["romance", "period romance"]))
    assert not tc.dark_in_tone(np.array([], dtype=object)) and tc.dark_in_tone(None) is False


def test_feelgood_keeps_a_romance_tagged_dark_comedy():
    queen_of_tears = (["Drama", "Comedy"], ["dark comedy", "romance", "contract marriage", "chaebol"])
    assert not tc.dark_in_tone(queen_of_tears[1], queen_of_tears[0])
    assert tc.dark_in_tone(["dark comedy"], ["Comedy"])
    assert not tc.dark_in_tone(["death", "zombie", "torture"], ["Comedy"])      # too broad to count
