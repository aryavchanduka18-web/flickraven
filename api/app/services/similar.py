"""More Like This for one title: neighbours from the engine, and the reasons shown on each card.

Every reason comes from real data about the two titles: keywords both have on TMDB (rarest first, so
"workplace romance" says more than "new york city"), people both share (director or top-5 cast), a close
plot/topic match from the offline similarity model, or the genres they share. Nothing personal.
"""
from collections import Counter

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from cinematch_engine.similar import story_keywords

STORY_TOPIC_MIN, STORY_PLOT_MIN = 0.5, 0.06     # about the top quarter / top tenth of shown neighbours
MAX_REASONS = 2


def _keyword_df(engine) -> Counter:
    df = getattr(engine, "_keyword_df", None)
    if df is None:
        df = Counter(k for ks in engine.cat.keywords for k in set(story_keywords(ks)))
        engine._keyword_df = df
    return df


def shared_people(db: Session, anchor_id: int, ids: list[int]) -> dict[int, list[tuple[str, str]]]:
    """(name, role) pairs each title shares with the anchor: directors and top-5 billed cast."""
    if not ids:
        return {}
    rows = db.execute(text("""
        WITH a AS (SELECT person_id, role FROM movie_credits WHERE movie_id = :a
                   AND (role = 'director' OR (role = 'cast' AND coalesce(credit_order, 99) < 5)))
        SELECT mc.movie_id, p.name, mc.role FROM movie_credits mc
        JOIN a ON a.person_id = mc.person_id AND a.role = mc.role
        JOIN people p ON p.id = mc.person_id
        WHERE mc.movie_id = ANY(:ids) AND (mc.role = 'director' OR coalesce(mc.credit_order, 99) < 5)
        ORDER BY mc.movie_id, mc.role DESC, mc.credit_order NULLS LAST"""), {"a": anchor_id, "ids": ids}).all()
    out: dict[int, list[tuple[str, str]]] = {}
    for m, name, role in rows:
        out.setdefault(m, []).append((name, role))
    return out


def reasons(engine, anchor_row: int, item: dict, people: list[tuple[str, str]]) -> list[dict]:
    cat, row, sig = engine.cat, item["row"], item["signals"]
    df = _keyword_df(engine)
    out = []
    both = set(story_keywords(cat.keywords[anchor_row])) & set(story_keywords(cat.keywords[row]))
    if both:
        kws = sorted(both, key=lambda k: (df.get(k, 0), k))[:2]
        out.append({"code": "similar_themes", "text": "Both: " + ", ".join(kws)})
    directors = [n for n, r in people if r == "director"]
    cast = [n for n, r in people if r == "cast"]
    if directors:
        out.append({"code": "similar_people", "text": f"Same director: {directors[0]}"})
    elif cast:
        out.append({"code": "similar_people", "text": "Also stars " + " and ".join(cast[:2])})
    if sig.get("topic", 0) >= STORY_TOPIC_MIN or sig.get("plot", 0) >= STORY_PLOT_MIN:
        out.append({"code": "similar_story", "text": "Similar story and setting"})
    if not out:
        shared = [g for g in cat.genres[row] if g in set(cat.genres[anchor_row])]
        if shared:
            out.append({"code": "similar_genre", "text": "Also " + " / ".join(shared[:2]).lower()})
    return [{**r, "source": "more_like_this", "share": 0.0, "anchor_movie_id": None} for r in out[:MAX_REASONS]]


def similar_page(db: Session, engine, movie_id: int, offset: int, limit: int) -> tuple[list[dict], dict[int, dict], int]:
    """(items for this page, extra card fields by id, total available)."""
    row = engine.cat.row_of[movie_id]
    items = engine.similar_items(row, k=40)
    total = len(items)
    page = items[offset:offset + limit]
    ids = [int(engine.cat.movie_ids[i["row"]]) for i in page]
    people = shared_people(db, movie_id, ids)
    extra = {mid: {"score": round(i["score"], 4), "reasons": reasons(engine, row, i, people.get(mid, []))}
             for mid, i in zip(ids, page)}
    return page, extra, total


def debug_rows(engine, movie_id: int) -> dict:
    """Everything behind the list, for the owner-only debug view: per candidate type, language, method, final
    score, each stored signal (0..1) and its weight. Signals that the method does not use are null, not 0."""
    cat = engine.cat
    row = cat.row_of[movie_id]
    table = getattr(engine, "similar_table", None)
    items = engine.similar_items(row, k=40)
    from cinematch_engine.similar import DEFAULT_WEIGHTS, STORED
    return {
        "title": cat.titles[row], "type": cat.kind[row], "language": cat.language[row],
        "method": items[0]["method"] if items else None, "table_loaded": table is not None,
        "weights": DEFAULT_WEIGHTS,
        "note": "Score = sum of weight x signal over keywords, plot, topic, genre, people, language, era and "
                "quality (fame percentile). Language, era and quality are not stored per neighbour; the "
                "fallback method only reports genre.",
        "candidates": [{"rank": n + 1, "movie_id": int(cat.movie_ids[i["row"]]), "title": cat.titles[i["row"]],
                        "year": None if np.isnan(cat.year[i["row"]]) else int(cat.year[i["row"]]),
                        "type": cat.kind[i["row"]], "language": cat.language[i["row"]], "score": round(i["score"], 4),
                        "signals": {s: (round(i["signals"][s], 3) if s in i["signals"] else None) for s in STORED},
                        "same_language": cat.language[i["row"]] == cat.language[row],
                        "fame_percentile": round(float(cat.fame_pct[i["row"]]), 1)}
                       for n, i in enumerate(items)],
    }
