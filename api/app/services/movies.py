"""Movie payloads: the card shape of spec section 11 and the full detail page."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings

SITE_PRIOR = 20          # community rating: popularity_score acts as 20 prior votes, site ratings add to it

CARD_SQL = """
SELECT m.id, m.title, m.year, m.poster_path, m.backdrop_path, m.logo_path, m.original_language, m.runtime_min,
       m.dominant_color, m.overview, m.popularity_score, m.catalog_part, m.imdb_rating, m.imdb_votes,
       coalesce(array_agg(g.name ORDER BY g.name) FILTER (WHERE g.name IS NOT NULL), '{}') AS genres,
       (SELECT count(*) FROM ratings r WHERE r.movie_id = m.id) AS site_n,
       (SELECT coalesce(sum(r.rating), 0) FROM ratings r WHERE r.movie_id = m.id) AS site_sum
FROM movies m
LEFT JOIN movie_genres mg ON mg.movie_id = m.id LEFT JOIN genres g ON g.id = mg.genre_id
WHERE m.id = ANY(:ids)
GROUP BY m.id
"""


def community_rating(popularity: float | None, site_n: int, site_sum: float) -> float | None:
    """Bayesian average of MovieLens (or TMDB, for films outside MovieLens) and site ratings, 1-10."""
    if popularity is None and not site_n:
        return None
    base = popularity if popularity is not None else 6.5
    return round((base * SITE_PRIOR + float(site_sum)) / (SITE_PRIOR + site_n), 1)


def short(text_: str | None, words: int = 28) -> str | None:
    if not text_:
        return None
    parts = text_.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def user_states(db: Session, user_id: int | None, ids: list[int]) -> dict[int, dict]:
    states = {i: {"rating": None, "reaction": 0, "in_list": False, "watched": False} for i in ids}
    if user_id is None or not ids:
        return states
    p = {"u": user_id, "ids": ids}
    for m, r in db.execute(text("SELECT movie_id, rating FROM ratings WHERE user_id = :u AND movie_id = ANY(:ids)"), p):
        states[m]["rating"] = r
    for m, v in db.execute(text("SELECT movie_id, value FROM reactions WHERE user_id = :u AND movie_id = ANY(:ids)"), p):
        states[m]["reaction"] = v
    for (m,) in db.execute(text("SELECT movie_id FROM user_movie_list WHERE user_id = :u AND movie_id = ANY(:ids)"), p):
        states[m]["in_list"] = True
    for (m,) in db.execute(text("SELECT movie_id FROM watched WHERE user_id = :u AND movie_id = ANY(:ids)"), p):
        states[m]["watched"] = True
    return states


def imdb(row) -> dict:
    """IMDb rating and vote count for display, or nulls when the film has none or IMDB_RATINGS is off."""
    if not get_settings().imdb_ratings or row["imdb_rating"] is None:
        return {"imdb_rating": None, "imdb_votes": None}
    return {"imdb_rating": float(row["imdb_rating"]), "imdb_votes": row["imdb_votes"]}


def cards(db: Session, ids: list[int], user_id: int | None = None, extra: dict[int, dict] | None = None) -> list[dict]:
    """Recommendation item shape (spec 11), in the order of `ids`."""
    if not ids:
        return []
    rows = {r["id"]: r for r in db.execute(text(CARD_SQL), {"ids": ids}).mappings()}
    states = user_states(db, user_id, ids)
    out = []
    for i in ids:
        r = rows.get(i)
        if r is None:
            continue
        e = (extra or {}).get(i, {})
        out.append({
            "movie": {"id": r["id"], "title": r["title"], "year": r["year"], "poster": r["poster_path"],
                      "backdrop": r["backdrop_path"], "logo": r["logo_path"], "genres": list(r["genres"]),
                      "language": r["original_language"], "runtime": r["runtime_min"],
                      "community_rating": community_rating(r["popularity_score"], r["site_n"], r["site_sum"]),
                      **imdb(r),
                      "dominant_color": r["dominant_color"], "overview_short": short(r["overview"]),
                      "catalog_part": r["catalog_part"]},
            "score": e.get("score"), "match_pct": e.get("match_pct"), "reasons": e.get("reasons", []),
            "agreement": e.get("agreement"),
            "user_state": states[i],
        })
    return out


def where_to_watch(db: Session, movie_id: int) -> dict | None:
    """Streaming, free, rent and buy services for the film's stored region (TMDB, data by JustWatch).
    None when TMDB lists no service, so the page never suggests availability it does not know about."""
    rows = db.execute(text("""SELECT region, kind, provider_name AS name, logo_path AS logo, link, fetched_on
        FROM movie_watch_providers WHERE movie_id = :m
        ORDER BY display_priority NULLS LAST, provider_name"""), {"m": movie_id}).mappings().all()
    if not rows:
        return None
    by_kind: dict[str, list[dict]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append({"name": r["name"], "logo": r["logo"]})
    return {"region": rows[0]["region"], "link": rows[0]["link"], "updated": rows[0]["fetched_on"].isoformat(),
            "providers": by_kind}


def detail(db: Session, movie_id: int, user_id: int | None) -> dict | None:
    m = db.execute(text("SELECT * FROM movies WHERE id = :m"), {"m": movie_id}).mappings().first()
    if m is None:
        return None
    p = {"m": movie_id}
    genres = [r[0] for r in db.execute(text(
        "SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = :m ORDER BY g.name"), p)]
    credits = db.execute(text("""SELECT pe.id, pe.name, pe.profile_path, mc.role, mc.character, mc.credit_order
        FROM movie_credits mc JOIN people pe ON pe.id = mc.person_id WHERE mc.movie_id = :m
        ORDER BY mc.role, mc.credit_order NULLS LAST, pe.name"""), p).mappings().all()
    keywords = [r[0] for r in db.execute(text(
        "SELECT k.name FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id WHERE mk.movie_id = :m ORDER BY k.name"), p)]
    awards = [dict(r) for r in db.execute(text(
        "SELECT award, category, year, result FROM movie_awards WHERE movie_id = :m ORDER BY result DESC, year, award"), p).mappings()]
    site = db.execute(text("SELECT count(*), coalesce(sum(rating), 0) FROM ratings WHERE movie_id = :m"), p).first()
    site_hist = dict(db.execute(text("SELECT rating, count(*) FROM ratings WHERE movie_id = :m GROUP BY rating"), p).all())
    hist = list(m["rating_hist"] or [0] * 10)
    hist = [h + site_hist.get(i + 1, 0) for i, h in enumerate(hist)]
    by_role = lambda role: [dict(c) for c in credits if c["role"] == role]
    return {
        "watch": where_to_watch(db, movie_id),
        "id": m["id"], "tmdb_id": m["tmdb_id"], "imdb_id": m["imdb_id"], "title": m["title"],
        "original_title": m["original_title"], "overview": m["overview"], "tagline": m["tagline"],
        "release_date": m["release_date"].isoformat() if m["release_date"] else None, "year": m["year"],
        "runtime": m["runtime_min"], "language": m["original_language"], "spoken_languages": m["spoken_languages"],
        "countries": m["countries"], "certification": m["certification"], "poster": m["poster_path"],
        "backdrop": m["backdrop_path"], "logo": m["logo_path"], "dominant_color": m["dominant_color"],
        "studios": m["studios"], "genres": genres, "keywords": keywords, "awards": awards,
        "directors": by_role("director"), "writers": by_role("writer"), "cast": by_role("cast"),
        "catalog_part": m["catalog_part"],
        "collection": {"id": m["collection_id"], "name": m["collection_name"]} if m["collection_id"] else None,
        "community_rating": community_rating(m["popularity_score"], site[0], site[1]), **imdb(m),
        "rating_count": int((m["ml_rating_count"] or 0) + site[0]), "rating_hist": hist,
        "user_state": user_states(db, user_id, [movie_id])[movie_id],
    }