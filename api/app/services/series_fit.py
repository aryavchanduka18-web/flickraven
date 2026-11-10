"""Series Commitment Matcher: series that fit the time someone has, with an honest time estimate.

Total viewing time = episodes x episode length (TMDB's typical episode runtime). A series without an episode count
or runtime is left out rather than guessed. Days to finish = episodes / episodes per day, rounded up.
"""
import math

BUDGETS = {"3": (0, 3), "5": (0, 5), "10": (0, 10), "20": (0, 20), "long": (20, 10_000)}   # hours: (min, max)
EPISODE_LENGTHS = {"short": (0, 30), "medium": (31, 45), "long": (46, 60), "xl": (61, 1_000)}  # minutes
STATUS = {"ended": {"Ended", "Canceled"}, "airing": {"Returning Series"}}


def hours(episodes: int | None, runtime: int | None) -> float | None:
    if not episodes or not runtime:
        return None
    return round(episodes * runtime / 60, 1)


def fits(s: dict, budget: str = "", status: str = "", episode_length: str = "") -> bool:
    """s: {episodes, runtime, status}. Empty filters match everything."""
    h = hours(s.get("episodes"), s.get("runtime"))
    if h is None:
        return False
    if budget:
        lo, hi = BUDGETS[budget]
        if not lo <= h <= hi:
            return False
    if status and s.get("status") not in STATUS[status]:
        return False
    if episode_length:
        lo, hi = EPISODE_LENGTHS[episode_length]
        if not lo <= (s.get("runtime") or 0) <= hi:
            return False
    return True


def plan(episodes: int, runtime: int, per_day: int) -> dict:
    """{hours, days, text}: e.g. 7 episodes x 60 min at 2 a day -> 7.0 hours, 4 days."""
    h = hours(episodes, runtime) or 0
    days = math.ceil(episodes / max(per_day, 1))
    when = "one weekend" if days <= 2 else f"{days} days" if days < 14 else f"about {round(days / 7)} weeks"
    return {"hours": h, "days": days, "text": f"{episodes} episodes, about {h:g} hours: {when} at {per_day} a day"}
