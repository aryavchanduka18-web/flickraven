"""Discovery missions: small personal challenges that widen what someone watches, with live progress.

Progress comes only from what the user actually did on FlickRaven: titles they marked watched, rated, or liked.
Nothing is stored for missions, so progress can never drift from the real activity. The genre mission is personal:
it picks a well-known genre the user has barely touched.
"""
from dataclasses import dataclass

HOME_COUNTRIES = {"US", "IN"}          # the catalog's two biggest film industries; the mission is about going beyond them
CLASSIC_BEFORE = 1980


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
    main_lang = max(langs, key=lambda l: sum(t["lang"] == l for t in titles)) if langs else None
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
                              f"You have barely watched {new_genre}. Try 3 well-rated ones.", 3,
                              sum(1 for t in titles if new_genre in (t["genres"] or []))))
    for m in out:
        m.progress = min(m.progress, m.goal)
    return sorted(out, key=lambda m: m.done)                 # open missions first


def pick_new_genre(titles: list[dict], genres_by_size: list[str]) -> str | None:
    """The most common catalog genre (genres_by_size, biggest first) the user has 0 or 1 titles in."""
    seen: dict[str, int] = {}
    for t in titles:
        for g in t["genres"] or []:
            seen[g] = seen.get(g, 0) + 1
    for g in genres_by_size:
        if seen.get(g, 0) <= 1 and g not in ("TV Movie", "Documentary"):
            return g
    return None
