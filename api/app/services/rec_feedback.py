"""Feedback on the recommendations themselves (not on the title): "Not interested", hidden rows, and Home rows
that move up or down from how one person uses them.

Everything here is stored as events in `interactions` (no extra table):
- `not_interested` / `not_interested_undo` on a title. The title stays out of that person's recommendation rows for
  HIDE_DAYS. It is NOT a dislike: it does not touch the taste profile, the models or the user stage. A later like or
  My List add on the same title ends it.
- `row_hide` / `row_restore` with the row's key in `source` and no title. The row stays off Home for ROW_HIDE_DAYS.

Row learning reads two things that were already being stored: how often a Home row was shown to this person
(`recommendation_logs`) and what they did from it (`interactions.source` = the row's key). Nothing is shared
between people.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

HIDE_DAYS = 90            # a "Not interested" title stays out of recommendation rows this long
ROW_HIDE_DAYS = 30        # a hidden Home row stays away this long
LEARN_DAYS = 60           # row learning looks this far back (recommendation_logs are kept 60 days)
MIN_SHOWS = 5             # a row is not moved before it was shown this many times
PRIOR_SHOWS = 8           # a row counts as this many "average" showings on top of its own (steadies small numbers)
MAX_SHIFT = 2             # a row moves at most this many places up or down
PINNED_ROWS = {"rail:top_picks"}      # never moved, never hidden: the main answer of the page

ENDS_HIDE = ("not_interested_undo", "like", "list_add")


def base_key(source: str | None) -> str:
    """'rail:because:123' and 'rail:because' are the same row; so are 'because:123' and 'because'."""
    parts = (source or "").split(":")
    if parts[0] in ("rail", "collection"):
        return ":".join(parts[:2])
    return parts[0]


def set_not_interested(db: Session, user_id: int, movie_id: int, source: str | None) -> None:
    db.execute(text("""INSERT INTO interactions (user_id, movie_id, event_type, source)
                       VALUES (:u, :m, 'not_interested', :s)"""), {"u": user_id, "m": movie_id, "s": source})


def undo_not_interested(db: Session, user_id: int, movie_id: int) -> None:
    db.execute(text("""INSERT INTO interactions (user_id, movie_id, event_type)
                       VALUES (:u, :m, 'not_interested_undo')"""), {"u": user_id, "m": movie_id})


def hidden_titles(db: Session, user_id: int | None, ids: list[int] | None = None) -> list[int]:
    """Titles this person marked Not interested in the last HIDE_DAYS and has not undone, liked or saved since.
    Newest first. `ids` narrows the check to those titles."""
    if user_id is None:
        return []
    p = {"u": user_id, "d": HIDE_DAYS, "types": ["not_interested", *ENDS_HIDE]}
    narrow = ""
    if ids is not None:
        if not ids:
            return []
        narrow, p["ids"] = "AND movie_id = ANY(:ids)", ids
    rows = db.execute(text(f"""
        SELECT movie_id, event_type, created_at FROM (
            SELECT DISTINCT ON (movie_id) movie_id, event_type, created_at, id FROM interactions
            WHERE user_id = :u AND movie_id IS NOT NULL AND event_type = ANY(:types) {narrow}
            ORDER BY movie_id, id DESC) latest
        WHERE event_type = 'not_interested' AND created_at >= now() - make_interval(days => :d)
        ORDER BY id DESC"""), p).all()
    return [r[0] for r in rows]


def hide_row(db: Session, user_id: int, source: str) -> None:
    db.execute(text("INSERT INTO interactions (user_id, event_type, source) VALUES (:u, 'row_hide', :s)"),
               {"u": user_id, "s": base_key(source)})


def restore_rows(db: Session, user_id: int) -> int:
    keys = hidden_rows(db, user_id)
    for k in keys:
        db.execute(text("INSERT INTO interactions (user_id, event_type, source) VALUES (:u, 'row_restore', :s)"),
                   {"u": user_id, "s": k})
    return len(keys)


def hidden_rows(db: Session, user_id: int | None) -> list[str]:
    if user_id is None:
        return []
    rows = db.execute(text("""
        SELECT source FROM (
            SELECT DISTINCT ON (source) source, event_type, created_at FROM interactions
            WHERE user_id = :u AND movie_id IS NULL AND event_type IN ('row_hide', 'row_restore') AND source IS NOT NULL
            ORDER BY source, id DESC) latest
        WHERE event_type = 'row_hide' AND created_at >= now() - make_interval(days => :d)
        ORDER BY source"""), {"u": user_id, "d": ROW_HIDE_DAYS}).all()
    return [r[0] for r in rows]


def row_stats(db: Session, user_id: int) -> dict[str, dict]:
    """Per Home film row (key 'rail:<name>'), over the last LEARN_DAYS: `shows` = page loads that showed it,
    `good` = titles the person liked, saved, marked watched or rated 7+ from it (1 each) or opened from it (0.5),
    `bad` = titles they disliked or marked Not interested from it. Each title counts once per kind."""
    p = {"u": user_id, "d": LEARN_DAYS}
    stats: dict[str, dict] = {}
    for surface, shows in db.execute(text("""
            SELECT split_part(surface, ':', 1), count(DISTINCT request_id) FROM recommendation_logs
            WHERE user_id = :u AND surface IS NOT NULL AND created_at >= now() - make_interval(days => :d)
            GROUP BY 1"""), p):
        stats[f"rail:{surface}"] = {"shows": int(shows), "good": 0.0, "bad": 0.0}
    for source, kind, n in db.execute(text("""
            SELECT source, CASE
                     WHEN event_type IN ('like', 'list_add', 'watched') OR (event_type = 'rate' AND value >= 7) THEN 'good'
                     WHEN event_type = 'detail_view' THEN 'open'
                     WHEN event_type IN ('dislike', 'not_interested') THEN 'bad' END AS kind,
                   count(DISTINCT movie_id)
            FROM interactions
            WHERE user_id = :u AND movie_id IS NOT NULL AND source LIKE 'rail:%'
              AND created_at >= now() - make_interval(days => :d)
            GROUP BY 1, 2"""), p):
        s = stats.get(base_key(source))
        if s is None or kind is None:
            continue
        if kind == "good":
            s["good"] += n
        elif kind == "open":
            s["good"] += 0.5 * n
        else:
            s["bad"] += n
    return stats


def shifts(keys: list[str], stats: dict[str, dict]) -> dict[str, int]:
    """How many places each row moves (positive = up).

    UP: a row's value is (good - bad) per showing, steadied towards this person's own average over all their rows;
    a row clearly above the average moves up 1 or 2 places. A row needs MIN_SHOWS showings of its own, and nothing
    moves up until the person has done something good from at least one row.

    DOWN: only on explicit negatives from that row (a dislike or a Not interested on one of its cards). Two or more,
    and more than the good actions from it, move it down 1; four or more, at least twice the good actions, move it
    down 2. A row nobody touched never moves down: not acting is not a "no"."""
    out = {}
    for k in keys:
        s = stats.get(k)
        if s is None or k in PINNED_ROWS:
            continue
        if s["bad"] >= 4 and s["bad"] >= 2 * s["good"]:
            out[k] = -2
        elif s["bad"] >= 2 and s["bad"] > s["good"]:
            out[k] = -1
    seen = [stats[k] for k in keys if k in stats and stats[k]["shows"] > 0]
    shows = sum(s["shows"] for s in seen)
    good = sum(s["good"] for s in seen)
    if not shows or good <= 0:
        return out
    average = max(sum(s["good"] - s["bad"] for s in seen) / shows, 0.0)
    if average <= 0:
        average = good / shows / 2          # more bad than good overall: still rank rows against a positive bar
    for k in keys:
        s = stats.get(k)
        if s is None or s["shows"] < MIN_SHOWS or k in PINNED_ROWS or k in out:
            continue
        value = (s["good"] - s["bad"] + PRIOR_SHOWS * average) / (s["shows"] + PRIOR_SHOWS)
        ratio = value / average
        step = 2 if ratio >= 1.75 else 1 if ratio >= 1.25 else 0
        if step:
            out[k] = step
    return out


def reorder(keys: list[str], stats: dict[str, dict]) -> tuple[list[int], dict[str, str]]:
    """New order of the rows (as indexes into `keys`) and, per moved row, 'up' or 'down'. Pinned rows keep their
    place; the others are sorted by (old place - shift), ties going to the row that earned the move."""
    move = shifts(keys, stats)
    free = [i for i, k in enumerate(keys) if k not in PINNED_ROWS]
    ranked = sorted(free, key=lambda i: (i - 1.1 * move.get(keys[i], 0), i))
    order, it = [], iter(ranked)
    for i, k in enumerate(keys):
        order.append(i if k in PINNED_ROWS else next(it))
    learned = {}
    for new, old in enumerate(order):
        if new < old and move.get(keys[old], 0) > 0:
            learned[keys[old]] = "up"
        elif new > old and move.get(keys[old], 0) < 0:
            learned[keys[old]] = "down"
    return order, learned


def hero_without_hidden(plan: dict, skip: set[int]) -> tuple[list[dict], set[int]]:
    """The Home hero without hidden titles. A hidden title never comes back through a fallback: if hiding shortens the
    hero, the next best Top Picks that are not hidden fill the places, and with nothing left the hero is simply shorter
    (it may be empty). Returns (hero entries, `skip` plus the rows that moved into the hero so the rows do not repeat them)."""
    entries = [e for e in plan["hero"] if e["row"] not in skip]
    missing = len(plan["hero"]) - len(entries)
    top = next((r for r in plan["rails"] if r["key"] == "top_picks"), None)
    if missing > 0 and top is not None:
        spare = [top["scored"][row] for row in top["rows"] if row not in skip and row in top["scored"]][:missing]
        entries += spare
        skip = skip | {e["row"] for e in spare}
    return entries, skip

