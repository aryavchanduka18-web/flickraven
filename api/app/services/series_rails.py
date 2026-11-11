"""Themed series rows for Home ("... dramas for you" by language, binge-worthy, quick comedy, rewatch favourites).

Each theme is a plain rule over what we know about a series (country, language, seasons, episodes, episode length,
status, genres, popularity). Inside a theme the series are ordered the way the recommender ranks series for this
user (content similarity to their taste plus popularity), so the rows are personal without any invented numbers.
There is no "most rewatched" data, so the rewatch row says what it is: finished series with several seasons.
"""
from dataclasses import dataclass

INDIAN_LANGUAGES = {"hi", "ta", "te", "ml", "kn", "bn", "mr", "pa", "gu", "ur"}
ANGLO_COUNTRIES = {"US", "GB"}
# Language groups behind the "... for you" rows, used to put the rows a user has shown interest in first.
FOR_YOU_LANGUAGES = {"kdrama": {"ko"}, "jdrama": {"ja"}, "indian": INDIAN_LANGUAGES, "anglo": {"en"}}
MIN_ROW = 8
WEEKEND_HOURS = 15      # "get through in a weekend": at most this many hours in total (episodes x episode length)
ROW_SIZE = 20


@dataclass(frozen=True)
class Theme:
    key: str
    title: str
    subtitle: str


THEMES = {
    "kdrama": Theme("kdrama", "Korean dramas for you", "Korean dramas, in the order that suits your taste."),
    "jdrama": Theme("jdrama", "Japanese dramas for you", "Japanese live-action dramas, in the order that suits your taste."),
    "indian": Theme("indian", "Indian series for you", "Hindi, Tamil, Telugu, Malayalam and other Indian-language series, in the order that suits your taste."),
    "anglo": Theme("anglo", "American and British dramas for you", "Dramas made in the US and UK, in the order that suits your taste."),
    "international": Theme("international", "International dramas for you", "Dramas in other languages, such as Spanish, French, Turkish and Chinese, in the order that suits your taste."),
    "acclaimed": Theme("acclaimed", "Highly rated TV dramas", "The highest-rated drama series, by viewer ratings on TMDB."),
    "weekend": Theme("weekend", "Perfect binge-watches", "Short, finished series you can get through in a weekend."),
    "binge": Theme("binge", "Can't stop at just one episode", "Much-loved series with plenty of seasons to get lost in."),
    "quick_comedy": Theme("quick_comedy", "Quick comedy", "Live-action comedy series with short episodes, easy to fit in."),
    "one_season": Theme("one_season", "One Season. One Great Story.", "Finished in a single season: a complete story without a long commitment."),
    "completed": Theme("completed", "Completed Series Worth Bingeing", "Finished series that viewers rate very highly, so there is no wait for the next season."),
    "hidden_gems": Theme("hidden_gems", "Hidden Gems You Might Have Missed", "Well-rated series that fewer people have seen."),
    "returning": Theme("returning", "New Episodes & Returning Shows", "Series that are still airing and well rated. TMDB's status, not an episode calendar."),
    "rewatch": Theme("rewatch", "Great to rewatch", "Finished series with several seasons that hold up a second time."),
}


def in_theme(key: str, s: dict) -> bool:
    """Does the series `s` (keys: lang, countries, seasons, episodes, runtime, status, genres, popularity) fit?"""
    pop = s.get("popularity") or 0
    seasons, episodes = s.get("seasons") or 0, s.get("episodes") or 0
    live_action = "Animation" not in (s.get("genres") or [])           # dramas and sitcoms, not cartoons
    drama = "Drama" in (s.get("genres") or [])                        # the rows say "dramas"
    lang = s.get("lang")
    if key == "kdrama":
        return live_action and drama and lang == "ko"
    if key == "jdrama":
        return live_action and drama and lang == "ja"
    if key == "indian":
        return live_action and lang in INDIAN_LANGUAGES
    if key == "anglo":
        return live_action and drama and lang == "en" and bool(ANGLO_COUNTRIES & set(s.get("countries") or []))
    if key == "international":
        return live_action and drama and bool(lang) and lang not in {"en", "ko", "ja"} | INDIAN_LANGUAGES
    if key == "acclaimed":
        return live_action and "Drama" in (s.get("genres") or []) and pop >= 8.3 and (s.get("votes") or 0) >= 1000
    if key == "weekend":
        runtime = s.get("runtime") or 0                                   # unknown length: not promised as a weekend
        return (s.get("status") == "Ended" and 1 <= seasons <= 3 and 6 <= episodes <= 36 and pop >= 7.8
                and 0 < episodes * runtime <= WEEKEND_HOURS * 60)
    if key == "binge":
        return seasons >= 3 and episodes >= 30 and pop >= 7.5
    if key == "quick_comedy":
        return live_action and "Comedy" in (s.get("genres") or []) and 0 < (s.get("runtime") or 0) <= 30 and episodes >= 20 and pop >= 6.5
    votes = s.get("votes") or 0
    if key == "one_season":
        return s.get("status") in ("Ended", "Canceled") and seasons == 1 and 4 <= episodes <= 16 and pop >= 7.6 and votes >= 300
    if key == "completed":
        return s.get("status") == "Ended" and episodes >= 8 and pop >= 8.0 and votes >= 1000
    if key == "hidden_gems":
        return live_action and pop >= 7.8 and 100 <= votes < 1500
    if key == "returning":
        return s.get("status") == "Returning Series" and pop >= 7.2 and votes >= 300
    if key == "rewatch":
        return s.get("status") == "Ended" and seasons >= 4 and pop >= 7.5
    return False


def affinity(liked_languages: list[str], chosen_languages: list[str]) -> dict[str, int]:
    """How much the user has shown interest in each "... for you" row: titles they liked, rated 7+ or saved in that
    language group (1 each) plus 3 when they chose the language at sign-up. Nothing is hidden by a low value: it only
    decides which rows come first."""
    out = {}
    for key, langs in FOR_YOU_LANGUAGES.items():
        out[key] = sum(1 for l in liked_languages if l in langs) + 3 * bool(langs & set(chosen_languages))
    out["international"] = (sum(1 for l in liked_languages if l and l not in {"en", "ko", "ja"} | INDIAN_LANGUAGES)
                            + 3 * bool(set(chosen_languages) - ({"en", "ko", "ja"} | INDIAN_LANGUAGES)))
    return out


def build(series: list[dict], ranked_ids: list[int], interest: dict[str, int] | None = None,
          exclude_ids: set[int] | None = None) -> list[dict]:
    """[{key, title, subtitle, ids}] for every theme with at least MIN_ROW series, each ordered like `ranked_ids`
    (the user's series ranking, best first); series missing from the ranking (already seen) are left out.
    `exclude_ids` are titles already shown in Home's main Series row or an earlier series shelf. With `interest`
    (see affinity), rows the user has shown interest in come first; the rest keep their order and are still shown,
    so nobody is shut out of a language."""
    by_id = {s["id"]: s for s in series}
    themes = list(THEMES.values())
    if interest:
        themes.sort(key=lambda t: -interest.get(t.key, 0))
    out = []
    used = set(exclude_ids or ())
    for theme in themes:
        ids = [i for i in ranked_ids if i not in used and i in by_id and by_id[i].get("has_art") and in_theme(theme.key, by_id[i])][:ROW_SIZE]
        if len(ids) >= MIN_ROW:
            out.append({"key": theme.key, "title": theme.title, "subtitle": theme.subtitle, "ids": ids})
            used.update(ids)
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
