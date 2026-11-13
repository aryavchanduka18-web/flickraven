"""Gemini tag pilot (tags only, 60 films, read-only for the site). Approved 2026-11-12 as a bounded pilot.

    python -m pipeline.gemini_tag_pilot sample        # build the 60-film manifest + blind mapping (no API call)
    python -m pipeline.gemini_tag_pilot run           # 2 runs x 6 batches of 10 = 12 Gemini calls (+ at most 1 retry each)
    python -m pipeline.gemini_tag_pilot evaluate      # automatic report data + blind review sheet (no API call)
    python -m pipeline.score_review                   # after the human review: correctness vs the pilot gate

Isolation: everything is written under work/gemini-tag-pilot/. Nothing here writes artifacts/models/ai_similar_films.json
or any file the site builds or deploys (it only READS the existing Hindi traits as historical controls); the similar-film
pipeline (pipeline/ai_similar_films.py) is unchanged. The fixed vocabularies are imported from it, never copied or
extended.

What is sent to Google: title, year, up to 4 genres and the first 350 characters of the TMDB plot. No user data.
Calls: one HTTP request per batch and model; a 404 (model not available) moves to the next model in
ai_similar.MODELS_TO_TRY; any other failure is NOT retried inside the call (the caller retries a failed batch once).
This differs from ai_similar.ask, which retries rate limits up to four times per model, because the pilot has a hard call
budget. Token usage comes from the API response (usageMetadata).

Pilot response rules (prefer empty or null to a confident wrong tag):
  mood    up to 3 words from the mood list, or []
  tone    one word from the tone list, or null
  pacing  one word from the pacing list, or null
  themes  up to 3 words from the theme list, or []
  gap     optional short text naming what the theme list cannot express, or null
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import ai_similar as base
from pipeline import ai_similar_films as films

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "gemini-tag-pilot"
PROMPT_VERSION = "tags-only-v1"
FAMILIES = ("mood", "tone", "pacing", "themes")
SET_FAMILIES = ("mood", "themes")
PLOT_CHARS = films.PLOT_CHARS
PER_CALL = 10
RUNS = 2
SEED = 11
GROUPS = {                         # group -> (languages, size); None = any language not listed
    "hindi_control": (("hi",), 12),
    "other_indian": (("ta", "te", "ml"), 10),
    "korean": (("ko",), 8),
    "japanese": (("ja",), 6),
    "english": (("en",), 14),
    "world": (None, 10),
}
LISTED = {"hi", "ta", "te", "ml", "ko", "ja", "en"}
HARD_KEYWORDS = {"dark comedy", "black comedy", "tragicomedy", "slow burn", "slow cinema", "satire", "absurdism",
                 "black humor", "neo-noir", "psychological thriller"}
HARD_TARGET = 10


def vocab_version() -> str:
    blob = json.dumps([films.MOODS, films.TONES, films.PACING, films.THEMES])
    return "ai_similar_films:" + hashlib.sha1(blob.encode()).hexdigest()[:10]


# ----------------------------------------------------------------------------- sample
def is_hard(genres, keywords) -> bool:
    """Deliberately hard cases: dark comedies, slow thrillers, mixed tone."""
    g = set(genres)
    kw = {k.lower() for k in keywords}
    mixed = "Comedy" in g and bool(g & {"Crime", "Thriller", "Horror", "War", "Drama"})
    return bool(kw & HARD_KEYWORDS) or mixed


def stratified_pick(df: pd.DataFrame, n: int, n_hard: int, rng) -> pd.DataFrame:
    """n rows spread over fame band (TMDB votes: top 10% / 50-90% / bottom half of the group) x decade x primary
    genre, taking the bands in turn; about n_hard flagged hard cases first."""
    df = df.copy()
    df["decade"] = (df.year // 10 * 10).astype(int)
    pct = df.tmdb_vote_count.rank(pct=True)
    df["fame"] = np.where(pct > 0.9, "top10", np.where(pct > 0.5, "mid", "obscure"))
    df["genre0"] = [g[0] if len(g) else "none" for g in df.genres]
    picked: list = []
    hard = df[df.hard]
    if n_hard and len(hard):
        picked += list(hard.sample(min(n_hard, len(hard)), random_state=int(rng.integers(1 << 31))).index)
    # fame first in the key so the round robin reaches every fame band early
    strata = {k: list(v.index) for k, v in df.drop(index=picked).groupby(["fame", "decade", "genre0"])}
    for k in strata:
        rng.shuffle(strata[k])
    bands = {}
    for k in strata:
        bands.setdefault(k[0], []).append(k)
    for b in bands.values():
        rng.shuffle(b)
    order = [k for trio in zip(*[bands.get(b, []) + [None] * 200 for b in ("top10", "mid", "obscure")])
             for k in trio if k is not None]                     # alternate fame bands
    while len(picked) < n and any(strata.values()):
        for k in order:
            if strata[k] and len(picked) < n:
                picked.append(strata[k].pop())
    return df.loc[picked]


def build_sample(movies: pd.DataFrame, controls: set, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    m = movies[(movies.title_type == "movie") & movies.year.notna() & (movies.overview.fillna("").str.len() > 40)].copy()
    m["genres"] = [list(g) if g is not None else [] for g in m.genres]
    m["keywords"] = [list(k) if k is not None else [] for k in m.keywords]
    m["tmdb_vote_count"] = m.tmdb_vote_count.fillna(0)
    m["hard"] = [is_hard(g, k) for g, k in zip(m.genres, m.keywords)]
    total = sum(n for _, n in GROUPS.values())
    parts = []
    for group, (langs, n) in GROUPS.items():
        if group == "hindi_control":
            pool = m[(m.original_language == "hi") & m.tmdb_id.astype(str).isin(controls)]
        elif langs is None:
            pool = m[~m.original_language.isin(LISTED)]
        else:
            pool = m[m.original_language.isin(langs)]
        p = stratified_pick(pool, n, max(1, round(n * HARD_TARGET / total)), rng)
        p["group"] = group
        parts.append(p)
    s = pd.concat(parts)
    s = s.iloc[rng.permutation(len(s))].reset_index(drop=True)
    s["blind_id"] = [f"P{i + 1:02d}" for i in range(len(s))]
    s["plot"] = s.overview.fillna("").str[:PLOT_CHARS]
    return s[["blind_id", "tmdb_id", "title", "year", "genres", "plot", "original_language", "group", "hard",
              "tmdb_vote_count", "decade", "keywords"]]


# ----------------------------------------------------------------------------- prompt, call, clean
def prompt(batch: list) -> str:
    lines = "\n".join(f'{n}. {b["title"]} ({int(b["year"])}) - {", ".join(list(b["genres"])[:4])}. {b["plot"]}'
                      for n, b in enumerate(batch, 1))
    return ("For each numbered film below, describe how it feels, using ONLY the words given. Answer with JSON only: an "
            "object whose keys are the numbers and whose values are objects with the keys mood, tone, pacing, themes, gap. "
            "Be conservative: if you are not sure, leave the field empty rather than guess. A wrong word is worse than "
            "no word.\n"
            '"mood": a list of 0 to 3 of: ' + ", ".join(films.MOODS) + ".\n"
            '"tone": exactly one of ' + ", ".join(films.TONES) + ", or null if none fits or you are unsure.\n"
            '"pacing": exactly one of ' + ", ".join(films.PACING) + ", or null if none fits or you are unsure.\n"
            '"themes": a list of 0 to 3 of: ' + ", ".join(films.THEMES) + ".\n"
            '"gap": null, or a short phrase (at most 8 words) naming an important theme of the film that the theme list '
            "above cannot express.\n\n" + lines)


def clean(raw) -> dict:
    """Valid words only; missing or invalid becomes [] or None. 'dropped' counts thrown-away words (-1 = no answer)."""
    out = {"mood": [], "tone": None, "pacing": None, "themes": [], "gap": None, "dropped": 0}
    if not isinstance(raw, dict):
        out["dropped"] = -1
        return out
    for key, allowed, limit in (("mood", films.MOODS, 3), ("themes", films.THEMES, 3)):
        v = raw.get(key)
        vals = v if isinstance(v, list) else ([v] if v else [])
        words = [x.strip().lower() for x in vals if isinstance(x, str)]
        good = list(dict.fromkeys(w for w in words if w in allowed))
        out["dropped"] += len([w for w in words if w not in allowed]) + max(0, len(good) - limit)
        out[key] = good[:limit]
    for key, allowed in (("tone", films.TONES), ("pacing", films.PACING)):
        v = raw.get(key)
        w = v.strip().lower() if isinstance(v, str) else None
        if w in allowed:
            out[key] = w
        elif w not in (None, "", "null", "none"):
            out["dropped"] += 1
    g = raw.get("gap")
    if isinstance(g, str) and g.strip() and g.strip().lower() not in ("null", "none", "n/a"):
        out["gap"] = " ".join(g.split())[:80]
    return out


def ask_once(body: dict, key: str, opener=urllib.request.urlopen) -> tuple:
    """(model that answered, parsed JSON, usageMetadata). One request per model; only a 404 moves to the next model."""
    for model in base.MODELS_TO_TRY:
        req = urllib.request.Request(base.URL.format(m=model), data=json.dumps(body).encode("utf-8"),
                                     headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            with opener(req, timeout=120) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise RuntimeError(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"network: {type(e).__name__}") from None
        text_ = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return model, json.loads(text_), data.get("usageMetadata", {})
    raise RuntimeError("no model answered")


def missing_batches(tags: dict, rows: list, runs=None, per_call: int = PER_CALL) -> set:
    """(run, batch start) pairs whose films have no answer yet (clean(None) marks an unanswered film with dropped -1)."""
    todo = set()
    for r in (runs or range(1, RUNS + 1)):
        got = tags.get(f"run{r}", {})
        for b in range(0, len(rows), per_call):
            if any(got.get(x["blind_id"], {"dropped": -1})["dropped"] == -1 for x in rows[b:b + per_call]):
                todo.add((r, b))
    return todo


def run(sample: pd.DataFrame, key: str, ask=ask_once, out: Path = OUT, pause: float = 6.0, resume: bool = False,
        retry_pause: float | None = None, stop_after_failures: int | None = None,
        max_requests: int | None = None, runs=None, per_call: int = PER_CALL) -> dict:
    """RUNS x ceil(n / PER_CALL) calls; a failed batch is retried once, never more. resume=True keeps earlier answers
    and calls, and asks only for the batches that have no answer yet (same budget: one call + one retry each)."""
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    runs = tuple(runs or range(1, RUNS + 1))
    tags = {f"run{r}": {} for r in runs}
    calls = []
    rows = sample.to_dict("records")
    if resume:
        tags = json.loads((out / "tags.json").read_text(encoding="utf-8"))
        calls = json.loads((out / "calls.json").read_text(encoding="utf-8"))
    for r in runs:
        tags.setdefault(f"run{r}", {})
    todo = missing_batches(tags, rows, runs, per_call)
    streak = 0                                     # consecutive failed requests (e.g. HTTP 503 overload)
    stopped = False
    sent = 0

    def save():                                    # after every batch, so a crash cannot lose the call log
        (out / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "calls.json").write_text(json.dumps(calls, indent=1), encoding="utf-8")
    for r in runs:
        for b in range(0, len(rows), per_call):
            if (r, b) not in todo or stopped:
                continue
            batch = rows[b:b + per_call]
            body = {"contents": [{"role": "user", "parts": [{"text": prompt(batch)}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4000,
                                         "responseMimeType": "application/json"}}
            for attempt in (1, 2):
                if max_requests is not None and sent >= max_requests:      # hard request budget
                    stopped = True
                    break
                sent += 1
                rec = {"run": r, "batch": b // per_call + 1, "attempt": attempt,
                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "prompt_version": PROMPT_VERSION, "vocab_version": vocab_version(),
                       "tier": "assumed free (same key as the Hindi run); not changed by the pilot"}
                try:
                    model, answer, usage = ask(body, key)
                    rec.update(model=model, usage=usage, ok=True)
                    (raw_dir / f"run{r}-batch{rec['batch']}.json").write_text(
                        json.dumps({"call": rec, "films": [x["blind_id"] for x in batch], "answer": answer},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
                    for n, x in enumerate(batch, 1):
                        item = answer.get(str(n)) if isinstance(answer, dict) else None
                        tags[f"run{r}"][x["blind_id"]] = clean(item)
                    calls.append(rec)
                    streak = 0
                    break
                except (RuntimeError, ValueError, KeyError, IndexError) as e:
                    rec.update(ok=False, error=str(e)[:120])
                    calls.append(rec)
                    streak += 1
                    if attempt == 2:
                        for x in batch:
                            tags[f"run{r}"][x["blind_id"]] = clean(None)
                    if stop_after_failures and streak >= stop_after_failures:
                        stopped = True
                        break
                    wait = pause if retry_pause is None else retry_pause
                    if wait and attempt == 1:
                        time.sleep(wait)
            if stopped:
                for x in batch:
                    tags[f"run{r}"].setdefault(x["blind_id"], clean(None))
            save()
            if pause and not stopped:
                time.sleep(pause)
    (out / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "calls.json").write_text(json.dumps(calls, indent=1), encoding="utf-8")
    return {"tags": tags, "calls": calls, "stopped_early": stopped}


# ----------------------------------------------------------------------------- evaluation
def jaccard(a, b) -> float:
    a, b = set(a or []), set(b or [])
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def agreement(t1: dict, t2: dict, ids) -> dict:
    """Exact match (tone, pacing); exact-set and mean Jaccard (mood, themes)."""
    ids = list(ids)
    out = {}
    for fam in FAMILIES:
        if fam in SET_FAMILIES:
            out[fam] = {"exact_set": round(float(np.mean([set(t1[i][fam]) == set(t2[i][fam]) for i in ids])), 3),
                        "jaccard": round(float(np.mean([jaccard(t1[i][fam], t2[i][fam]) for i in ids])), 3)}
        else:
            out[fam] = {"exact": round(float(np.mean([t1[i][fam] == t2[i][fam] for i in ids])), 3)}
    return out


def abstention(t: dict, ids) -> dict:
    ids = list(ids)
    return {fam: round(float(np.mean([not t[i][fam] for i in ids])), 3) for fam in FAMILIES}


TASTE_CHECKS = {   # Taste DNA trait -> pilot tag test, for the overlapping concepts only
    "dark": lambda t: bool({"dark", "gritty", "eerie"} & set(t["mood"])),
    "slow_burn": lambda t: t["pacing"] == "slow-burn",
    "fast": lambda t: t["pacing"] == "fast",
    "humour": lambda t: bool({"funny", "satirical"} & set(t["mood"])) or t["tone"] in ("light", "satirical"),
}


def taste_agreement(t: dict, sample: pd.DataFrame, evidence_fn, threshold: float = 1.0) -> dict:
    """Consistency check, NOT ground truth: where Taste DNA's keyword rules give the trait evidence >= threshold, how often
    the pilot tag agrees; where Taste DNA has no such evidence, how often the pilot claims the trait anyway."""
    out = {}
    for trait, test in TASTE_CHECKS.items():
        yes, no = [], []
        for x in sample.itertuples():
            ev = evidence_fn(list(x.keywords), list(x.genres)).get(trait, 0.0)
            (yes if ev >= threshold else no).append(test(t[x.blind_id]))
        out[trait] = {"taste_dna_says_yes": len(yes), "pilot_agrees": round(float(np.mean(yes)), 3) if yes else None,
                      "taste_dna_silent": len(no), "pilot_claims_anyway": round(float(np.mean(no)), 3) if no else None}
    return out


def historical(t: dict, sample: pd.DataFrame, old_traits: dict) -> dict:
    """Run 1 vs the existing combined-prompt Hindi traits. Different prompt, so a historical comparison, not
    repeatability."""
    old = {}
    for x in sample[sample.group == "hindi_control"].itertuples():
        o = old_traits.get(str(x.tmdb_id))
        if o:
            old[x.blind_id] = {"mood": o.get("mood", []), "tone": o.get("tone"), "pacing": o.get("pacing"),
                               "themes": o.get("themes", [])}
    return {"films": len(old), **(agreement(t, old, old) if old else {})}


def review_sheet(sample: pd.DataFrame, t: dict, path: Path) -> None:
    """Blind: no language, no group, no tmdb id. Right / wrong / unsure is filled in per tag family."""
    cols = ["blind_id", "title", "year", "genres", "plot", "mood", "tone", "pacing", "themes",
            "mood_ok", "tone_ok", "pacing_ok", "themes_ok", "comment"]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for x in sample.sort_values("blind_id").itertuples():
            g = t[x.blind_id]
            w.writerow([x.blind_id, x.title, int(x.year), ", ".join(list(x.genres)[:4]), x.plot,
                        ", ".join(g["mood"]) or "(none)", g["tone"] or "(none)", g["pacing"] or "(none)",
                        ", ".join(g["themes"]) or "(none)", "", "", "", "", ""])


def cost(calls: list, in_price: float = 0.30, out_price: float = 2.50) -> dict:
    """Token totals, and USD at gemini-3.5-flash-lite paid-tier list prices per million tokens (the run is assumed to be
    on the free tier, where the actual charge is 0)."""
    ok = [c for c in calls if c.get("ok")]
    tin = sum(int(c.get("usage", {}).get("promptTokenCount", 0)) for c in ok)
    tout = sum(int(c.get("usage", {}).get("candidatesTokenCount", 0)) + int(c.get("usage", {}).get("thoughtsTokenCount", 0))
               for c in ok)
    return {"input_tokens": tin, "output_tokens": tout,
            "usd_if_paid_list_price": round(tin / 1e6 * in_price + tout / 1e6 * out_price, 4),
            "calls_ok": len(ok), "calls_failed": len(calls) - len(ok),
            "models": sorted({c["model"] for c in ok})}


def evaluate(out: Path = OUT, evidence_fn=None, old_traits=None) -> dict:
    if evidence_fn is None:
        from api.app.services.taste_dna import trait_evidence as evidence_fn
    if old_traits is None:
        old_traits = json.loads(films.OUT.read_text(encoding="utf-8")).get("traits", {})      # read only
    sample = pd.read_json(out / "sample.json")
    tags = json.loads((out / "tags.json").read_text(encoding="utf-8"))
    calls = json.loads((out / "calls.json").read_text(encoding="utf-8"))
    t1, t2 = tags["run1"], tags["run2"]
    ids = list(sample.blind_id)
    rep = {"prompt_version": PROMPT_VERSION, "vocab_version": vocab_version(), "films": len(ids),
           "repeatability": agreement(t1, t2, ids),
           "abstention_run1": abstention(t1, ids), "abstention_run2": abstention(t2, ids),
           "gap_rate_run1": round(float(np.mean([t1[i]["gap"] is not None for i in ids])), 3),
           "gaps_run1": {i: t1[i]["gap"] for i in ids if t1[i]["gap"]},
           "gaps_run2": {i: t2[i]["gap"] for i in ids if t2[i]["gap"]},
           "dropped_words": {r: int(sum(max(tags[r][i]["dropped"], 0) for i in ids)) for r in ("run1", "run2")},
           "unanswered": {r: int(sum(tags[r][i]["dropped"] == -1 for i in ids)) for r in ("run1", "run2")},
           "taste_dna_consistency_run1": taste_agreement(t1, sample, evidence_fn),
           "historical_hindi_vs_run1": historical(t1, sample, old_traits),
           "by_group": {}, "cost": cost(calls)}
    for grp, d in sample.groupby("group"):
        gi = list(d.blind_id)
        rep["by_group"][grp] = {"films": len(gi), "repeatability": agreement(t1, t2, gi),
                                "abstention_run1": abstention(t1, gi),
                                "gap_rate_run1": round(float(np.mean([t1[i]["gap"] is not None for i in gi])), 3)}
    hard = list(sample[sample.hard].blind_id)
    rep["hard_cases"] = {"films": len(hard), "repeatability": agreement(t1, t2, hard) if hard else {},
                         "abstention_run1": abstention(t1, hard) if hard else {}}
    (out / "evaluation.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    review_sheet(sample, t1, out / "review-sheet.csv")
    return rep


# ----------------------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "run", "evaluate"])
    ap.add_argument("--resume", action="store_true", help="run: ask only for batches that have no answer yet")
    ap.add_argument("--max-requests", type=int, default=None, help="run --resume: hard cap on HTTP requests")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.step == "sample":
        from pipeline.common import PROCESSED
        movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
        controls = set(json.loads(films.OUT.read_text(encoding="utf-8")).get("traits", {}))   # read only
        s = build_sample(movies, controls)
        s.to_json(OUT / "sample.json", orient="records", force_ascii=False, indent=1)
        s[["blind_id", "tmdb_id", "original_language", "group", "hard", "tmdb_vote_count", "decade"]].to_csv(
            OUT / "mapping-HIDDEN-until-review.csv", index=False)
        print(s.groupby("group").agg(n=("blind_id", "size"), hard=("hard", "sum")).to_string())
    elif a.step == "run":
        from pipeline.common import env
        key = env("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY is missing from .env")
        if (OUT / "tags.json").exists() and not a.resume:
            raise SystemExit("tags.json exists: the pilot already ran. Use --resume (approved reruns only) for missing batches.")
        if a.resume:     # approved rerun: space requests minutes apart, stop after 3 failures in a row
            res = run(pd.read_json(OUT / "sample.json"), key, resume=True, pause=90, retry_pause=300,
                      stop_after_failures=3, max_requests=a.max_requests)
        else:
            res = run(pd.read_json(OUT / "sample.json"), key)
        print(json.dumps({**cost(res["calls"]), "stopped_early": res["stopped_early"],
                          "batches_still_missing": len(missing_batches(res["tags"],
                                                                       pd.read_json(OUT / "sample.json").to_dict("records")))},
                         indent=1))
    else:
        print(json.dumps(evaluate(), indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
