"""The AI assistant: Google Gemini (Flash), grounded in the catalog so it never shows a title we do not have.

Privacy: the model gets the conversation, a short taste summary (genres and a few liked titles) and, for titles the
user names, the catalog's own synopsis. It never gets a name, an email or an id. Free-tier prompts may be used by
Google to improve its products; the privacy page says so.
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
TITLE_RE = re.compile(r"\[\[(.+?)\]\]")

SYSTEM = """You are FlickRaven's assistant: a friendly, knowledgeable guide to films, TV series and anime. You may chat about \
anything the person wants, and you can answer questions about a title's story, characters, ending or themes.
Rules:
- When you recommend a title, write it as [[Title (Year)]]. FlickRaven only shows titles in its own catalog, so recommend \
only real titles you are sure exist, and never invent one. If you are not sure about a fact, say so.
- Put any plot spoiler (twists, endings, who dies) between || and || so the app can hide it until the person taps. Avoid \
spoilers unless they asked for the ending.
- FlickRaven does not stream anything. Do not claim a title is on a particular service; point people to the Where to watch \
section on the title's page.
- Keep answers short (under 150 words) unless the person asks for detail. Use plain, simple English.
- Use the taste summary only to personalise suggestions; do not recite it back."""

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


def taste_summary(db: Session, user_id: int) -> str:
    genres = [r[0] for r in db.execute(text("""SELECT g.name FROM (
        SELECT movie_id FROM ratings WHERE user_id = :u AND rating >= 8
        UNION SELECT movie_id FROM reactions WHERE user_id = :u AND value = 1) l
        JOIN movie_genres mg ON mg.movie_id = l.movie_id JOIN genres g ON g.id = mg.genre_id
        GROUP BY g.name ORDER BY count(*) DESC LIMIT 4"""), {"u": user_id})]
    liked = [r[0] for r in db.execute(text("""SELECT m.title FROM movies m JOIN (
        SELECT movie_id, rating AS s FROM ratings WHERE user_id = :u AND rating >= 8
        UNION SELECT movie_id, 10 FROM reactions WHERE user_id = :u AND value = 1) l ON l.movie_id = m.id
        ORDER BY l.s DESC, m.tmdb_vote_count DESC NULLS LAST LIMIT 6"""), {"u": user_id})]
    if not genres and not liked:
        return "Taste summary: nothing yet (a new user)."
    return f"Taste summary: likes {', '.join(genres) or 'various genres'}; rated highly: {', '.join(liked) or 'none yet'}."


def named_titles(db: Session, message: str) -> str:
    """Catalog synopsis for titles the user names: every run of 1 to 6 words in the message is tried as an exact title
    (one-word runs need 4+ letters, so "up" or "her" in ordinary speech do not match)."""
    words = re.findall(r"[\w'&.:-]+", message)
    runs = {" ".join(words[i:i + n]).lower().strip(".:-") for n in range(1, 7) for i in range(len(words) - n + 1)}
    runs = [r for r in runs if len(r) >= 4 or (" " in r and len(r) >= 3)][:200]
    if not runs:
        return ""
    rows = db.execute(text("""SELECT title, year, overview FROM movies WHERE lower(title) = ANY(:t)
        ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 3"""), {"t": runs}).mappings().all()
    lines = [f"- {r['title']} ({r['year']}): {(r['overview'] or '')[:500]}" for r in rows]
    return ("Catalog facts about titles mentioned (use these for story questions, say if they are not enough):\n" + "\n".join(lines)) if lines else ""


def ask_gemini(history: list[dict], system: str) -> str:
    s = get_settings()
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["text"]}]} for m in history],
            "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.7, "thinkingConfig": {"thinkingBudget": 0}}}
    try:
        r = httpx.post(URL.format(model=s.gemini_model), json=body, headers={"x-goog-api-key": s.gemini_api_key}, timeout=httpx.Timeout(25.0, connect=5.0))
    except httpx.HTTPError as e:
        log.warning("gemini request failed: %s", type(e).__name__)
        raise HTTPException(502, "The assistant could not be reached. Try again in a moment.")
    if r.status_code != 200:
        log.warning("gemini returned HTTP %s", r.status_code)
        raise HTTPException(502, "The assistant is busy right now. Try again in a moment.")
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
