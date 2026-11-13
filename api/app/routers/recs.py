"""Recommendations: home page plan, rails, For Tonight, Surprise Me, explanations."""
import time
import uuid

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.services import recommender as rec
from app.services import daily
from app.services import match_display
from app.services import perfect_pick as pp
from app.services import series_fit as fit
from app.services import rec_feedback
from app.services import recent_row
from app.services import series_rails as series_rails_service
from app.services import title_class as tc
from app.services.confidence import agreement_all, confidence
from app.services.movies import cards
from cinematch_engine.tonight import Request as TonightRequest

router = APIRouter(prefix="/recs", tags=["recs"])


def engine_or_503(db):
    if not rec.artifacts_ready():
        raise HTTPException(503, "Recommendation models are not built yet (run the pipeline)")
    return rec.load_engine(db)


def mode_of(db, uid, mode):
    if mode in ("familiar", "balanced", "discover"):
        return mode
    return db.execute(text("SELECT discovery_mode FROM user_preferences WHERE user_id = :u"), {"u": uid}).scalar() or "balanced"


def log_shown(db, uid, request_id, page_id, surface, mode, items):
    for rank, it in enumerate(items):
        db.execute(text("""INSERT INTO recommendation_logs (request_id, user_id, surface, movie_id, rank, final_score,
            match_pct, components, reason_code, mode, page_id) VALUES (:r, :u, :s, :m, :k, :f, :p, CAST(:c AS jsonb), :rc, :mo, :pg)"""),
                   {"r": request_id, "u": uid, "s": surface, "m": it["movie"]["id"], "k": rank, "f": it.get("score"),
                    "p": it.get("match_pct"), "c": __import__("json").dumps(it.get("components") or {}),
                    "rc": it["reasons"][0]["code"] if it.get("reasons") else None, "mo": mode, "pg": page_id})


_SERIES_FACTS: dict = {"at": 0.0, "rows": []}
SERIES_FACTS_TTL = 6 * 3600


def _series_facts(db: Session) -> list[dict]:
    """Static facts about every series (genres, keywords, seasons...) for the Home series rails. The query reads all
    ~4,300 series with their keywords, about 0.5 MB from the hosted database, so it ran on every Home load and was a
    large share of the database's network transfer. The facts only change when the catalogue is refreshed (which
    needs a deploy), so they are kept for six hours. Callers get copies, so a request can never change the cache."""
    now = time.monotonic()
    if not _SERIES_FACTS["rows"] or now - _SERIES_FACTS["at"] > SERIES_FACTS_TTL:
        _SERIES_FACTS["rows"] = [
            {"id": r["id"], "lang": r["original_language"], "countries": r["countries"] or [], "seasons": r["seasons"],
             "keywords": list(r["keywords"] or []),
             "episodes": r["episodes"], "runtime": r["runtime_min"], "status": r["series_status"],
             "genres": list(r["genres"]), "popularity": float(r["popularity_score"] or 0), "votes": r["tmdb_vote_count"] or 0,
             "has_art": r["backdrop_path"] is not None}
            for r in db.execute(text("""
                SELECT m.id, m.original_language, m.countries, m.seasons, m.episodes, m.runtime_min, m.series_status,
                       m.popularity_score, m.tmdb_vote_count, m.backdrop_path,
                       ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres,
                       ARRAY(SELECT k.name FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id WHERE mk.movie_id = m.id) AS keywords
                FROM movies m WHERE m.title_type = 'series'""")).mappings()]
        _SERIES_FACTS["at"] = now
    return [{**r, "genres": list(r["genres"]), "keywords": list(r["keywords"]), "countries": list(r["countries"])}
            for r in _SERIES_FACTS["rows"]]


@router.get("/kind/{kind}")
def kind_rail(kind: str, limit: int = 24, offset: int = 0, user=Depends(current_user),
              db: Session = Depends(get_db)) -> dict:
    """Series or anime for this user (Home rows). No ratings exist for them: content similarity to the user's
    taste plus TMDB popularity, so there is no Match %."""
    if kind not in ("series", "anime"):
        raise HTTPException(404, "Unknown kind")
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    rows, scores = engine.kind_rank(st, kind)
    skip = {engine.cat.row_of[m] for m in rec_feedback.hidden_titles(db, user["id"]) if m in engine.cat.row_of}
    if skip:                                # "Not interested" titles stay out of recommendation rows
        keep_at = [i for i, r in enumerate(rows) if int(r) not in skip]
        rows, scores = [rows[i] for i in keep_at], [scores[i] for i in keep_at]
    page = slice(max(offset, 0), max(offset, 0) + min(limit, 60))
    rows, scores = list(rows), list(scores)
    if offset <= 0 and len(rows) > limit:
        # The first page changes a little every day (a strong core stays) and no language fills the first twelve places.
        from cinematch_engine.rerank import refresh, spread_languages
        keep = refresh(list(zip(rows, scores)), min(limit, 60), daily.rng(user["id"], f"kind:{kind}"))
        keep = spread_languages(keep, [engine.cat.language[r] for r, _ in keep])
        picked = {r for r, _ in keep}
        rows, scores = [r for r, _ in keep] + [r for r in rows if r not in picked], [s for _, s in keep] + [s for r, s in zip(rows, scores) if r not in picked]
    extra = {int(engine.cat.movie_ids[r]): {"score": float(s)} for r, s in zip(rows[page], scores[page])}
    items = cards(db, list(extra), user["id"], extra)
    log_shown(db, user["id"], str(uuid.uuid4()), None, f"kind_{kind}", None, items)   # so the report counts series too
    db.commit()
    return {"items": items, "total": int(len(rows))}


@router.get("/series-rails")
def series_rails(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Themed series rows for Home (see app/services/series_rails.py), a "because you liked ..." row from the series
    the user liked or rated 7+, and one row that mixes films and series. Ordered for this user like the Series row.
    There is no Match % on any of them (series have no ratings here)."""
    engine = engine_or_503(db)
    uid = user["id"]
    st = rec.user_state(db, uid, engine)
    cat = engine.cat
    rows, scores = engine.kind_rank(st, "series")
    not_interested = set(rec_feedback.hidden_titles(db, uid))
    ranked = [int(cat.movie_ids[r]) for r in rows]
    ranked_series_rows = set(rows.tolist())
    series = _series_facts(db)
    engaged = {r for r, v in st.ratings.items() if v >= 7} | st.likes | st.picks | st.in_list
    interest = series_rails_service.affinity([cat.language[r] for r in engaged], list(st.languages))
    shown_series = set(ranked[:24])       # Home's main Series row requests 24 titles.
    rails = []

    # "Because you liked X": the series most like the one the user liked or rated highest.
    liked = {r: 1.0 for r in st.likes | st.picks}
    liked.update({r: (v - 6) / 4 for r, v in st.ratings.items() if v >= 7})
    liked = {r: w for r, w in liked.items() if cat.kind[r] in ("series", "anime")}      # anime fans get one too
    if liked:
        base = min(liked, key=lambda r: (-liked[r], r))
        same_kind = set(engine.kind_rank(st, "anime")[0].tolist()) if cat.kind[base] == "anime" else ranked_series_rows
        similar = [int(cat.movie_ids[r]) for r in engine.similar(base, k=120)
                   if cat.kind[r] == cat.kind[base] and r in same_kind and int(cat.movie_ids[r]) not in shown_series][:20]
        if len(similar) >= series_rails_service.MIN_ROW:
            rails.append({"key": "because", "title": f"Because you liked {cat.titles[base]}",
                          "subtitle": ("Anime" if cat.kind[base] == "anime" else "Series") + " with a similar feel.", "ids": similar})
            shown_series.update(similar)

    day_rng = daily.rng(uid, "series-rails")
    for theme in series_rails_service.build(series, ranked, interest, exclude_ids=shown_series, rng=day_rng):
        rails.append({"key": theme["key"], "title": theme["title"], "subtitle": theme["subtitle"], "ids": theme["ids"]})
        shown_series.update(theme["ids"])

    # Anime series: the big names first (Attack on Titan, Demon Slayer, Solo Leveling...), then romance and feel-good anime.
    anime_rows, _ = engine.kind_rank(st, "anime")
    anime_ids = {int(cat.movie_ids[r]): int(r) for r in anime_rows}
    art = set(db.execute(text("SELECT id FROM movies WHERE title_type = 'anime' AND backdrop_path IS NOT NULL")).scalars())
    anime_list = [(i, r) for i, r in anime_ids.items() if i in art]               # already in the user's anime ranking order
    anime_rails = []
    if engine.anime_interest(st) >= 3:
        # An anime fan already gets Home's personal "Anime for you" row (/kind/anime, their own anime order) right after
        # Top Picks: no second, fame-ranked anime row here, so Home shows one anime row.
        pass
    else:
        hits = [i for i, r in sorted(anime_list, key=lambda t: -cat.fame_pct[t[1]]) if cat.popularity[anime_ids[i]] >= 7.3][:60]
        anime_rails.append(("anime_hits", "Anime everyone is talking about", "The most-watched anime series, from Attack on Titan to Demon Slayer and Solo Leveling.", hits))
    anime_rails.append(("anime_romance", "Romantic anime", "Love stories and romantic comedies in anime form.",
                        tc.evidence_first([i for i, r in anime_list if tc.is_romantic(cat.genres[r], cat.keywords[r], anime=True)],
                                          {i: tc.romance_tier(cat.genres[r], cat.keywords[r], anime=True) for i, r in anime_list})))
    anime_rails.append(("anime_feelgood", "Feel-good anime", "Light, funny and warm anime.",
                        [i for i, r in anime_list if {"Comedy", "Family"} & set(cat.genres[r]) and not {"Horror", "Crime"} & set(cat.genres[r])
                         and not tc.dark_in_tone(cat.keywords[r], cat.genres[r]) and cat.popularity[r] >= 7.0]))
    from cinematch_engine.rerank import refresh
    lead = []
    for key, title, sub, ids in anime_rails:
        ids = [i for i in ids if i not in shown_series]
        ids = refresh(ids, series_rails_service.ROW_SIZE, day_rng) if key != "anime_hits" else refresh(ids, series_rails_service.ROW_SIZE, day_rng, pool_mult=2, keep=6)
        if len(ids) >= series_rails_service.MIN_ROW:
            lead.append({"key": key, "title": title, "subtitle": sub, "ids": ids})
            shown_series.update(ids)
    # The anime hits row comes first among the themed rows; the other anime rows follow the other themes.
    # Anime hits lead only for people who have shown interest in anime (a Japanese language choice is not that); others see it after their first two themed rows.
    themed = [r for r in rails if r["key"] != "because"]
    hits_row = [r for r in lead if r["key"] == "anime_hits"]
    if engine.anime_interest(st) >= 1:
        rails = [r for r in rails if r["key"] == "because"] + hits_row + themed + [r for r in lead if r["key"] != "anime_hits"]
    else:
        rails = [r for r in rails if r["key"] == "because"] + themed[:2] + hits_row + themed[2:] + [r for r in lead if r["key"] != "anime_hits"]

    # Films and series, alternating.
    film_scores = engine.rail_scores(st)
    films = [int(cat.movie_ids[r]) for r in np.argsort(-film_scores)[:30] if np.isfinite(film_scores[r])][:12]
    remaining_series = [mid for mid in ranked if mid not in shown_series]
    mixed = series_rails_service.interleave(films, remaining_series[:12])
    if len(mixed) >= series_rails_service.MIN_ROW:
        rails.append({"key": "mix", "title": "Films and series picked for you", "subtitle": "A mix of both.", "ids": mixed})

    out = []
    request_id = str(uuid.uuid4())
    for r in rails:
        items = cards(db, [i for i in r["ids"] if i not in not_interested], uid)
        if len(items) >= series_rails_service.MIN_ROW:
            out.append({"key": r["key"], "title": r["title"], "subtitle": r["subtitle"], "items": items})
            log_shown(db, uid, request_id, None, f"series_{r['key']}", None, items)   # the report counts series too
    db.commit()
    # How many series the user has shown interest in: Home adds TV-focused rows as this grows (see Home.tsx).
    return {"rails": out, "engaged_series": sum(1 for r in engaged if cat.kind[r] == "series"),
            "engaged_anime": sum(1 for r in engaged if cat.kind[r] == "anime")}


@router.get("/anime")
def anime_page(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The Anime page: rows of anime series (TV anime) and anime films (Japanese animated films), and nothing else.
    Series come in the engine's anime order (kind_rank), films in the film hybrid order (rail_scores); both already
    leave out what this person rated, watched, liked, picked or disliked, and disliked genres. "Not interested" titles
    are left out too. Rows are cut by app/services/anime_rows.py; no title repeats on the page. No Match %."""
    from app.services import anime_rows as ar
    from cinematch_engine.rerank import refresh
    engine = engine_or_503(db)
    uid = user["id"]
    cat, st = engine.cat, rec.user_state(db, uid, engine)
    skip = set(rec_feedback.hidden_titles(db, uid))
    art = set(db.execute(text("""SELECT id FROM movies WHERE backdrop_path IS NOT NULL
        AND (title_type = 'anime' OR (title_type = 'movie' AND original_language = 'ja'))""")).scalars())

    def title(r, kind):
        return ar.Title(id=int(cat.movie_ids[r]), kind=kind, genres=list(cat.genres[r]), keywords=list(cat.keywords[r]),
                        quality=float(cat.popularity[r]), fame=float(cat.fame_pct[r]), has_art=int(cat.movie_ids[r]) in art)

    series_rows, _ = engine.kind_rank(st, "anime")
    series = [title(r, "series") for r in series_rows if int(cat.movie_ids[r]) not in skip]
    rail = engine.rail_scores(st)
    film_rows = [r for r in np.nonzero(np.isfinite(rail))[0]
                 if cat.kind[r] == "movie" and ar.is_anime_film(list(cat.genres[r]), cat.language[r])]
    film_rows.sort(key=lambda r: (-float(rail[r]), int(r)))
    films = [title(r, "film") for r in film_rows if int(cat.movie_ids[r]) not in skip]

    # "Because you liked X": the anime (series or film) this person liked or rated highest, and the anime most like it.
    is_anime = lambda r: cat.kind[r] == "anime" or (cat.kind[r] == "movie" and ar.is_anime_film(list(cat.genres[r]), cat.language[r]))
    liked = {r: 1.0 for r in st.likes | st.picks}
    liked.update({r: (v - 6) / 4 for r, v in st.ratings.items() if v >= 7})
    liked = {r: w for r, w in liked.items() if is_anime(r)}
    because = None
    if liked:
        base = min(liked, key=lambda r: (-liked[r], r))
        because = (cat.titles[base], [int(cat.movie_ids[r]) for r in engine.similar(base, k=120) if is_anime(r)])

    rng = daily.rng(uid, "anime-page")
    rows = ar.build(series, films, because, pick=lambda ids, k, keep=3: refresh(ids, k, rng, keep=keep))
    out, request_id = [], str(uuid.uuid4())
    for r in rows:
        items = cards(db, r["ids"], uid)
        if len(items) >= ar.MIN_ROW:
            out.append({"key": r["key"], "title": r["title"], "subtitle": r["subtitle"], "items": items})
            log_shown(db, uid, request_id, None, f"anime_{r['key']}", None, items)
    db.commit()
    return {"rails": out, "counts": {"series": len(series), "films": len(films)}}


NEXT_BUDGET = {"3": "5", "5": "10", "10": "20", "20": "long"}


@router.get("/series-fit")
def series_fit(budget: str = "", status: str = "", episode_length: str = "", series_type: str = "", genre: str = "",
               language: str = "", sort: str = "best", per_day: int = 2, user=Depends(current_user),
               db: Session = Depends(get_db)) -> dict:
    """Series that fit the time the user has (see app/services/series_fit.py), each with seasons, episodes, total
    hours and days to finish at `per_day` episodes a day (0 = flexible: no schedule). "best" is the user's own series
    ranking (series have no Match %: there are no ratings for them). Series without an episode count or episode
    length are left out and counted in `unknown_length`; nothing is guessed."""
    if (budget not in ("", *fit.BUDGETS) or status not in ("", *fit.STATUS) or episode_length not in ("", *fit.EPISODE_LENGTHS)
            or series_type not in ("", *fit.SERIES_TYPES) or sort not in fit.SORTS):
        raise HTTPException(422, "Unknown filter value")
    per_day = max(0, min(per_day, 10))
    from app.config import get_settings
    show_imdb = get_settings().imdb_ratings
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    rows, _ = engine.kind_rank(st, "series")
    rank = {int(engine.cat.movie_ids[r]): n for n, r in enumerate(rows)}
    info = {r["id"]: dict(r) for r in db.execute(text("""SELECT m.id, m.episodes, m.seasons, m.runtime_min AS runtime,
        m.series_status AS status, m.original_language AS lang, m.imdb_rating AS rating,
        ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres
        FROM movies m WHERE m.title_type = 'series' AND m.backdrop_path IS NOT NULL""")).mappings()}
    pool = [i for i in rank if i in info]
    unknown = sum(1 for i in pool if fit.hours(info[i]["episodes"], info[i]["runtime"]) is None)
    matching = [i for i in pool if fit.fits(info[i], budget, status, episode_length, series_type, genre, language)]
    more = None
    if budget in NEXT_BUDGET:
        wider = sum(1 for i in pool if fit.fits(info[i], NEXT_BUDGET[budget], status, episode_length, series_type, genre, language))
        more = {"budget": NEXT_BUDGET[budget], "extra": wider - len(matching)}
    ordered = fit.order([{"id": i, "hours": fit.hours(info[i]["episodes"], info[i]["runtime"]), "status": info[i]["status"],
                          "rating": info[i]["rating"] if show_imdb else None, "rank": rank[i]} for i in matching], sort)
    ids = [o["id"] for o in ordered[:40]]
    items = cards(db, ids, user["id"])
    for it in items:
        s = info[it["movie"]["id"]]
        it["plan"] = fit.plan(s["episodes"], s["runtime"], per_day)
        it["series"] = {"seasons": s["seasons"], "episodes": s["episodes"], "runtime": s["runtime"], "status": s["status"],
                        "hours": fit.hours(s["episodes"], s["runtime"])}
    languages = sorted({info[i]["lang"] for i in pool if info[i]["lang"]})
    genres = sorted({g for i in pool for g in info[i]["genres"]})
    return {"items": items, "total": len(matching), "unknown_length": unknown, "more_with_next_budget": more,
            "options": {"languages": languages, "genres": genres}}


@router.get("/home")
def home(mode: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    uid = user["id"]
    mode = mode_of(db, uid, mode)
    st = rec.user_state(db, uid, engine)
    scores = engine.scores(st)            # scored once: Home and the agreement numbers share it
    plan = engine.home(st, mode, tuning=rec.user_tuning(db, uid), recent_rows=rec.recent_positive_rows(db, uid, engine),
                       scores=scores, seed=daily.seed(uid, f"home:{mode}"))
    cat = engine.cat
    agree = agreement_all(engine, st, scores)
    request_id, page_id = str(uuid.uuid4()), str(uuid.uuid4())

    def agreement(row):
        return None if np.isnan(agree[row]) else int(agree[row])

    def scored_items(entries):
        extra = {}
        for e in entries:
            mid = int(cat.movie_ids[e["row"]])
            extra[mid] = {"score": e["score"], "match_pct": e["match_pct"], "components": e["shares"],
                          "reasons": engine.reasons(st, e["row"], e["shares"], e.get("reranked", False)),
                          "agreement": agreement(e["row"])}
        return cards(db, list(extra), uid, extra)

    # Feedback on the recommendations themselves (services/rec_feedback.py): "Not interested" titles and hidden rows
    # are left out, and rows this person uses move up while rows they ignore move down.
    skip = {cat.row_of[m] for m in rec_feedback.hidden_titles(db, uid) if m in cat.row_of}
    hidden_rows = rec_feedback.hidden_rows(db, uid)
    hero_entries, skip = rec_feedback.hero_without_hidden(plan, skip)
    hero = scored_items(hero_entries)
    # A separate row of recent films (services/recent_row.py); built last so it never takes a title from another row.
    on_page = {e["row"] for e in hero_entries} | {row for r in plan["rails"] for row in r["rows"]}
    recent = recent_row.recent_rail(cat, plan["rail_scores"], on_page, skip, daily.today().year)
    shown = [r for r in recent_row.insert_after_top_picks(plan["rails"], recent)
             if rec_feedback.base_key(f"rail:{r['key']}") not in hidden_rows]
    order, learned = rec_feedback.reorder([rec_feedback.base_key(f"rail:{r['key']}") for r in shown],
                                          rec_feedback.row_stats(db, uid))
    rails = []
    for r in (shown[i] for i in order):
        rows = [row for row in r["rows"] if row not in skip]
        if r["scored"]:
            items = scored_items([r["scored"][row] for row in rows])
        else:
            extra = {}
            for row in rows:
                s = float(plan["rail_scores"][row])
                extra[int(cat.movie_ids[row])] = {"score": s, "match_pct": engine.match(st.stage, s) if np.isfinite(s) else None,
                                                  "reasons": [r["reason"]] if r.get("reason") else [],
                                                  "agreement": agreement(row)}
            items = cards(db, list(extra), uid, extra)
        subtitle = None
        if r["key"] == "current_phase" and r["reason"].get("genre"):
            subtitle = (f"You've been into {r['reason']['genre'].lower()} films lately. "
                        "Recent likes, ratings and saves count more here than your older history.")
        rails.append({"key": r["key"], "title": r["title"], "subtitle": subtitle, "source": r["source"], "items": items,
                      "learned": learned.get(rec_feedback.base_key(f"rail:{r['key']}"))})
        log_shown(db, uid, request_id, page_id, r["key"], mode, items)
    log_shown(db, uid, request_id, page_id, "hero", mode, hero)
    db.commit()
    return {"stage": plan["stage"], "mode": mode, "hero": hero, "rails": rails, "page_id": page_id, "day": daily.today().isoformat(),
            "hidden_rows": hidden_rows}


class TonightBody(BaseModel):
    mood: str
    runtime: str | None = None
    languages: list[str] = []
    genres: list[str] = []


@router.post("/tonight")
def tonight(body: TonightBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    from cinematch_engine.tonight import moods
    if body.mood not in moods():
        raise HTTPException(422, f"mood must be one of {sorted(moods())}")
    st = rec.user_state(db, user["id"], engine)
    req = TonightRequest(body.mood, body.runtime, body.languages[0] if body.languages else None, body.genres)
    rows, relaxed, note = engine.tonight(st, req)
    scores = engine.rail_scores(st)
    extra = {int(engine.cat.movie_ids[r]): {"score": float(scores[r]), "match_pct": engine.match(st.stage, float(scores[r]))}
             for r in rows}
    items = cards(db, list(extra), user["id"], extra)
    log_shown(db, user["id"], str(uuid.uuid4()), None, "tonight", None, items)
    db.commit()
    return {"items": items, "relaxed": relaxed, "message": note}


class PerfectPickBody(BaseModel):
    kind: str = "movie"                  # movie | series | either
    mood: str | None = None              # a mood from the For Tonight rules, or none
    genres: list[str] = []               # genres the person ticked (soft)
    languages: list[str] = []            # language codes, "other" for any not listed; empty = any language
    time: str = "any"                    # see perfect_pick.MOVIE_TIMES / SERIES_TIMES / EITHER_TIMES
    status: str = "any"                  # any | completed | airing (series only)
    adventure: str = "balanced"          # familiar | balanced | adventurous
    other_languages: bool = False        # drop the language limit ("Include other languages")
    exclude: list[int] = []              # titles already shown (Not these, Show more)
    more: bool = False                   # a "Show more" batch: the next titles in the same order, added below the earlier ones


@router.post("/perfect-pick")
def perfect_pick(body: PerfectPickBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Three picks from up to six answers. Order of work: (1) hard limits (movie or series, length, finished or airing),
    (2) candidates from the film or series ranking, (3) score = 0.55 relevance to this person + 0.25 picked-genre fit +
    0.20 mood fit, (4) novelty by the familiar/balanced/adventurous answer, (5) a genre-diversity pass so the three are not
    clones, (6) a reason per title for each thing that was checked. Kind, time, finished/airing and languages are never
    relaxed. When fewer than three meet mood and genres too, the rest come back separately as `alternatives`, each with
    the answers it misses (one miss before two); when nothing exists in the chosen languages, `offer` asks the person
    to include other languages instead of doing it for them."""
    from cinematch_engine.tonight import matches_mood, moods
    kb = moods()
    tables = {"movie": pp.MOVIE_TIMES, "series": pp.SERIES_TIMES, "either": pp.EITHER_TIMES}
    if (body.kind not in tables or body.time not in tables[body.kind] or body.adventure not in pp.ADVENTURES
            or body.status not in ("any", "completed", "airing") or (body.mood is not None and body.mood not in kb)):
        raise HTTPException(422, "Unknown answer value")
    pf = pp.Prefs(kind=body.kind, mood=body.mood, genres=body.genres[:8], languages=[] if body.other_languages else body.languages[:9],
                  time=body.time, status=body.status, adventure=body.adventure)
    engine = engine_or_503(db)
    cat, st = engine.cat, rec.user_state(db, user["id"], engine)
    skip = set(body.exclude)
    items: list[pp.Item] = []
    rail = engine.rail_scores(st)
    if pf.kind in ("movie", "either"):
        for r in np.nonzero(np.isfinite(rail))[0]:
            i = int(cat.movie_ids[r])
            if cat.kind[r] != "movie" or i in skip:
                continue
            mins = None if np.isnan(cat.runtime[r]) else float(cat.runtime[r])
            items.append(pp.Item(i, "movie", list(cat.genres[r]), list(cat.keywords[r]), cat.language[r], mins, None, None,
                                 float(rail[r]), float(cat.novelty[r]),
                                 anime=pp.is_anime_film(list(cat.genres[r]), cat.language[r])))
    if pf.kind in ("series", "either"):
        scored = {}
        for kind in ("series", "anime"):
            rows, scores = engine.kind_rank(st, kind)
            scored.update({int(cat.movie_ids[r]): (int(r), float(sc)) for r, sc in zip(rows, scores)})
        info = {r["id"]: r for r in db.execute(text("SELECT m.id, m.episodes, m.runtime_min AS runtime, m.seasons, m.series_status AS status "
                                                    "FROM movies m WHERE m.id = ANY(:i) AND m.title_type IN ('series', 'anime') "
                                                    "AND m.backdrop_path IS NOT NULL"), {"i": list(scored)}).mappings()}
        for i, (r, sc) in scored.items():
            d = info.get(i)
            if d is None or i in skip:
                continue
            h = fit.hours(d["episodes"], d["runtime"])
            genres, added = pp.series_genres(list(cat.genres[r]), list(cat.keywords[r]))
            items.append(pp.Item(i, "series", genres, list(cat.keywords[r]), cat.language[r], None if h is None else h * 60,
                                 d["seasons"], d["status"], sc, float(cat.novelty[r]), d["episodes"], added,
                                 anime=cat.kind[r] == "anime"))
    rule = kb.get(pf.mood) if pf.mood else None
    sel = pp.select(items, pf, rule, matches_mood)
    by_id = {i.id: i for i in sel.exact + [i for i, _ in sel.near]}
    picks = pp.choose(pp.rank(sel.exact, pf, rule, matches_mood), pf.adventure, genres={i.id: set(i.genres) for i in sel.exact})
    alts = pp.pick_alternatives(sel.near, pf, rule, matches_mood, 3 - len(picks))

    def out(chosen: list[tuple[pp.Cand, list[str]]], surface: str) -> list[dict]:
        extra = {}
        for c, misses in chosen:
            it = by_id[c.id]
            mp = match_display.shown(engine.match(st.stage, it.rec)) if it.kind == "movie" else None
            extra[c.id] = {"score": it.rec, **({"match_pct": mp} if mp is not None else {}),
                           "reasons": pp.reasons_v2(it, c.role, pf, misses, matches_mood, rule, mp)}
        cards_out = cards(db, [c.id for c, _ in chosen], user["id"], extra)
        misses_by_id = {c.id: m for c, m in chosen}
        for card in cards_out:
            card["misses"] = misses_by_id.get(card["movie"]["id"], [])
        if cards_out:
            log_shown(db, user["id"], str(uuid.uuid4()), None, surface, None, cards_out)
        return cards_out

    items_out = out([(c, []) for c in picks], "perfect_pick")
    alt_out = out(alts, "perfect_pick_alt")
    db.commit()
    message = pp.message(len(items_out), len(alt_out), pf, sel.other_languages, sel.exact_elsewhere, more=body.more)
    if not items_out and not alt_out and not sel.other_languages and not body.more:
        message = f"Nothing fits your {pp.kept(pf)}. Try a longer time, another kind, or more languages."
    relaxed = [m for m in ("mood", "genres", "tone") if any(m in a.get("misses", []) for a in alt_out)]
    # what a "Show more" would still find: exact matches first, then broader alternatives (the same order as here)
    remaining = {"exact": len(sel.exact) - len(items_out), "alternatives": len(sel.near) - len(alt_out)}
    return {"items": items_out, "alternatives": alt_out, "message": message, "relaxed": relaxed, "remaining": remaining,
            "offer": "other_languages" if (sel.other_languages or sel.exact_elsewhere) and len(items_out) < 3 else None}


@router.get("/surprise")
def surprise(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    pick = engine.surprise(st, np.random.default_rng())
    if pick is None:
        return {"item": None, "message": "Rate a few more films first, so we can surprise you well."}
    mid = int(engine.cat.movie_ids[pick["row"]])
    items = cards(db, [mid], user["id"], {mid: pick})
    log_shown(db, user["id"], str(uuid.uuid4()), None, "surprise_me", None, items)
    db.commit()
    return {"item": items[0]}


@router.get("/explain/{movie_id}")
def explain(movie_id: int, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    engine = engine_or_503(db)
    st = rec.user_state(db, user["id"], engine)
    row = engine.cat.row_of.get(movie_id)
    if row is None:
        raise HTTPException(404, "Unknown movie")
    from app.routers.catalog import _shares
    shares = _shares(engine, st, row)
    s = float(engine.rail_scores(st)[row])
    logged = db.execute(text("SELECT count(*) FROM interactions WHERE user_id = :u"), {"u": user["id"]}).scalar() or 0
    return {"movie_id": movie_id, "stage": st.stage, "behavioral_count": st.behavioral_count,
            "logged_interactions": int(logged), "onboarding_count": len(st.picks), "shares": shares,
            "match_pct": match_display.shown(engine.match(st.stage, s) if np.isfinite(s) else None),
            "reasons": engine.reasons(st, row, shares), "weights": engine.weights[st.stage],
            "confidence": confidence(engine, st, row, match_display.shown(engine.match(st.stage, s) if np.isfinite(s) else None))}
