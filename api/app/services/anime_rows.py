"""Rows for the Anime page: anime series (TV anime, title_type 'anime') and anime films (Japanese animated films, the
same rule as the Anime genre page and Perfect Pick).

Nothing here ranks anything. The two orders come in already personal: anime series from the engine's `kind_rank`
(taste similarity, learned anime lists, the Gemini graph and fame), anime films from the film hybrid (`rail_scores`).
Both already leave out titles the person rated, watched, liked, picked or disliked, and disliked genres. This module
only cuts those two lists into rows with plain rules, keeps live-action out, and never repeats a title on the page.
"""
from dataclasses import dataclass, field

from app.services import title_class as tc

MIN_ROW = 6          # a row with fewer titles than this is left out
ROW_SIZE = 20


@dataclass
class Title:
    id: int
    kind: str                          # "series" (TV anime) or "film" (anime film)
    genres: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    quality: float = 0.0               # TMDB vote average (0..10)
    fame: float = 0.0                  # vote-count percentile (0..1)
    has_art: bool = True


def is_anime_film(genres: list[str], lang: str) -> bool:
    """Japanese animated film: the rule the Anime genre page uses."""
    return lang == "ja" and "Animation" in genres


ACTION = {"Action", "Adventure", "Action & Adventure", "War", "War & Politics"}
FANTASY = {"Fantasy", "Science Fiction", "Sci-Fi & Fantasy"}
DARK = {"Mystery", "Thriller", "Crime", "Horror"}


def romantic(t: Title) -> bool:
    # Shared rule (app/services/title_class.py): Romance genre (films), or exact romance keywords (TMDB TV has no Romance).
    return tc.is_romantic(t.genres, t.keywords, anime=True)


def feelgood(t: Title) -> bool:
    return (bool({"Comedy", "Family"} & set(t.genres)) and not (DARK & set(t.genres)) and not tc.dark_in_tone(t.keywords, t.genres)
            and t.quality >= 7.0)


THEMES = [
    ("action", "Action and adventure anime", "Battles, quests and big adventures, series and films.",
     lambda t: bool(ACTION & set(t.genres))),
    ("fantasy", "Fantasy and sci-fi anime", "Other worlds, magic and the future.", lambda t: bool(FANTASY & set(t.genres))),
    ("dark", "Dark and mind-bending anime", "Mysteries, thrillers and horror.", lambda t: bool(DARK & set(t.genres))),
    ("romance", "Romantic anime", "Love stories and romantic comedies in anime form.", romantic),
    ("feelgood", "Feel-good anime", "Light, funny and warm anime.", feelgood),
]


def mix(a: list[int], b: list[int], n: int = ROW_SIZE) -> list[int]:
    """Alternate two lists (a first) and carry on with the longer one, no repeats, at most n."""
    out, seen = [], set()
    for i in range(max(len(a), len(b))):
        for lst in (a, b):
            if i < len(lst) and lst[i] not in seen:
                seen.add(lst[i])
                out.append(lst[i])
    return out[:n]


def build(series: list[Title], films: list[Title], because: tuple[str, list[int]] | None = None,
          pick=None) -> list[dict]:
    """Rows for the Anime page. `series` and `films` are in this person's order, best first, and already exclude
    what they have seen or disliked. `because` = (title of the anime they liked most, similar anime ids in order).
    `pick(ids, k, keep)` chooses k of a row (the daily refresh); by default the first k.
    Order: because you liked, anime series for you, anime films for you, anime everyone is talking about,
    anime films everyone knows, then the themes (series and films mixed, each in this person's order)."""
    pick = pick or (lambda ids, k, keep=3: ids[:k])
    series = [t for t in series if t.has_art]
    films = [t for t in films if t.has_art]
    by_id = {t.id: t for t in series + films}
    shown: set[int] = set()
    rows: list[dict] = []

    def add(key, title, subtitle, ids, keep=3):
        ids = pick([i for i in ids if i not in shown and i in by_id], ROW_SIZE, keep)
        if len(ids) >= MIN_ROW:
            rows.append({"key": key, "title": title, "subtitle": subtitle, "ids": ids})
            shown.update(ids)

    if because:
        name, ids = because
        add("because", f"Because you liked {name}", "Anime with a similar feel.", ids, keep=ROW_SIZE)
    add("series", "Anime series for you", "TV anime picked from your taste. Live-action shows are never in this row.",
        [t.id for t in series])
    add("films", "Anime films for you", "Japanese animated films picked from your taste.", [t.id for t in films])
    add("series_hits", "Anime everyone is talking about", "The most-watched anime series, from Attack on Titan to Demon Slayer.",
        [t.id for t in sorted((t for t in series if t.quality >= 7.3), key=lambda t: -t.fame)][:60], keep=6)
    add("film_classics", "Anime films everyone knows", "The best-known anime films, such as the Studio Ghibli classics.",
        [t.id for t in sorted((t for t in films if t.quality >= 7.0), key=lambda t: -t.fame)][:60], keep=6)
    for key, title, subtitle, rule in THEMES:
        add(key, title, subtitle, mix([t.id for t in series if rule(t)], [t.id for t in films if rule(t)], n=ROW_SIZE * 3))
    return rows
