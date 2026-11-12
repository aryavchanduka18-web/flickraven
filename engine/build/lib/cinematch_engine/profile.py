"""User stage (spec section 6.1).

The stage depends ONLY on the behavioral interaction count b: distinct films the user rated, liked,
disliked, added to My List or marked watched. Onboarding picks are counted separately
(onboarding_count) and never add to b; views, Quick Views and search clicks do not count either.
"""
COLD, WARMING, ESTABLISHED = "cold", "warming", "established"
STAGES = (COLD, WARMING, ESTABLISHED)
BEHAVIORAL_EVENTS = {"rate", "like", "dislike", "list_add", "watched"}

# How much a live event says about taste (2026-11-10):
#   weak       opening a page, a quick view, a search click, a banner click. Anyone can open a page for any reason, and
#              what gets opened depends on what was shown (position, banner), so these never enter the long-term taste
#              profile. They only drive short-term things (Continue Exploring).
#   strong     list add / remove, watched, like, dislike: a deliberate action on a title, weighted in event_weights.yaml.
#   confirmed  a rating (1-10): the user said how much they liked it; the rating itself sets the weight.
WEAK_EVENTS = {"detail_view", "quick_view", "search_click", "hero_view"}
STRONG_EVENTS = {"list_add", "list_remove", "watched", "like", "dislike"}
CONFIRMED_EVENTS = {"rate"}


def tier_of(event_type: str) -> str | None:
    """'weak', 'strong' or 'confirmed' (None for events that say nothing about taste, e.g. a feedback answer)."""
    return ("weak" if event_type in WEAK_EVENTS else "strong" if event_type in STRONG_EVENTS
            else "confirmed" if event_type in CONFIRMED_EVENTS else None)


def stage_of(b: int) -> str:
    if b <= 2:
        return COLD
    if b <= 10:
        return WARMING
    return ESTABLISHED


def behavioral_count(events) -> int:
    """events: iterable of (event_type, movie_id). Counts distinct films with a behavioral event."""
    return len({movie for kind, movie in events if kind in BEHAVIORAL_EVENTS})