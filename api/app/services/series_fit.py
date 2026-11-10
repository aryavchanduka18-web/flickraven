"""Series Commitment Matcher: series that fit the time someone has, with an honest time estimate.

Total viewing time = episodes x episode length (TMDB's typical episode runtime). A series without an episode count
or runtime is left out rather than guessed. Days to finish = episodes / episodes per day, rounded up.
"""
import math

BUDGETS = {"3": (0, 3), "5": (0, 5), "10": (0, 10), "20": (0, 20), "long": (20, 10_000)}   # hours: (min, max)
EPISODE_LENGTHS = {"short": (0, 30), "medium": (31, 45), "long": (46, 60), "xl": (61, 1_000)}  # minutes
SERIES_TYPES = {"mini": (1, 10), "short": (11, 30), "medium": (31, 80), "long": (81, 100_000)}   # by episode count
SORTS = {"best", "shortest", "longest", "rated", "completed"}
STATUS = {"ended": {"Ended", "Canceled"}, "airing": {"Returning Series"}}


def hours(episodes: int | None, runtime: int | None) -> float | None:
    if not episodes or not runtime:
        return None
    return round(episodes * runtime / 60, 1)


def fits(s: dict, budget: str = "", status: str = "", episode_length: str = "", series_type: str = "",
         genre: str = "", language: str = "") -> bool:
    """s: {episodes, runtime, status, genres, lang}. Empty filters match everything."""
    h = hours(s.get("episodes"), s.get("runtime"))
    if h is None:
        return False
    if budget:
        lo, hi = BUDGETS[budget]
        if not lo <= h <= hi:
            return False
    if status and s.get("status") not in STATUS[status]:
        return False
    if series_type:
        lo, hi = SERIES_TYPES[series_type]
        if not lo <= (s.get("episodes") or 0) <= hi:
            return False
    if genre and genre not in (s.get("genres") or []):
        return False
    if language and s.get("lang") != language:
        return False
    if episode_length:
        lo, hi = EPISODE_LENGTHS[episode_length]
        if not lo <= (s.get("runtime") or 0) <= hi:
            return False
    return True


def order(items: list[dict], sort: str) -> list[dict]:
    """items: {id, hours, status, rating, rank} (rank = position in the user's own series ranking, 0 = best).
    Ties always fall back to the user's ranking. Series without an IMDb score go last for "rated"."""
    by_rank = sorted(items, key=lambda i: i["rank"])
    if sort == "shortest":
        return sorted(by_rank, key=lambda i: i["hours"])
    if sort == "longest":
        return sorted(by_rank, key=lambda i: -i["hours"])
    if sort == "rated":
        return sorted(by_rank, key=lambda i: -(i["rating"] if i.get("rating") is not None else -1))
    if sort == "completed":
        return sorted(by_rank, key=lambda i: i["status"] not in STATUS["ended"])
    return by_rank


def plan(episodes: int, runtime: int, per_day: int) -> dict:
    """{hours, days, text}: e.g. 7 episodes x 60 min at 2 a day -> 7.0 hours, 4 days."""
    h = hours(episodes, runtime) or 0
    if per_day <= 0:                                          # "flexible": no schedule was asked for
        return {"hours": h, "days": None, "finish": None, "text": f"{episodes} episodes, about {h:g} hours"}
    days = math.ceil(episodes / max(per_day, 1))
    when = "one weekend" if days <= 2 else f"{days} days" if days < 14 else f"about {round(days / 7)} weeks"
    return {"hours": h, "days": days, "finish": f"{when} at {per_day} a day",
            "text": f"{episodes} episodes, about {h:g} hours: {when} at {per_day} a day"}
