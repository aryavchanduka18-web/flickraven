"""More Like This: offline neighbour table (cinematch_engine/similar.py) and how OnlineEngine serves it."""
import numpy as np
import pandas as pd

from cinematch_engine import similar as S
from cinematch_engine.online import OnlineEngine
from tests.test_kind_rank import cat


def movies():
    rows = [
        # tmdb, type, overview, keywords, genres, lang, year, votes
        (1, "movie", "Two assistants scheme to make their bosses fall in love at work.",
         ["assistant", "boss", "matchmaking", "workplace romance"], ["Romance", "Comedy"], "en", 2018, 5000),
        (2, "movie", "An executive assistant and her demanding boss fake an engagement.",
         ["assistant", "boss", "workplace romance", "fake engagement"], ["Romance", "Comedy"], "en", 2009, 9000),
        (3, "movie", "A princess swaps places with a baker before christmas.",
         ["christmas", "royalty", "swap"], ["Romance", "Comedy"], "en", 2018, 3000),
        (4, "series", "Office workers at a paper company and their awkward boss.",
         ["boss", "office", "workplace"], ["Comedy"], "en", 2005, 8000),
        (5, "movie", "A professional matchmaker helps a shy accountant win a heiress.",
         ["matchmaking", "dating coach"], ["Romance", "Comedy"], "en", 2005, 7000),
        (6, "series", "A paper company documentary about office life and a clueless manager.",
         ["office", "workplace", "mockumentary"], ["Comedy"], "en", 2001, 4000),
    ]
    df = pd.DataFrame(rows, columns=["tmdb_id", "title_type", "overview", "keywords", "genres", "original_language", "year",
                                     "tmdb_vote_count"])
    df["tagline"] = ""
    return df


def credits():
    return pd.DataFrame({"tmdb_id": [1, 3], "name": ["Zoey", "Zoey"], "role": ["cast", "cast"], "credit_order": [0, 0]})


def test_story_beats_same_genre_and_year():
    f = S.build_features(movies(), credits())
    rows, scores, sig = S.neighbours(f, 0, S.DEFAULT_WEIGHTS, k=3)
    # The workplace/assistant film ranks above the same-year, same-genre, shared-actor christmas film.
    assert rows.tolist().index(1) < rows.tolist().index(2)
    assert sig["keywords"][0] > 0


def test_same_type_only_and_never_itself():
    f = S.build_features(movies(), credits())
    table = S.build_table(f, k=5)
    for r in range(f.n):
        nb = table["rows"][r][table["rows"][r] >= 0]
        assert r not in nb
        assert all(f.kind[x] == f.kind[r] for x in nb)
    assert table["rows"][3][0] == 5          # the series' only series neighbour


def test_table_is_deterministic():
    f = S.build_features(movies(), credits())
    a, b = S.build_table(f, k=3), S.build_table(f, k=3)
    assert (a["rows"] == b["rows"]).all()


def test_engine_serves_table_and_filters_type():
    c = cat(["movie", "movie", "series", "movie"], [5, 5, 5, 5])
    e = OnlineEngine.__new__(OnlineEngine)
    e.cat = c
    rows = np.array([[3, 2, 1], [0, 3, -1], [-1, -1, -1], [0, 1, -1]], dtype=np.int32)
    e.similar_table = {"rows": rows, "scores": np.ones((4, 3), dtype=np.float16),
                       "comps": np.full((1, 4, 3), 255, dtype=np.uint8), "stored": ["keywords"]}
    items = e.similar_items(0)
    assert [i["row"] for i in items] == [3, 1]                 # the series (row 2) is dropped
    assert items[0]["method"] == "neighbours" and items[0]["signals"]["keywords"] == 1.0
    # a title missing from the table uses the fallback, still same type only
    fb = e.similar_items(2)
    assert fb == [] and all(i["method"] == "fallback" for i in e._similar_fallback(0, 5))
    assert all(c.kind[i["row"]] == "movie" for i in e._similar_fallback(0, 5))
