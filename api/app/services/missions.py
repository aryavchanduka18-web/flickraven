"""Discovery missions: small personal challenges that widen what someone watches, with live progress.

Progress comes only from what the user actually did on FlickRaven: titles they marked watched, rated, or liked.
Nothing is stored for missions, so progress can never drift from the real activity. The genre mission is personal:
it picks the biggest catalog genre the user has fewer than GENRE_GOAL titles in, so the choice stays put while
the user works on it (it only moves on once that genre reaches the goal).
"""
from dataclasses import dataclass

HOME_COUNTRIES = {"US", "IN"}          # the catalog's two biggest film industries; the mission is about going beyond them
CLASSIC_BEFORE = 1980
GENRE_GOAL = 3
SKIP_GENRES = ("TV Movie", "Documentary")


@dataclass
class Mission:
    key: str
    title: str
    description: str
    goal: int
    progress: int = 0

    @property
    def done(self) -> bool:
        return self.progress >= self.goal


def progress(titles: list[dict], new_genre: str | None) -> list[Mission]:
    """titles: what the user watched, rated or liked, each {countries, lang, genres, year, title_type, episodes}."""
    films = [t for t in titles if t["title_type"] == "movie"]
    countries = {c for t in films for c in (t["countries"] or []) if c not in HOME_COUNTRIES}
    langs = {t["lang"] for t in titles if t["lang"]}
    main_lang = main_language(titles)
    out = [
        Mission("world", "International Explorer", "Watch films from 5 different countries beyond the US and India.", 5,
                len(countries)),
        Mission("languages", "Beyond your language", "Watch titles in 4 languages other than the one you watch most.", 4,
                len(langs - {main_lang})),
        Mission("classics", "Classic cinema", f"Watch 3 films released before {CLASSIC_BEFORE}.", 3,
                sum(1 for t in films if t["year"] and t["year"] < CLASSIC_BEFORE)),
        Mission("mini_series", "Mini-series weekend", "Finish a short series of 8 episodes or fewer.", 1,
                sum(1 for t in titles if t["title_type"] == "series" and t["episodes"] and t["episodes"] <= 8)),
    ]
    if new_genre:
        out.insert(2, Mission(f"genre:{new_genre}", f"New to {new_genre}",
                              f"You have barely tried {new_genre}. Get to {GENRE_GOAL} {new_genre} titles.", GENRE_GOAL,
                              sum(1 for t in titles if new_genre in (t["genres"] or []))))
    for m in out:
        m.progress = min(m.progress, m.goal)
    return sorted(out, key=lambda m: m.done)                 # open missions first


def main_language(titles: list[dict]) -> str | None:
    """The language the user has the most titles in; ties go to the alphabetically first code, so the progress and
    the suggestions always agree on it."""
    counts: dict[str, int] = {}
    for t in titles:
        if t["lang"]:
            counts[t["lang"]] = counts.get(t["lang"], 0) + 1
    return min(counts, key=lambda l: (-counts[l], l)) if counts else None


def pick_new_genre(titles: list[dict], genres_by_size: list[str]) -> str | None:
    """The most common catalog genre (genres_by_size, biggest first) the user has fewer than GENRE_GOAL titles in.
    (An earlier rule, "0 or 1 titles", dropped the genre as soon as the user's second title in it was logged, so the
    mission could never get past 1 of 3.)"""
    seen: dict[str, int] = {}
    for t in titles:
        for g in t["genres"] or []:
            seen[g] = seen.get(g, 0) + 1
    for g in genres_by_size:
        if seen.get(g, 0) < GENRE_GOAL and g not in SKIP_GENRES:
            return g
    return None
