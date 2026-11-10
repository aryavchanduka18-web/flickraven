"""Discovery missions: small personal challenges that widen what someone watches, with live progress.

Progress comes only from what the user actually did on FlickRaven: titles they marked watched, rated, or liked.
Nothing about progress is stored, so it can never drift from the real activity. Only dismissals are stored.
A completed mission shows the date of the activity that completed it (replayed from the activity timestamps).
Each mission says why it was picked, using only numbers from the user's own history. The genre mission is
personal: it picks the biggest catalog genre the user has fewer than GENRE_GOAL titles in, so the choice stays
put while the user works on it (it only moves on once that genre reaches the goal).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

HOME_COUNTRIES = {"US", "IN"}          # the catalog's two biggest film industries; the mission is about going beyond them
CLASSIC_BEFORE = 1980
GENRE_GOAL = 3
DECADE_GOAL = 5
SKIP_GENRES = ("TV Movie", "Documentary")
ALT_GENRES = 3                          # extra genre missions offered in the Explore tab


@dataclass
class Mission:
    key: str
    title: str
    description: str
    goal: int
    unit: Callable[[dict], object] = field(repr=False, default=lambda t: None)   # what one step is, per title (None: no step)
    progress: int = 0
    why: str = ""
    relevance: float = 0.5                  # how well the mission fits this user's history, 0 to 1 (orders Recommended)
    completed_at: datetime | None = None

    @property
    def done(self) -> bool:
        return self.progress >= self.goal


def _is_film(t: dict) -> bool:
    return t["title_type"] == "movie"


def _n(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _lang_name(code: str | None) -> str:
    from cinematch_engine.online import LANGUAGE_NAMES
    return LANGUAGE_NAMES.get(code, (code or "").upper()) if code else ""


def definitions(titles: list[dict], genres: list[str]) -> list[Mission]:
    """The missions for this user. `genres`: the personal genre missions, the user's own pick first."""
    films = [t for t in titles if _is_film(t)]
    main_lang = main_language(titles)
    home = sum(1 for t in films if set(t["countries"] or []) & HOME_COUNTRIES)
    n_main = sum(1 for t in titles if main_lang and t["lang"] == main_lang)
    old = sum(1 for t in films if t["year"] and t["year"] < CLASSIC_BEFORE)
    other_langs = len({t["lang"] for t in titles if t["lang"] and t["lang"] != main_lang})
    decades = len({t["year"] // 10 for t in films if t["year"]})
    gcount: dict[str, int] = {}
    for t in titles:
        for g in t["genres"] or []:
            gcount[g] = gcount.get(g, 0) + 1

    # the country mission counts distinct countries: one film can add several
    out = [
        Mission("world", "International Explorer", "Watch films from 5 different countries beyond the US and India.", 5,
                unit=lambda t: set(c for c in (t["countries"] or []) if c not in HOME_COUNTRIES) if _is_film(t) else None,
                why=(f"{home} of your {_n(len(films), 'film')} are from the US or India." if films else
                     "You have no films logged yet, so any film from outside the US and India counts."),
                relevance=home / len(films) if films else 0.6),
        Mission("languages", "Beyond your language", "Watch titles in 4 languages other than the one you watch most.", 4,
                unit=lambda t: t["lang"] if t["lang"] and t["lang"] != main_lang else None,
                why=(f"{n_main} of your {_n(len(titles), 'title')} are in {_lang_name(main_lang)}; you have tried "
                     f"{_n(other_langs, 'other language')} so far." if main_lang else
                     "Once you log a few titles, this counts languages other than your most-watched one."),
                relevance=n_main / len(titles) if titles else 0.4),
        Mission("classics", "Classic cinema", f"Watch 3 films released before {CLASSIC_BEFORE}.", 3,
                unit=lambda t: t["_k"] if _is_film(t) and t["year"] and t["year"] < CLASSIC_BEFORE else None,
                why=(f"{old} of your {_n(len(films), 'film')} came out before {CLASSIC_BEFORE}." if films else
                     f"You have no films logged yet; these are films from before {CLASSIC_BEFORE}."),
                relevance=1.0 - min(old / 3, 1.0) if films else 0.5),
        Mission("decades", "Through the decades", f"Watch films from {DECADE_GOAL} different decades.", DECADE_GOAL,
                unit=lambda t: t["year"] // 10 if _is_film(t) and t["year"] else None,
                why=(f"Your films cover {_n(decades, 'decade')} so far." if films else
                     "You have no films logged yet, so any decade counts."),
                relevance=1.0 - min(decades / DECADE_GOAL, 1.0) if films else 0.5),
        Mission("mini_series", "Mini-series weekend", "Finish a short series of 8 episodes or fewer.", 1,
                unit=lambda t: t["_k"] if t["title_type"] == "series" and t["episodes"] and t["episodes"] <= 8 else None,
                why="A short series is a small commitment: 8 episodes or fewer.", relevance=0.4),
    ]
    top = max(gcount, key=lambda g: (gcount[g], g)) if gcount else None
    for i, g in enumerate(genres):
        k = gcount.get(g, 0)
        out.insert(2 + i, Mission(
            f"genre:{g}", f"New to {g}", f"You have barely tried {g}. Get to {GENRE_GOAL} {g} titles.", GENRE_GOAL,
            unit=lambda t, g=g: t["_k"] if g in (t["genres"] or []) else None,
            why=(f"You have {_n(k, g + ' title')}" + (f", against {gcount[top]} in {top}." if top and top != g else ".")),
            relevance=0.9 - 0.1 * i))
    return out


def _units(m: Mission, t: dict) -> set:
    u = m.unit(t)
    if u is None:
        return set()
    return set(u) if isinstance(u, (set, frozenset)) else {u}


def progress(titles: list[dict], genres: list[str] | str | None) -> list[Mission]:
    """titles: what the user watched, rated or liked, each {countries, lang, genres, year, title_type, episodes} and
    optionally {id, at} (at = when they first acted on it). Fills progress and completed_at."""
    if isinstance(genres, str):
        genres = [genres]
    titles = [{**t, "_k": t.get("id", i)} for i, t in enumerate(titles)]      # one step per title, even if ids are missing
    out = definitions(titles, list(genres or []))
    ordered = sorted((t for t in titles if t.get("at")), key=lambda t: t["at"])
    for m in out:
        seen: set = set()
        for t in titles:
            seen |= _units(m, t)
        m.progress = min(len(seen), m.goal)
        if m.done and ordered:                              # replay in time order: when did the goal get reached?
            run: set = set()
            for t in ordered:
                run |= _units(m, t)
                if len(run) >= m.goal:
                    m.completed_at = t["at"]
                    break
    return sorted(out, key=lambda m: m.done)                 # open missions first


def tab(m: Mission, dismissed: bool, primary: bool) -> str:
    """Which tab a mission lives in. Completed beats everything (it is an achievement); a dismissed one goes to
    Explore so it can be brought back; one with progress is Active; the rest are Recommended or, for the
    extra genre ideas, Explore."""
    if m.done:
        return "completed"
    if dismissed:
        return "explore"
    if m.progress > 0:
        return "active"
    return "recommended" if primary else "explore"


def main_language(titles: list[dict]) -> str | None:
    """The language the user has the most titles in; ties go to the alphabetically first code, so the progress and
    the suggestions always agree on it."""
    counts: dict[str, int] = {}
    for t in titles:
        if t["lang"]:
            counts[t["lang"]] = counts.get(t["lang"], 0) + 1
    return min(counts, key=lambda l: (-counts[l], l)) if counts else None


def pick_new_genres(titles: list[dict], genres_by_size: list[str], exclude: set[str] | None = None, n: int = 1) -> list[str]:
    """The n most common catalog genres (biggest first) the user has fewer than GENRE_GOAL titles in, skipping
    `exclude` (dismissed ones). (An earlier rule, "0 or 1 titles", dropped the genre as soon as the user's second title
    in it was logged, so the mission could never get past 1 of 3.)"""
    seen: dict[str, int] = {}
    for t in titles:
        for g in t["genres"] or []:
            seen[g] = seen.get(g, 0) + 1
    out = []
    for g in genres_by_size:
        if seen.get(g, 0) < GENRE_GOAL and g not in SKIP_GENRES and g not in (exclude or set()):
            out.append(g)
            if len(out) == n:
                break
    return out


def pick_new_genre(titles: list[dict], genres_by_size: list[str]) -> str | None:
    g = pick_new_genres(titles, genres_by_size)
    return g[0] if g else None
