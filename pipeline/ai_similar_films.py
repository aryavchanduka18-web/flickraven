"""Ask Google Gemini, once and offline, which films are like each Hindi film, and what each film feels like.

    python -m pipeline.ai_similar_films                 # every Hindi film in the catalog (about 120 Gemini calls)
    python -m pipeline.ai_similar_films --limit 200     # a smaller first run
    python -m pipeline.ai_similar_films --language ta   # another language later (Tamil, Telugu ...)

Why: only about 3% of Hindi films have any MovieLens ratings, and most have a one-line plot, so More Like This for a
Hindi film falls back to fame (3 Idiots shows up in 891 of 1,215 Hindi lists). Gemini knows these films. One call per
10 films returns, for each film:
  similar  up to 24 similar films, as "Title (Year)". The site keeps only names that exist in its own catalog.
  traits   mood, tone, pacing and themes, each from a FIXED word list below. Anything outside the list is thrown away.
The traits are stored for the next step (content preferences); nothing reads them yet.

Writes artifacts/models/ai_similar_films.json (separate from ai_similar.json, which the series ranking and its
pre-upload check read). Only title, year, genres and the TMDB plot text are sent: no person, no account.
Needs GEMINI_API_KEY (and DATABASE_URL, default the local Docker database) in .env. Resumable: films already in the
file are skipped, and a quota error (HTTP 429) stops the run after saving; run it again later.
"""
import argparse
import re
import time
from datetime import date

from sqlalchemy import create_engine, text

from pipeline import ai_similar as base
from pipeline.common import ARTIFACTS, env, get_logger

log = get_logger("ai_similar_films")
OUT = ARTIFACTS / "models" / "ai_similar_films.json"
ASK = 24
PLOT_CHARS = 350
NAME = re.compile(r"^(.+?)\s*\((\d{4})\)$")

MOODS = ["dark", "suspenseful", "tense", "gritty", "melancholic", "emotional", "heartwarming", "feel-good", "romantic",
         "funny", "satirical", "inspiring", "nostalgic", "thrilling", "eerie", "chaotic", "epic", "quirky"]
TONES = ["serious", "light", "mixed", "satirical", "melodramatic", "realistic"]
PACING = ["slow-burn", "steady", "fast"]
THEMES = ["revenge", "betrayal", "corruption", "family", "friendship", "love", "class and caste", "politics", "crime and the underworld",
          "war and patriotism", "sports", "coming of age", "mystery and investigation", "social issues", "ambition", "grief and loss",
          "identity", "journey", "supernatural", "history", "gender and society", "religion", "music and performance"]
LIMITS = {"mood": 3, "themes": 3}


def prompt(batch: list[dict]) -> str:
    lines = "\n".join(f'{n}. {b["title"]} ({b["year"]}) - {", ".join(b["genres"][:4])}. {(b["overview"] or "")[:PLOT_CHARS]}'
                      for n, b in enumerate(batch, 1))
    return (f"For each numbered film below, answer with JSON only: an object whose keys are the numbers and whose values are "
            f'objects with "similar" and the four traits. "similar": the {ASK} films that viewers of this film would enjoy most '
            "(same tone, themes, pacing and audience, not only the same genre; mostly Hindi films, other Indian or world "
            'films only if they really fit), written exactly "Title (Release year)", only real films you are sure exist, never '
            'the film itself. Traits, using ONLY these words: "mood": up to 3 of ' + ", ".join(MOODS) +
            '; "tone": one of ' + ", ".join(TONES) + '; "pacing": one of ' + ", ".join(PACING) +
            '; "themes": up to 3 of ' + ", ".join(THEMES) + ".\n\n" + lines)


def clean_traits(raw) -> dict | None:
    """Only words from the fixed lists survive; a film with no valid trait at all gets None."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for key, allowed in (("mood", MOODS), ("tone", TONES), ("pacing", PACING), ("themes", THEMES)):
        v = raw.get(key)
        vals = v if isinstance(v, list) else [v]
        good = [x.strip().lower() for x in vals if isinstance(x, str) and x.strip().lower() in allowed]
        good = list(dict.fromkeys(good))[:LIMITS.get(key, 1)]
        if good:
            out[key] = good if key in LIMITS else good[0]
    return out or None


def load() -> dict:
    return base.read_json(OUT, {"titles": {}, "traits": {}})


def save(done: dict) -> None:
    base.write_json(OUT, done)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", default="hi", help="original language code of the films to ask about")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--per-call", type=int, default=10)
    ap.add_argument("--pause", type=float, default=6.0)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    key = env("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing from .env")
    db = create_engine(env("DATABASE_URL", "postgresql+psycopg://cinematch:cinematch@localhost:5432/cinematch"))
    with db.connect() as c:
        rows = c.execute(text("""SELECT m.tmdb_id, m.title, m.year, m.overview,
              ARRAY(SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id) AS genres
            FROM movies m WHERE m.title_type = 'movie' AND m.original_language = :l AND m.year IS NOT NULL
            ORDER BY m.tmdb_vote_count DESC NULLS LAST LIMIT :n"""), {"l": a.language, "n": a.limit}).mappings().all()
    done = load()
    todo = [dict(r) for r in rows if a.refresh or str(r["tmdb_id"]) not in done["titles"]]
    log.info("%d films considered, %d to ask about", len(rows), len(todo))
    model, calls = 0, 0
    for s in range(0, len(todo), a.per_call):
        batch = todo[s:s + a.per_call]
        body = {"contents": [{"role": "user", "parts": [{"text": prompt(batch)}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 12000, "responseMimeType": "application/json"}}
        try:
            model, answer = base.ask(body, key, model)
        except RuntimeError as e:
            if str(e) == "quota":
                log.warning("daily quota used. Progress is saved: run the same command again later (e.g. tomorrow).")
                break
            log.warning("a batch failed (%s); skipping it, rerun later to retry", e)
            continue
        except (ValueError, KeyError, IndexError) as e:
            log.warning("a batch gave an unreadable answer (%s); skipping it, rerun later to retry", type(e).__name__)
            continue
        got = 0
        for n, b in enumerate(batch, 1):
            item = answer.get(str(n)) if isinstance(answer, dict) else None
            if not isinstance(item, dict):
                continue
            names = [x for x in base.clean(item.get("similar")) if not x.lower().startswith(b["title"].lower() + " (")]
            if names:
                done["titles"][str(b["tmdb_id"])] = names
                got += 1
            traits = clean_traits(item.get("traits", item))
            if traits:
                done["traits"][str(b["tmdb_id"])] = traits
        done.update(model=base.MODELS_TO_TRY[model], built=str(date.today()))
        save(done)
        calls += 1
        log.info("call %d: %d of %d answered, %d films in the file", calls, got, len(batch), len(done["titles"]))
        time.sleep(a.pause)
    log.info("done: %d films in %s", len(done["titles"]), OUT)


if __name__ == "__main__":
    main()
