"""For Tonight: constraint-based recommendation (spec section 6.10).

The knowledge base is the rule table in config/moods.yaml (mood -> genres / keywords). Constraints
are hard filters; survivors are ranked by the user's hybrid score. If nothing matches, constraints
are relaxed in this order: runtime band (widen by one band), then genres, then mood (nearest mood),
then language, and the user is told what was relaxed.
"""
from dataclasses import dataclass, field
from importlib.resources import files

import numpy as np
import yaml

RUNTIME_BANDS = {"short": (0, 89), "medium": (90, 120), "long": (121, 999)}
WIDER = {"short": "medium", "medium": "long", "long": "medium"}
BAND_TEXT = {"short": "under 90 minutes", "medium": "90-120 minutes", "long": "over 2 hours"}


def moods() -> dict:
    return yaml.safe_load(files("cinematch_engine.config").joinpath("moods.yaml").read_text(encoding="utf-8"))


@dataclass
class Request:
    mood: str
    runtime: str | None = None          # short | medium | long | None
    language: str | None = None
    genres: list[str] = field(default_factory=list)


def matches_mood(film: dict, rule: dict) -> bool:
    genres = set(film["genres"])
    if genres & set(rule.get("genres", [])):
        return True
    for combo in rule.get("genre_with_keywords", []):
        if combo["genre"] in genres and set(film["keywords"]) & set(combo["keywords"]):
            return True
    return False


def runtime_ok(film: dict, band: str | None, widened: bool) -> bool:
    if band is None or film.get("runtime_min") is None:
        return band is None
    lo, hi = RUNTIME_BANDS[band]
    if widened:
        lo2, hi2 = RUNTIME_BANDS[WIDER[band]]
        lo, hi = min(lo, lo2), max(hi, hi2)
    return lo <= film["runtime_min"] <= hi


def recommend(films: list[dict], scores: np.ndarray, req: Request, k: int = 10, min_results: int = 5):
    """films[i] has genres, keywords, runtime_min, original_language. Returns (indices, relaxed, note)."""
    kb = moods()
    steps = [dict(widen=False, genres=True, mood=req.mood, language=True),
             dict(widen=True, genres=True, mood=req.mood, language=True),
             dict(widen=True, genres=False, mood=req.mood, language=True),
             dict(widen=True, genres=False, mood=kb[req.mood].get("nearest", req.mood), language=True),
             dict(widen=True, genres=False, mood=kb[req.mood].get("nearest", req.mood), language=False)]
    relaxed_names = [[], ["runtime"], ["runtime", "genres"], ["runtime", "genres", "mood"],
                     ["runtime", "genres", "mood", "language"]]
    for step, relaxed in zip(steps, relaxed_names):
        rule = kb[step["mood"]]
        ok = [i for i, f in enumerate(films)
              if matches_mood(f, rule)
              and runtime_ok(f, req.runtime, step["widen"])
              and (not step["genres"] or not req.genres or set(req.genres) & set(f["genres"]))
              and (not step["language"] or not req.language or f["original_language"] == req.language)]
        if len(ok) >= min_results or relaxed == relaxed_names[-1]:
            ok = sorted(ok, key=lambda i: -scores[i])[:k]
            return ok, relaxed, relaxation_note(req, relaxed)
    return [], relaxed_names[-1], None


def relaxation_note(req: Request, relaxed: list[str]) -> str | None:
    if not relaxed:
        return None
    what = []
    if "runtime" in relaxed and req.runtime:
        what.append(f"widened the runtime beyond {BAND_TEXT[req.runtime]}")
    if "genres" in relaxed and req.genres:
        what.append("dropped the genre filter")
    if "mood" in relaxed:
        what.append(f"used a mood close to {req.mood}")
    if "language" in relaxed and req.language:
        what.append("included other languages")
    return ("Not enough matches, so we " + ", ".join(what) + ".") if what else None