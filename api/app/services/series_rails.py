"""Themed series rows for Home (East Asian dramas, popular K-dramas, binge-worthy, quick comedy, rewatch favourites).

Each theme is a plain rule over what we know about a series (country, language, seasons, episodes, episode length,
status, genres, popularity). Inside a theme the series are ordered the way the recommender ranks series for this
user (content similarity to their taste plus popularity), so the rows are personal without any invented numbers.
There is no "most rewatched" data, so the rewatch row says what it is: finished series with several seasons.
"""
from dataclasses import dataclass

EAST_ASIA = {"KR", "JP", "CN", "TW", "HK"}
MIN_ROW = 8
ROW_SIZE = 20


@dataclass(frozen=True)
class Theme:
    key: str
    title: str
    subtitle: str


THEMES = {
    "east_asian": Theme("east_asian", "East Asian TV dramas", "Korean, Japanese, Chinese and Taiwanese dramas."),
    "kdrama": Theme("kdrama", "Popular K-dramas", "The most-watched Korean dramas."),
    "binge": Theme("binge", "Can't stop at just one episode", "Much-loved series with plenty of seasons to get lost in."),
    "quick_comedy": Theme("quick_comedy", "Quick comedy", "Live-action comedy series with short episodes, easy to fit in."),
    "rewatch": Theme("rewatch", "Great to rewatch", "Finished series with several seasons that hold up a second time."),
}


def in_theme(key: str, s: dict) -> bool:
    """Does the series `s` (keys: lang, countries, seasons, episodes, runtime, status, genres, popularity) fit?"""
    pop = s.get("popularity") or 0
    seasons, episodes = s.get("seasons") or 0, s.get("episodes") or 0
    live_action = "Animation" not in (s.get("genres") or [])           # dramas and sitcoms, not cartoons
    if key == "east_asian":
        return live_action and bool(EAST_ASIA & set(s.get("countries") or []))
    if key == "kdrama":
        return live_action and s.get("lang") == "ko"
    if key == "binge":
        return seasons >= 3 and episodes >= 30 and pop >= 7.5
    if key == "quick_comedy":
        return live_action and "Comedy" in (s.get("genres") or []) and 0 < (s.get("runtime") or 0) <= 30 and episodes >= 20 and pop >= 6.5
    if key == "rewatch":
        return s.get("status") == "Ended" and seasons >= 4 and pop >= 7.5
    return False


def build(series: list[dict], ranked_ids: list[int]) -> list[dict]:
    """[{key, title, subtitle, ids}] for every theme with at least MIN_ROW series, each ordered like `ranked_ids`
    (the user's series ranking, best first); series missing from the ranking (already seen) are left out."""
    by_id = {s["id"]: s for s in series}
    out = []
    for theme in THEMES.values():
        ids = [i for i in ranked_ids if i in by_id and by_id[i].get("has_art") and in_theme(theme.key, by_id[i])][:ROW_SIZE]
        if len(ids) >= MIN_ROW:
            out.append({"key": theme.key, "title": theme.title, "subtitle": theme.subtitle, "ids": ids})
    return out


def interleave(films: list[int], series: list[int], n: int = 20) -> list[int]:
    """Films and series alternating (film first), no repeats, at most n."""
    out, seen = [], set()
    for a, b in zip(films, series):
        for x in (a, b):
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out[:n]
