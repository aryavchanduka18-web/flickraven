"""More Like This for TV series, helped by Google Gemini.

We have no viewing data for series, so the stored similarity is weak for many of them. Gemini knows TV well, so for a
series page we ask it for similar series BY NAME and keep only the names that exist in our own catalog (same kind of
title, matching year). Nothing it invents can reach the page. Only the title, year and genres are sent: no person,
no account. Answers are cached per title (a week, in memory) and the number of calls per day is capped, so the free
Gemini quota is safe; if anything fails the page silently falls back to the stored similarity list.
"""
import json
import logging
import re
import threading
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import assistant

log = logging.getLogger(__name__)
TTL = 7 * 24 * 3600
ASK = 24                 # names requested; some will not be in the catalog
TIMEOUT = 8.0            # seconds; a slow Gemini must not hold the page
LINE = re.compile(r"^\s*(?:[-*\d.)]+\s*)?(.+?)\s*\((\d{4})\)\s*$")

SYSTEM = ("You recommend TV. Given one TV series, list the %d TV series (or anime series, if it is anime) that fans of it "
          "would enjoy most: same tone, themes, audience and style, not just the same genre. Mix well-known and lesser-known. "
          "Only real titles you are sure exist. Output one per line, exactly 'Title (First air year)', nothing else." % ASK)

MODELS = Path(__file__).resolve().parents[3] / "artifacts" / "models"
_file: dict[str, list[str]] | None = None          # tmdb id -> names, from artifacts/models/ai_similar.json (pipeline/ai_similar.py)
_films: dict[str, list[str]] | None = None        # same for films, from artifacts/models/ai_similar_films.json (pipeline/ai_similar_films.py)
_file_ids: dict[int, list[int]] = {}               # movie id -> catalog ids, resolved once per process
_cache: dict[int, tuple[float, list[int]]] = {}
_calls: dict[str, int] = {}
_lock = threading.Lock()


def enabled() -> bool:
    s = get_settings()
    return bool(s.assistant_enabled and s.gemini_api_key)


def parse(reply: str) -> list[tuple[str, int]]:
    out = []
    for line in reply.splitlines():
        m = LINE.match(line.replace("**", "").replace("[[", "").replace("]]", ""))
        if m:
            out.append((m.group(1).strip(), int(m.group(2))))
    return list(dict.fromkeys(out))


def resolve(db: Session, names: list[tuple[str, int]], kinds: list[str], exclude: int) -> list[int]:
    """Catalog ids for the names, in the given order: same kind of title, year within one."""
    ids: list[int] = []
    for name, year in names:
        row = db.execute(text("""SELECT id FROM movies WHERE lower(title) = lower(:t) AND title_type = ANY(:k)
            AND (year IS NULL OR year BETWEEN :y - 1 AND :y + 1) ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 1"""),
                         {"t": name, "k": kinds, "y": year}).first()
        if row and row[0] != exclude and row[0] not in ids:
            ids.append(row[0])
    return ids


def _budget() -> bool:
    day = assistant.today()
    with _lock:
        for k in [k for k in _calls if k != day]:
            del _calls[k]
        if _calls.get(day, 0) >= get_settings().ai_similar_daily_cap:
            return False
        _calls[day] = _calls.get(day, 0) + 1
        return True


def _load(name: str) -> dict[str, list[str]]:
    path = MODELS / name
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("titles", {}) if path.exists() else {}
    except (OSError, ValueError):
        log.warning("%s could not be read", name)
        return {}


def precomputed(db: Session, movie_id: int, kind: str) -> list[int] | None:
    """Catalog ids from the shipped file (asked once, offline, so no Gemini call at all), or None when the title is not
    in it. Series and anime use ai_similar.json, films ai_similar_films.json (Hindi films so far)."""
    global _file, _films
    if _file is None:
        _file = _load("ai_similar.json")
    if _films is None:
        _films = _load("ai_similar_films.json")
    named = _films if kind == "movie" else _file
    if not named:
        return None
    if movie_id in _file_ids:
        return _file_ids[movie_id]
    row = db.execute(text("SELECT tmdb_id FROM movies WHERE id = :i"), {"i": movie_id}).first()
    names = named.get(str(row[0])) if row else None
    if not names:
        return None
    parsed = [(m.group(1), int(m.group(2))) for n in names if (m := re.match(r"^(.+?)\s*\((\d{4})\)$", n))]
    ids = resolve(db, parsed, ["anime", "series"] if kind in ("anime", "series") else [kind], movie_id)
    _file_ids[movie_id] = ids
    return ids


def suggest(db: Session, movie_id: int, title: str, year: int | None, genres: list[str], kind: str) -> list[int]:
    """Catalog ids of series that Gemini says are like this one (best first), or [] on any problem."""
    pre = precomputed(db, movie_id, kind)
    if pre:
        return pre
    if kind == "movie" or not enabled():     # films come only from the offline file: no live Gemini call per film page
        return []
    now = time.time()
    hit = _cache.get(movie_id)
    if hit and now - hit[0] < TTL:
        return hit[1]
    if not _budget():
        return []
    prompt = f"{title} ({year})" if year else title
    if genres:
        prompt += f". Genres: {', '.join(genres[:4])}."
    try:
        reply = assistant.ask_gemini([{"role": "user", "text": prompt}], SYSTEM, timeout=TIMEOUT)
    except Exception as e:  # never break the page
        log.warning("ai similar failed: %s", type(e).__name__)
        return []
    kinds = ["anime", "series"] if kind in ("anime", "series") else [kind]
    ids = resolve(db, parse(reply), kinds, movie_id)
    log.info("ai similar for %s: %d asked, %d in catalog", movie_id, len(parse(reply)), len(ids))
    if ids:
        _cache[movie_id] = (now, ids)
    return ids
