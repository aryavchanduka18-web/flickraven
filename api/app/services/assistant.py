"""The AI assistant: Google Gemini (Flash), grounded in the catalog so it never shows a title we do not have.

Privacy: the model gets the conversation, the catalog's own synopsis for titles the user names and, when the message asks
for suggestions, a shortlist of catalog titles that FlickRaven's engine picked (assistant_context.py). It never gets a
name, an email, an id, or anything from the person's ratings, likes, dislikes, Taste DNA or history. The one exception is
opt-in and off by default: a person who turns on taste sharing also sends, with suggestion requests, one coarse line of
genres, languages and Taste DNA trait phrases with no titles or numbers (assistant_taste.py). Free-tier prompts may be used
by Google to improve its products; the privacy page says so.
"""
import logging
import re
import threading
import time

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings

MAX_CHARS = 1000            # one message
MAX_TURNS = 12              # messages of history sent to the model
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
TITLE_RE = re.compile(r"\[\[(.+?)\]\]")

SYSTEM = """You are FlickRaven's assistant: a friendly, knowledgeable guide to films, TV series and anime from anywhere in the world. \
Answer freely from your own knowledge, like a good friend who has seen everything: stories, characters, cast and crew, endings, \
themes, comparisons, trivia and recommendations, for any title, whether or not FlickRaven lists it. Stay on films, series, \
anime and recommendations; for anything else, say briefly that you are here for movies and shows and steer back.
Rules:
- When you recommend a title, write it as [[Title (Year)]]. Recommend only real titles you are sure exist, never invent one. \
The app turns a name into a link only when FlickRaven has that title and shows it as plain text otherwise, so just name \
the titles you think fit; do not talk about a "catalog" or "database", and never tell the person that FlickRaven does not \
have a title. If you are not sure about a fact or a story, \
say "I am not sure about that one", and answer from what you know if you are confident.
- Follow what the person asks for right now. Keep suggestions in the same kind (TV series for a series request, films for a \
film request), the same language or country (a K-drama request gets K-dramas) and the same mood. Never answer a series \
request with a film unless they ask for films. When FlickRaven gives you its picks for the request, recommend mainly from \
them; they already suit the person.
- Put any plot spoiler (twists, endings, who dies) between || and || so the app can hide it until the person taps. Avoid \
spoilers unless they asked for the ending.
- FlickRaven does not stream anything. Do not claim a title is on a particular service; point people to the Where to watch \
section on the title's page.
- Keep answers short (under 150 words) unless the person asks for detail. Use plain, simple English. You can be wrong: for facts you\
  are unsure of (dates, cast, episode counts), say so rather than guess.
- Do not say how the picks were chosen or claim to know the person's history."""

_used: dict[tuple[str, str], int] = {}
log = logging.getLogger(__name__)
_lock = threading.Lock()


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def cap_for(is_guest: bool) -> int:
    s = get_settings()
    return s.assistant_guest_cap if is_guest else s.assistant_daily_cap


def remaining(user_id: int, is_guest: bool) -> int:
    with _lock:
        return max(0, cap_for(is_guest) - _used.get((str(user_id), today()), 0))


def spend(user_id: int, is_guest: bool) -> None:
    """Count one message, or raise 429 when today's cap is used (per person, in process memory: a restart resets it)."""
    key = (str(user_id), today())
    with _lock:
        for k in [k for k in _used if k[1] != key[1]]:
            del _used[k]
        if _used.get(key, 0) >= cap_for(is_guest):
            raise HTTPException(429, "You have used today's assistant messages. They reset tomorrow.")
        _used[key] = _used.get(key, 0) + 1


def refund(user_id: int, is_guest: bool) -> None:
    """Give a message back when the answer could not be produced (the user should not pay for our failure)."""
    key = (str(user_id), today())
    with _lock:
        if _used.get(key, 0) > 0:
            _used[key] -= 1


def named_titles(db: Session, message: str) -> str:
    """Catalog synopsis for titles the user names: every run of 1 to 6 words in the message is tried as an exact title
    (one-word runs need 4+ letters, so "up" or "her" in ordinary speech do not match)."""
    words = re.findall(r"[\w'&.:-]+", message)
    runs = {" ".join(words[i:i + n]).lower().strip(".:-") for n in range(1, 7) for i in range(len(words) - n + 1)}
    runs = [r for r in runs if len(r) >= 4 or (" " in r and len(r) >= 3)][:200]
    if not runs:
        return ""
    rows = db.execute(text("""SELECT title, year, overview, title_type, original_language FROM movies WHERE lower(title) = ANY(:t)
        ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 3"""), {"t": runs}).mappings().all()
    if not rows:
        rows = fuzzy_titles(db, message)
    lines = [f"- {r['title']} ({r['year']}, {r['title_type']}, language {r['original_language']}): {(r['overview'] or '')[:500]}" for r in rows]
    return ("Catalog facts about titles mentioned (use these for story questions; if they are not enough, say you are not sure):\n" + "\n".join(lines)) if lines else ""


def fuzzy_titles(db: Session, message: str) -> list:
    """Titles the person spelled loosely ("its ok to not be o k drama"): pg_trgm word similarity of each title to the
    message. Needs a title of 6+ letters and a close match, so ordinary chat does not match by accident."""
    q = re.sub(r"[^a-z0-9 ]", "", message.lower())[:200].strip()
    if len(q) < 6:
        return []
    try:
        return db.execute(text("""SELECT title, year, overview, title_type, original_language FROM movies
            WHERE length(title_norm) >= 6 AND word_similarity(title_norm, :q) >= 0.6
            ORDER BY word_similarity(title_norm, :q) DESC, tmdb_vote_count DESC NULLS LAST LIMIT 2"""), {"q": q}).mappings().all()
    except Exception:       # pg_trgm or title_norm missing: skip the nicety, never break the chat
        db.rollback()
        return []


def _gemini_error_details(response) -> tuple[str, str]:
    """Return short provider diagnostics without logging request content or credentials."""
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return "", ""
    if not isinstance(error, dict):
        return "", ""
    status = str(error.get("status") or error.get("code") or "")
    message = " ".join(str(error.get("message") or "").split())[:240]
    api_key = get_settings().gemini_api_key
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return status, message


_working_model: str | None = None   # the last model id that answered; tried first next time


def _post(model: str, body: dict, key: str, timeout: float = 25.0):
    """One request to one model, with a single retry after a network error or a Google 5xx."""
    for attempt in range(2):
        try:
            r = httpx.post(URL.format(model=model), json=body, headers={"x-goog-api-key": key},
                           timeout=httpx.Timeout(timeout, connect=5.0))
        except httpx.HTTPError as e:
            if attempt == 0:
                log.info("gemini request failed (%s); retrying once", type(e).__name__)
                time.sleep(0.25)
                continue
            log.warning("gemini request failed after retry: %s", type(e).__name__)
            raise HTTPException(502, "The assistant could not be reached. Try again in a moment.")
        if r.status_code in RETRYABLE_STATUS_CODES and attempt == 0:
            log.warning("gemini returned transient HTTP %s; retrying once", r.status_code)
            time.sleep(0.25)
            continue
        return r


def ask_gemini(history: list[dict], system: str, timeout: float = 25.0) -> str:
    """Asks Gemini. If a model id is unknown (HTTP 404) the next one in GEMINI_FALLBACK_MODELS is tried, and the one
    that works is remembered and logged, so a retired model name does not switch the assistant off."""
    global _working_model
    s = get_settings()
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["text"]}]} for m in history],
            "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.7}}
    models = [m for m in dict.fromkeys([_working_model, s.gemini_model, *[x.strip() for x in s.gemini_fallback_models.split(",")]]) if m]
    for model in models:
        r = _post(model, body, s.gemini_api_key, timeout)
        if r.status_code != 404:
            break
        log.warning("gemini model %s not found (HTTP 404); trying the next one", model)
    else:
        model = models[-1]
    if r.status_code == 200 and model != _working_model:
        log.warning("gemini model in use: %s", model)
        _working_model = model
    if r.status_code != 200:
        provider_status, provider_message = _gemini_error_details(r)
        log.warning("gemini returned HTTP %s (provider_status=%s, message=%s)",
                    r.status_code, provider_status or "unknown", provider_message or "none")
        if r.status_code in (400, 401, 403, 404):
            detail = "The assistant service needs a configuration update. Please try again later."
        elif r.status_code == 429:
            detail = "The AI service has reached its current request limit. Please try again later."
        else:
            detail = "The assistant is temporarily busy. Try again in a moment."
        raise HTTPException(502, detail)
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip() or "I could not think of an answer to that. Try asking another way."
    except (KeyError, IndexError, ValueError):
        return "I could not answer that one (it may have been blocked). Try asking another way."


def resolve_titles(db: Session, reply: str) -> list[int]:
    """Catalog ids for the [[Title (Year)]] marks in a reply; marks we cannot find are simply not linked."""
    ids: list[int] = []
    for raw in dict.fromkeys(TITLE_RE.findall(reply)):
        m = re.match(r"(.+?)\s*\((\d{4})\)\s*$", raw)
        name, year = (m.group(1), int(m.group(2))) if m else (raw, None)
        row = db.execute(text("""SELECT id FROM movies WHERE lower(title) = lower(:t) AND (CAST(:y AS int) IS NULL OR year = CAST(:y AS int))
            ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 1"""), {"t": name.strip(), "y": year}).first()
        if row and row[0] not in ids:
            ids.append(row[0])
    return ids[:6]
