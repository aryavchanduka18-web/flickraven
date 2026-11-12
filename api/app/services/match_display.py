"""Whether the Match % is shown to people.

2026-11-11 audit (decisions-log): the shipped calibrator was fitted on candidate-pool scores but is applied to the
catalog-wide score, runs 22 to 27 points high offline and can only print 72-93% (75-88% for established users). Until
it is refit on the serving score and checked, the API sends no Match % (cards, title page, Why, Perfect Pick reasons)
and Discover has no Match filter or Match sort. The engine still computes it internally (Surprise Me, the lab page).
Set MATCH_VISIBLE back to True only after the refit passes (ECE < 0.05 per stage on held-out users).
"""
MATCH_VISIBLE = False


def shown(match_pct: int | None) -> int | None:
    """The Match % to put in an API response: the value when Match % is visible, otherwise None."""
    return match_pct if MATCH_VISIBLE else None
