"""Ask Google Gemini, once and offline, which series are similar to each popular series and anime.

    python -m pipeline.ai_similar                 # the 2,500 most-voted series and anime (about 170 Gemini calls)
    python -m pipeline.ai_similar --limit 500     # a smaller first run
    python -m pipeline.ai_similar --per-call 15 --pause 6

Why: there is no viewing data for most series, so the stored similarity gives weak More Like This lists. Gemini knows
TV well. Asking it live for every page would burn the free quota, so it is asked here, in batches (about 15 series
per call), and the answers are written to artifacts/models/ai_similar.json, which ships with the site. The site makes
no Gemini call for a title that is in this file; it matches the names to its own catalog, so a made-up title can never
show. Only the title, year and genres are sent: no person, no account.

Needs GEMINI_API_KEY (and DATABASE_URL, default the local Docker database) in .env. Resumable: titles already in the
file are skipped, and a quota error (HTTP 429) stops the run after saving, so run it again later (e.g. tomorrow).
Rerun monthly with the data refresh; use --refresh to ask again for titles already in the file.
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date

from sqlalchemy import create_engine, text

from pipeline.common import ARTIFACTS, env, get_logger

log = get_logger("ai_similar")
OUT = ARTIFACTS / "models" / "ai_similar.json"
MODELS_TO_TRY = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-flash-latest"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
ASK = 24
NAME = re.compile(r"^(.+?)\s*\((\d{4})\)$")


def prompt(batch: list[dict]) -> str:
    lines = "\n".join(f'{n}. {b["title"]} ({b["year"]}) - {", ".join(b["genres"][:4])}' for n, b in enumerate(batch, 1))
    return (f"For each numbered TV series (or anime) below, list the {ASK} TV series (anime series if it is anime) that its fans "
            "would enjoy most: same tone, themes, audience and style, not only the same genre. Mix well-known and lesser-known; "
            "only real titles you are sure exist; never the series itself. Answer with JSON only: an object whose keys are the "
            'numbers and whose values are arrays of strings written exactly "Title (First air year)".\n\n' + lines)


def ask(body: dict, key: str, start: int) -> tuple[int, dict]:
    """(model index that worked, parsed JSON). Tries the next model on 404. Waits and retries on 429 (rate limit) and on
    5xx or network errors; raises RuntimeError('quota') if 429 keeps coming (daily quota used), RuntimeError for a
    request Google refuses (the HTTP status and its short message are logged)."""
    for i in range(start, len(MODELS_TO_TRY)):
        for attempt in range(4):
            req = urllib.request.Request(URL.format(m=MODELS_TO_TRY[i]), data=json.dumps(body).encode("utf-8"),
                                         headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                detail = " ".join(e.read().decode("utf-8", "replace").split())[:200].replace(key, "[key]")
                log.warning("HTTP %s from %s: %s", e.code, MODELS_TO_TRY[i], detail)
                if e.code == 404:
                    data = None
                    break
                if e.code == 429 or e.code >= 500:
                    if attempt == 3:
                        raise RuntimeError("quota" if e.code == 429 else f"HTTP {e.code}")
                    wait = (30, 60, 90)[attempt] if e.code == 429 else (5, 15, 30)[attempt]
                    log.info("waiting %d s, then retrying", wait)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"HTTP {e.code}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 3:
                    raise RuntimeError(f"network: {type(e).__name__}")
                time.sleep((5, 15, 30)[attempt])
        else:
            data = None
        if data is None:
            log.warning("model %s not found, trying the next", MODELS_TO_TRY[i])
            continue
        text_ = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return i, json.loads(text_)
    raise RuntimeError("no model answered")


def load() -> dict:
    """The saved progress. An earlier run on Windows may have written it in cp1252, so fall back to that."""
    if not OUT.exists():
        return {"titles": {}}
    raw = OUT.read_bytes()
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("cp1252"))


def save(done: dict) -> None:
    """UTF-8 always (Windows defaults to cp1252 and chokes on names like 'ğ'); written to a temp file first so a crash
    cannot damage the saved progress."""
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def clean(names) -> list[str]:
    out = []
    for n in names if isinstance(names, list) else []:
        if isinstance(n, str) and NAME.match(n.strip()):
            out.append(n.strip())
    return list(dict.fromkeys(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2500)
    ap.add_argument("--per-call", type=int, default=15)
    ap.add_argument("--pause", type=float, default=6.0, help="seconds between calls (free tier rate limit)")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    key = env("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing from .env")
    db = create_engine(env("DATABASE_URL", "postgresql+psycopg://cinematch:cinematch@localhost:5432/cinematch"))
    with db.connect() as c:
        rows = c.execute(text("""SELECT m.tmdb_id, m.title, m.year,
              ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres
            FROM movies m WHERE m.title_type IN ('series', 'anime') AND m.year IS NOT NULL
            ORDER BY m.tmdb_vote_count DESC NULLS LAST LIMIT :n"""), {"n": a.limit}).mappings().all()
    done = load()
    todo = [dict(r) for r in rows if a.refresh or str(r["tmdb_id"]) not in done["titles"]]
    log.info("%d series and anime considered, %d to ask about", len(rows), len(todo))
    model, calls = 0, 0
    for s in range(0, len(todo), a.per_call):
        batch = todo[s:s + a.per_call]
        body = {"contents": [{"role": "user", "parts": [{"text": prompt(batch)}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8000, "responseMimeType": "application/json"}}
        try:
            model, answer = ask(body, key, model)
        except RuntimeError as e:
            if str(e) == "quota":
                log.warning("daily quota used. Progress is saved: run the same command again later (e.g. tomorrow).")
                break
            log.warning("a batch failed (%s); skipping it, rerun later to retry", e)
            continue
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.warning("a batch gave an unreadable answer (%s); skipping it, rerun later to retry", type(e).__name__)
            continue
        got = 0
        for n, b in enumerate(batch, 1):
            names = [x for x in clean(answer.get(str(n))) if not x.lower().startswith(b["title"].lower() + " (")]
            if names:
                done["titles"][str(b["tmdb_id"])] = names
                got += 1
        done.update(model=MODELS_TO_TRY[model], built=str(date.today()))
        save(done)
        calls += 1
        log.info("call %d: %d of %d answered, %d titles in the file", calls, got, len(batch), len(done["titles"]))
        time.sleep(a.pause)
    log.info("done: %d titles in %s", len(done["titles"]), OUT)


if __name__ == "__main__":
    main()
