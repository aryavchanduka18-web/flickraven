"""Gemini tag follow-up: consensus, coverage, review agreement, budget counting, scale sample (synthetic, no network)."""
import numpy as np
import pandas as pd

from pipeline import gemini_tag_pilot as gp
from pipeline import gemini_tag_scale as gs


def t(mood=(), tone=None, pacing=None, themes=()):
    return {"mood": list(mood), "tone": tone, "pacing": pacing, "themes": list(themes), "gap": None, "dropped": 0}


def test_consensus_three_runs_two_of_three():
    c = gs.consensus([t(["dark", "tense"], "serious", "steady", ["revenge"]),
                      t(["dark", "gritty"], "serious", "slow-burn", ["revenge", "family"]),
                      t(["tense"], "mixed", "fast", ["family"])])
    assert c == {"mood": ["dark", "tense"], "themes": ["family", "revenge"], "tone": "serious", "pacing": None}


def test_consensus_two_runs_needs_both():
    c = gs.consensus([t(["dark"], "serious", "fast", ["love"]), t(["dark", "eerie"], "light", "fast", [])])
    assert c == {"mood": ["dark"], "themes": [], "tone": None, "pacing": "fast"}


def test_coverage():
    cons = {"a": gs.consensus([t(["dark"], themes=["love"])] * 2), "b": gs.consensus([t(["dark"])] * 2)}
    cv = gs.coverage(cons, ["a", "b"])
    assert cv["with_mood_and_theme"] == 0.5 and cv["empty_share"]["themes"] == 0.5 and cv["empty_share"]["tone"] == 1.0


def test_review_agreement():
    run1 = {"a": t(["dark", "tense"], "serious", "steady", ["revenge"]), "b": t(["funny"], "serious", "fast", ["ambition"])}
    cons = {"a": t(["dark"], "serious", "steady", ["revenge"]), "b": t(["funny"], "mixed", "fast", [])}
    labels = {"a": {"mood_ok": "r", "tone_ok": "r", "pacing_ok": "r", "themes_ok": "r"},
              "b": {"mood_ok": "r", "tone_ok": "w", "pacing_ok": "u", "themes_ok": "w"}}
    r = gs.review_agreement(run1, cons, labels)
    assert r["mood"] == {"judged_right": 2, "consensus_keeps_right": 1.0, "judged_wrong": 0, "consensus_changes_wrong": None}
    assert r["tone"]["consensus_changes_wrong"] == 1.0 and r["themes"]["consensus_changes_wrong"] == 1.0
    assert r["pacing"]["judged_right"] == 1                                   # unsure is ignored


def test_requests_in_counts_attempts_only():
    calls = [{"run": 3, "attempt": 1}, {"run": 3, "attempt": 2}, {"run": 1, "attempt": 1}, {"note": "x"}]
    assert gs.requests_in(calls) == 3 and gs.requests_in(calls, run=3) == 2


def test_scale_sample_excludes_hindi_and_pilot_films():
    rows = []
    rid = 1
    for lang in ("hi", "ta", "te", "ml", "ko", "ja", "en", "fr", "de"):
        for i in range(140):
            rows.append({"tmdb_id": rid, "title": f"{lang}{i}", "year": 1950 + i % 75, "overview": "x" * 60,
                         "original_language": lang, "title_type": "movie", "tmdb_vote_count": float(i),
                         "genres": np.array(["Drama"]), "keywords": np.array(["family"])})
            rid += 1
    m = pd.DataFrame(rows)
    pilot = {2 * 140 + 1, 2 * 140 + 2}                                       # two Telugu ids
    s = gs.build_scale_sample(m, pilot, seed=1)
    assert len(s) == sum(n for _, n in gs.SCALE_GROUPS.values()) and s.blind_id.is_unique
    assert "hi" not in set(s.original_language) and not set(s.tmdb_id) & pilot
    assert set(s[s.group == "world"].original_language) <= {"fr", "de"}


def test_review_400_is_stratified_and_blind(tmp_path):
    import csv
    rows = []
    for g, (langs, n) in gs.SCALE_GROUPS.items():
        for i in range(n):
            rows.append({"blind_id": f"{g}{i}", "tmdb_id": len(rows), "title": f"t{len(rows)}", "year": 1960 + i % 60,
                         "genres": ["Comedy", "Crime"] if i % 7 == 0 else ["Drama"], "plot": "p" * 500,
                         "original_language": (langs or ("fr",))[0], "group": g, "hard": i % 7 == 0,
                         "tmdb_vote_count": float(i), "decade": 1960, "keywords": []})
    s = pd.DataFrame(rows)
    cons = {b: {"mood": ["dark"], "tone": None, "pacing": "fast", "themes": []} for b in s.blind_id}
    r = gs.build_review_400(s, cons, seed=2)
    assert len(r) == 60 and r.groupby("group").size().to_dict() == gs.REVIEW_GROUPS
    path = tmp_path / "sheet.csv"
    gs.review_sheet_400(r, cons, path)
    out = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert len(out) == 60 and out[0]["blind_id"] == "R01"
    assert not set(out[0]) & {"original_language", "group", "tmdb_id", "scale_id"}
    assert out[0]["tone"] == "(none)" and out[0]["themes"] == "(none)" and len(out[0]["plot"]) == gp.PLOT_CHARS


def test_run_supports_extra_run_and_bigger_batches(tmp_path):
    s = pd.DataFrame({"blind_id": [f"S{i:03d}" for i in range(40)], "title": ["x"] * 40, "year": [2000] * 40,
                      "genres": [["Drama"]] * 40, "plot": ["p"] * 40})
    n = {"c": 0}

    def ask(body, key):
        n["c"] += 1
        return "m", {str(i): {"tone": "serious"} for i in range(1, 21)}, {}
    res = gp.run(s, "k", ask=ask, out=tmp_path, pause=0, runs=(1, 2), per_call=20)
    assert n["c"] == 4 and len(res["tags"]["run1"]) == 40
    n["c"] = 0
    res = gp.run(s, "k", ask=ask, out=tmp_path, pause=0, resume=True, runs=(3,), per_call=20, max_requests=1)
    assert n["c"] == 1 and res["stopped_early"]                              # budget respected
