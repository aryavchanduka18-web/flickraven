"""Candidate lanes for the mixed Home: which taxonomy lane every catalogue row belongs to, and how many titles of each
lane a person has liked or disliked (the evidence that decides how much a lane counts).

A lane is a taxonomy lane (`taxonomy.lane`): indian / hollywood / international film, anime film, indian / hollywood /
korean / international series, anime series. The engine's snapshot has no production countries, so origin falls back to
language (English counts as anglo, Hindi as Indian ...). That differs from the full taxonomy only for English-language
titles made outside the anglophone countries, and for Indian productions in other languages.
"""
from __future__ import annotations

from cinematch_engine import taxonomy

SERIES_LANES = ("indian_series", "hollywood_series", "korean_series", "international_series")
FILM_EXTRA_LANES = ("indian_film", "international_film")       # hollywood_film is the existing film list itself
LABEL = {"indian_film": "Indian films", "international_film": "international films", "hollywood_film": "films",
         "indian_series": "Indian series", "hollywood_series": "Hollywood series", "korean_series": "Korean series",
         "international_series": "international series", "anime_series": "anime", "anime_film": "anime", "anime": "anime"}


def lane_of_rows(cat) -> list[str]:
    """Taxonomy lane of every catalogue row, computed once per catalogue."""
    cached = cat.__dict__.get("_lane_of")
    if cached is None:
        cached = [taxonomy.lane(str(cat.kind[r]), cat.genres[r], cat.language[r], None) for r in range(len(cat.kind))]
        cat.__dict__["_lane_of"] = cached
    return cached


def rows_in_lane(cat, lane: str) -> list[int]:
    return [r for r, l in enumerate(lane_of_rows(cat)) if l == lane]


def group(lane: str) -> str:
    """The evidence group of a lane: anime series and anime films count together as anime."""
    return "anime" if lane.startswith("anime") else lane
