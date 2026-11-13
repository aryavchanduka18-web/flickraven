from types import SimpleNamespace

import numpy as np

from cinematch_engine import lanes


def cat():
    kind = np.array(["movie", "movie", "movie", "movie", "series", "series", "series", "series", "anime"], dtype=object)
    lang = ["en", "hi", "fr", "ja", "ko", "hi", "en", "es", "ja"]
    genres = [["Drama"], ["Drama"], ["Drama"], ["Animation"], ["Drama"], ["Drama"], ["Crime"], ["Drama"], ["Animation"]]
    return SimpleNamespace(kind=kind, language=lang, genres=genres)


def test_every_row_gets_its_taxonomy_lane():
    assert lanes.lane_of_rows(cat()) == ["hollywood_film", "indian_film", "international_film", "anime_film", "korean_series",
                                         "indian_series", "hollywood_series", "international_series", "anime_series"]


def test_lane_list_is_cached_and_groups_anime_together():
    c = cat()
    assert lanes.lane_of_rows(c) is lanes.lane_of_rows(c)
    assert lanes.rows_in_lane(c, "indian_series") == [5]
    assert lanes.group("anime_film") == "anime" and lanes.group("anime_series") == "anime" and lanes.group("korean_series") == "korean_series"
