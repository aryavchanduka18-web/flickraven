"""Catalogue taxonomy: independent attributes per title, and the Home lane each title belongs to.

The catalogue's `title_type` mixes two things: 'movie' / 'series' are formats, 'anime' means TV anime. This module
separates them into independent dimensions, so an anime FILM is "movie + anime", a Japanese live-action drama is
"series + Japanese + live action" (not anime), and English is not the same as Hollywood:

    format     movie | series
    style      anime | animation | live_action
    language   the original language code (hi, en, ko, ja, ...)
    origin     india | anglo | korea | japan | china | other   (production countries; language as a fallback)

`lane()` maps those to the Home candidate lanes. Pure functions over catalogue fields: no database, no model.
"""
from __future__ import annotations

INDIAN_LANGUAGES = {"hi", "ta", "te", "ml", "kn", "bn", "mr", "pa", "gu", "or", "as", "ur"}
ANGLO = {"US", "GB", "CA", "AU", "NZ", "IE"}
CHINA = {"CN", "HK", "TW"}
LANES = ("indian_film", "hollywood_film", "international_film", "anime_film",
         "indian_series", "hollywood_series", "korean_series", "international_series", "anime_series")


def fmt(title_type: str) -> str:
    return "series" if title_type in ("series", "anime") else "movie"


def style(title_type: str, genres, language: str) -> str:
    g = set(genres if genres is not None else [])
    if title_type == "anime" or (title_type == "movie" and language == "ja" and "Animation" in g):
        return "anime"
    return "animation" if "Animation" in g else "live_action"


def origin(countries, language: str) -> str:
    c = [str(x) for x in (countries if countries is not None else [])]
    if "IN" in c or (not c and language in INDIAN_LANGUAGES):
        return "india"
    if "KR" in c or (not c and language == "ko"):
        return "korea"
    if "JP" in c or (not c and language == "ja"):
        return "japan"
    if set(c) & CHINA or (not c and language in ("zh", "cn")):
        return "china"
    if set(c) & ANGLO or (not c and language == "en"):
        return "anglo"
    return "other"


def lane(title_type: str, genres, language: str, countries) -> str:
    """The Home lane of one title. Indian = Indian language or Indian production; Hollywood = English-language
    film/series from an anglophone production country; anime is its own lane in both formats."""
    f, s, o = fmt(title_type), style(title_type, genres, language), origin(countries, language)
    if s == "anime":
        return "anime_series" if f == "series" else "anime_film"
    indian = language in INDIAN_LANGUAGES or o == "india"
    if f == "movie":
        if indian:
            return "indian_film"
        return "hollywood_film" if (language == "en" and o == "anglo") else "international_film"
    if indian:
        return "indian_series"
    if language == "ko" or o == "korea":
        return "korean_series"
    return "hollywood_series" if (language == "en" and o == "anglo") else "international_series"


def describe(title_type: str, genres, language: str, countries) -> dict:
    return {"format": fmt(title_type), "style": style(title_type, genres, language), "language": language or "",
            "origin": origin(countries, language), "lane": lane(title_type, genres, language, countries)}
