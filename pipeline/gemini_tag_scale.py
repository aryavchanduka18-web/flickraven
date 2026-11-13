"""Gemini tags, offline follow-up to the 60-film pilot: consensus tagging and a 400-film non-Hindi run.

    python -m pipeline.gemini_tag_scale step1      # 1 extra tags-only run on the pilot's 60 films (6 calls)
    python -m pipeline.gemini_tag_scale sample2    # 400 non-Hindi films, stratified (no API call)
    python -m pipeline.gemini_tag_scale step2      # 2 tags-only runs on them, 20 films per call (40 calls)
    python -m pipeline.gemini_tag_scale evaluate   # consensus, coverage, agreement, report data (no API call)

Same tags-only prompt, vocabulary (not expanded), model and call rules as pipeline/gemini_tag_pilot.py. Hard budget:
80 Gemini requests for this follow-up (step 1 + step 2, counted from the call logs), stop after 3 failures in a row,
call log saved after every batch. Outputs: work/gemini-tag-pilot/ (run 3 added to tags.json) and
work/gemini-tag-pilot/scale/. Never touches artifacts/models/ai_similar_films.json, the database, Taste DNA or scoring.

Consensus: a mood or theme word is kept if it appears in at least 2 runs (3 runs: 2 of 3; 2 runs: both); tone and pacing
are kept if at least 2 runs give the same value; otherwise the field is empty (unknown).
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter

import numpy as np
import pandas as pd

from pipeline import gemini_tag_pilot as gp

SCALE = gp.OUT / "scale"
BUDGET = 80
STEP1_CAP = 12
SCALE_PER_CALL = 20
SCALE_SEED = 23
SCALE_GROUPS = {"other_indian": (("ta", "te", "ml"), 100), "korean": (("ko",), 60), "japanese": (("ja",), 60),
                "english": (("en",), 100), "world": (None, 80)}
LISTED = {"hi", "ta", "te", "ml", "ko", "ja", "en"}


# ----------------------------------------------------------------------------- pure helpers (tested)
def consensus(tag_runs: list) -> dict:
    """Words in >= 2 runs (both, when there are 2); tone/pacing need >= 2 identical votes; else empty."""
    need = 2 if len(tag_runs) >= 2 else 1
    out = {}
    for fam in gp.SET_FAMILIES:
        c = Counter(w for t in tag_runs for w in set(t.get(fam) or []))
        out[fam] = sorted(w for w, n in c.items() if n >= need)
    for fam in ("tone", "pacing"):
        best = Counter(t.get(fam) for t in tag_runs if t.get(fam)).most_common(1)
        out[fam] = best[0][0] if best and best[0][1] >= need else None
    return out


def coverage(cons: dict, ids) -> dict:
    ids = list(ids)
    return {"films": len(ids),
            "with_mood_and_theme": round(float(np.mean([bool(cons[i]["mood"]) and bool(cons[i]["themes"])
                                                        for i in ids])), 3) if ids else None,
            "empty_share": {f: round(float(np.mean([not cons[i][f] for i in ids])), 3) for f in gp.FAMILIES} if ids else {}}


def review_agreement(run1: dict, cons: dict, labels: dict) -> dict:
    """Against a reviewer's verdicts on RUN 1's tags: of families judged right, how often consensus keeps run 1's tag
    (sets: a non-empty subset of run 1); of families judged wrong, how often consensus changes or empties it."""
    out = {}
    for fam in gp.FAMILIES:
        kept, n_right, changed, n_wrong = 0, 0, 0, 0
        for i, lab in labels.items():
            v = (lab.get(f"{fam}_ok") or "").strip().lower()[:1]
            if i not in cons or v not in ("r", "w"):
                continue
            a, c = run1[i][fam], cons[i][fam]
            if fam in gp.SET_FAMILIES:
                same, differs = bool(c) and set(c) <= set(a or []), set(c) != set(a or [])
            else:
                same, differs = c is not None and c == a, c != a
            if v == "r":
                n_right += 1
                kept += same
            else:
                n_wrong += 1
                changed += differs
        out[fam] = {"judged_right": n_right, "consensus_keeps_right": round(kept / n_right, 3) if n_right else None,
                    "judged_wrong": n_wrong, "consensus_changes_wrong": round(changed / n_wrong, 3) if n_wrong else None}
    return out


def requests_in(calls: list, run=None) -> int:
    """HTTP requests in a call log (optionally one run only)."""
    return sum(1 for c in calls if "attempt" in c and (run is None or c.get("run") == run))


def build_scale_sample(movies: pd.DataFrame, exclude: set, seed: int = SCALE_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    m = movies[(movies.title_type == "movie") & movies.year.notna() & (movies.overview.fillna("").str.len() > 40)
               & ~movies.tmdb_id.isin(exclude)].copy()
    m["genres"] = [list(g) if g is not None else [] for g in m.genres]
    m["keywords"] = [list(k) if k is not None else [] for k in m.keywords]
    m["tmdb_vote_count"] = m.tmdb_vote_count.fillna(0)
    m["hard"] = [gp.is_hard(g, k) for g, k in zip(m.genres, m.keywords)]
    parts = []
    for group, (langs, n) in SCALE_GROUPS.items():
        pool = m[~m.original_language.isin(LISTED)] if langs is None else m[m.original_language.isin(langs)]
        p = gp.stratified_pick(pool, n, 0, rng)
        p["group"] = group
        parts.append(p)
    s = pd.concat(parts)
    s = s.iloc[rng.permutation(len(s))].reset_index(drop=True)
    s["blind_id"] = [f"S{i + 1:03d}" for i in range(len(s))]
    s["plot"] = s.overview.fillna("").str[:gp.PLOT_CHARS]
    return s[["blind_id", "tmdb_id", "title", "year", "genres", "plot", "original_language", "group", "hard",
              "tmdb_vote_count", "decade", "keywords"]]


# ----------------------------------------------------------------------------- steps
def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _key():
    from pipeline.common import env
    key = env("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing from .env")
    return key


def step1_requests() -> int:
    return requests_in(_read(gp.OUT / "calls.json", []), run=3)


def step2_requests() -> int:
    return requests_in(_read(SCALE / "calls.json", []))


def step1() -> dict:
    sample = pd.read_json(gp.OUT / "sample.json")
    res = gp.run(sample, _key(), resume=True, runs=(3,), pause=6, retry_pause=120, stop_after_failures=3,
                 max_requests=max(0, STEP1_CAP - step1_requests()))
    return {"requests_step1": step1_requests(), "stopped_early": res["stopped_early"]}


def step2() -> dict:
    sample = pd.read_json(SCALE / "sample.json")
    cap = BUDGET - step1_requests() - step2_requests()
    res = gp.run(sample, _key(), out=SCALE, resume=(SCALE / "tags.json").exists(), runs=(1, 2),
                 per_call=SCALE_PER_CALL, pause=6, retry_pause=120, stop_after_failures=3, max_requests=max(0, cap))
    return {"requests_step1": step1_requests(), "requests_step2": step2_requests(),
            "total": step1_requests() + step2_requests(), "budget": BUDGET, "stopped_early": res["stopped_early"]}


def evaluate() -> dict:
    from api.app.services.taste_dna import trait_evidence
    rep = {"budget": BUDGET, "requests_step1": step1_requests(), "requests_step2": step2_requests()}
    s1 = pd.read_json(gp.OUT / "sample.json")
    t = _read(gp.OUT / "tags.json", {})
    have = lambda tags, r, i: tags.get(f"run{r}", {}).get(i, {}).get("dropped", -1) != -1
    ids = [i for i in s1.blind_id if all(have(t, r, i) for r in (1, 2, 3))]
    cons1 = {i: consensus([t[f"run{r}"][i] for r in (1, 2, 3)]) for i in ids}
    labels = {}
    p = gp.OUT / "claude-review-labels.csv"
    if p.exists():
        with p.open(encoding="utf-8-sig") as fh:
            labels = {r["blind_id"]: r for r in csv.DictReader(fh)}
    calls1 = [c for c in _read(gp.OUT / "calls.json", []) if c.get("run") == 3]
    rep["step1"] = {"films_with_3_runs": len(ids), "consensus": coverage(cons1, ids),
                    "run1_only_empty_share": gp.abstention(t["run1"], ids) if ids else {},
                    "run3_vs_run1": gp.agreement(t["run1"], t["run3"], ids) if ids else {},
                    "run3_vs_run2": gp.agreement(t["run2"], t["run3"], ids) if ids else {},
                    "vs_claude_review_labels": review_agreement(t["run1"], cons1, labels) if labels else {},
                    "cost": gp.cost(calls1)}
    (gp.OUT / "consensus-3runs.json").write_text(json.dumps(cons1, indent=1, ensure_ascii=False), encoding="utf-8")
    t2 = _read(SCALE / "tags.json", None)
    if t2:
        s2 = pd.read_json(SCALE / "sample.json")
        ok = [i for i in s2.blind_id if all(have(t2, r, i) for r in (1, 2))]
        cons2 = {i: consensus([t2["run1"][i], t2["run2"][i]]) for i in ok}
        s2ok = s2[s2.blind_id.isin(ok)]
        gaps = [t2["run1"][i]["gap"] for i in ok if t2["run1"][i]["gap"]]
        rep["step2"] = {"films": len(s2), "films_with_2_runs": len(ok),
                        "repeatability": gp.agreement(t2["run1"], t2["run2"], ok) if ok else {},
                        "abstention_run1": gp.abstention(t2["run1"], ok) if ok else {},
                        "consensus": coverage(cons2, ok),
                        "gap_rate_run1": round(len(gaps) / max(len(ok), 1), 3), "gap_examples": gaps[:30],
                        "taste_dna_consistency_consensus": gp.taste_agreement(cons2, s2ok, trait_evidence) if ok else {},
                        "by_group": {}, "cost": gp.cost(_read(SCALE / "calls.json", []))}
        for grp, d in s2ok.groupby("group"):
            gi = list(d.blind_id)
            rep["step2"]["by_group"][grp] = {"films": len(gi), "repeatability": gp.agreement(t2["run1"], t2["run2"], gi),
                                             "consensus": coverage(cons2, gi)}
        (SCALE / "consensus-2runs.json").write_text(json.dumps(cons2, indent=1, ensure_ascii=False), encoding="utf-8")
    (gp.OUT / "followup-evaluation.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["step1", "sample2", "step2", "evaluate"])
    a = ap.parse_args()
    if a.step == "step1":
        print(json.dumps(step1(), indent=1))
    elif a.step == "sample2":
        from pipeline.common import PROCESSED
        SCALE.mkdir(parents=True, exist_ok=True)
        movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
        s = build_scale_sample(movies, set(pd.read_json(gp.OUT / "sample.json").tmdb_id))
        s.to_json(SCALE / "sample.json", orient="records", force_ascii=False, indent=1)
        print(s.groupby("group").agg(n=("blind_id", "size"), hard=("hard", "sum")).to_string())
    elif a.step == "step2":
        print(json.dumps(step2(), indent=1))
    else:
        print(json.dumps(evaluate(), indent=1, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
