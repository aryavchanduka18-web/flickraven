"""Catalogue taxonomy: format, style, origin and Home lane are independent and classify the hard cases correctly."""
from cinematch_engine import taxonomy as tx


def test_anime_film_is_movie_plus_anime():
    d = tx.describe("movie", ["Animation", "Fantasy"], "ja", ["JP"])
    assert d == {"format": "movie", "style": "anime", "language": "ja", "origin": "japan", "lane": "anime_film"}


def test_tv_anime_is_series_plus_anime():
    assert tx.describe("anime", ["Animation", "Action"], "ja", ["JP"])["lane"] == "anime_series"


def test_japanese_live_action_is_not_anime():
    d = tx.describe("series", ["Drama"], "ja", ["JP"])
    assert d["style"] == "live_action" and d["lane"] == "international_series"
    assert tx.describe("movie", ["Drama"], "ja", ["JP"])["lane"] == "international_film"


def test_non_japanese_animation_is_not_anime():
    assert tx.describe("movie", ["Animation", "Family"], "en", ["US"])["style"] == "animation"


def test_hindi_and_other_indian():
    assert tx.lane("movie", ["Drama"], "hi", ["IN"]) == "indian_film"
    assert tx.lane("movie", ["Action"], "te", []) == "indian_film"
    assert tx.lane("series", ["Drama"], "hi", ["IN"]) == "indian_series"


def test_english_is_not_hollywood_by_itself():
    assert tx.lane("movie", ["Drama"], "en", ["US"]) == "hollywood_film"
    assert tx.lane("movie", ["Drama"], "en", ["NG"]) == "international_film"          # English, Nigerian production
    assert tx.lane("movie", ["Drama"], "en", ["IN"]) == "indian_film"                 # English-language Indian film
    assert tx.lane("series", ["Crime"], "en", ["GB"]) == "hollywood_series"


def test_korean_and_international_series():
    assert tx.lane("series", ["Drama"], "ko", ["KR"]) == "korean_series"
    assert tx.lane("series", ["Drama"], "es", ["ES"]) == "international_series"


def test_missing_countries_fall_back_to_language():
    assert tx.origin([], "ko") == "korea" and tx.origin(None, "en") == "anglo" and tx.origin([], "fr") == "other"
