"""Gemini tag pilot: isolation, sampling, cleaning, call budget, evaluation and review scoring (synthetic, no network)."""
import csv
import hashlib
import io
import json
import urllib.error

import numpy as np
import pandas as pd
import pytest

from pipeline import ai_similar_films as films
from pipeline import gemini_tag_pilot as gp
from pipeline import score_review as sr


def _movies(n_per_lang=40):
    rows = []
    rid = 1
    for lang in ("hi", "ta", "te", "ml", "ko", "ja", "en", "fr", "it"):
        for i in range(n_per_lang):
            rows.append({"tmdb_id": rid, "title": f"{lang} film {i}", "year": 1950 + (i * 7) % 75,
                         "overview": "A long enough plot about people and places and what happens to them.",
                         "original_language": lang, "title_type": "movie", "tmdb_vote_count": float(10 + i * 37),
                         "genres": np.array(["Comedy", "Crime"] if i % 9 == 0 else ["Drama"]),
                         "keywords": np.array(["slow burn"] if i % 11 == 0 else ["family"])})
            rid += 1
    return pd.DataFrame(rows)


def test_outputs_are_isolated_from_the_site_artifacts():
    assert gp.OUT.parts[-2:] == ("work", "gemini-tag-pilot")
    assert "artifacts" not in gp.OUT.parts
    assert gp.OUT != films.OUT.parent and films.OUT.name == "ai_similar_films.json"


def test_build_sample_sizes_groups_and_blind_ids():
    m = _movies()
    controls = {str(t) for t in m[m.original_language == "hi"].tmdb_id[:20]}
    s = gp.build_sample(m, controls, seed=3)
    assert len(s) == 60 and s.blind_id.is_unique
    assert s.groupby("group").size().to_dict() == {g: n for g, (_, n) in gp.GROUPS.items()}
    assert set(s[s.group == "hindi_control"].tmdb_id.astype(str)) <= controls
    assert set(s[s.group == "world"].original_language) <= {"fr", "it"}
    assert s.hard.sum() >= 6
    s2 = gp.build_sample(m, controls, seed=3)
    assert s.tmdb_id.tolist() == s2.tmdb_id.tolist()                    # fixed seed, reproducible


def test_clean_allows_abstention_and_drops_invalid_words():
    c = gp.clean({"mood": ["dark", "Tense", "spooky", "eerie", "funny"], "tone": "unsure", "pacing": None,
                  "themes": [], "gap": "  caste and land  "})
    assert c["mood"] == ["dark", "tense", "eerie"] and c["tone"] is None and c["pacing"] is None
    assert c["themes"] == [] and c["gap"] == "caste and land"
    assert c["dropped"] == 1 + 1 + 1                                    # spooky, 4th valid mood, invalid tone
    assert gp.clean(None)["dropped"] == -1
    assert gp.clean({"tone": "null", "gap": "none"}) == {"mood": [], "tone": None, "pacing": None, "themes": [],
                                                          "gap": None, "dropped": 0}


def test_prompt_lists_only_the_existing_vocabularies():
    p = gp.prompt([{"title": "X", "year": 2001, "genres": ["Drama"], "plot": "p"}])
    for w in films.THEMES + films.MOODS:
        assert w in p
    assert '"similar"' not in p and "or null" in p


def test_ask_once_falls_back_only_on_404_and_records_usage():
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        seen.append(req.full_url)
        if len(seen) == 1:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        body = {"candidates": [{"content": {"parts": [{"text": '{"1": {"tone": "light"}}'}]}}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20}}
        return Resp(json.dumps(body).encode())

    model, ans, usage = gp.ask_once({}, "k", opener=opener)
    assert model == gp.base.MODELS_TO_TRY[1] and ans == {"1": {"tone": "light"}} and usage["promptTokenCount"] == 100

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)
    with pytest.raises(RuntimeError):
        gp.ask_once({}, "k", opener=refuse)                               # no silent retries


def test_run_respects_the_call_budget_and_never_touches_the_artifact(tmp_path):
    m = _movies()
    s = gp.build_sample(m, {str(t) for t in m[m.original_language == "hi"].tmdb_id[:20]}, seed=1)
    before = hashlib.sha256(films.OUT.read_bytes()).hexdigest() if films.OUT.exists() else None
    calls = {"n": 0}

    def fake_ask(body, key):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("HTTP 500")                                 # one failure -> exactly one retry
        return "gemini-3.5-flash-lite", {str(i): {"mood": ["dark"], "tone": "serious", "pacing": "steady",
                                                  "themes": ["family"]} for i in range(1, 11)}, {"promptTokenCount": 10}

    res = gp.run(s, "key", ask=fake_ask, out=tmp_path, pause=0)
    assert calls["n"] == gp.RUNS * 6 + 1
    assert len(res["tags"]["run1"]) == len(res["tags"]["run2"]) == 60
    assert (tmp_path / "tags.json").exists() and len(list((tmp_path / "raw").glob("*.json"))) == 12
    after = hashlib.sha256(films.OUT.read_bytes()).hexdigest() if films.OUT.exists() else None
    assert before == after                                                 # old output file untouched


def test_resume_asks_only_for_missing_batches_and_stops_on_repeated_failures(tmp_path):
    m = _movies()
    s = gp.build_sample(m, {str(t) for t in m[m.original_language == "hi"].tmdb_id[:20]}, seed=1)
    good = ("gemini-3.5-flash-lite", {str(i): {"tone": "serious"} for i in range(1, 11)}, {})
    state = {"n": 0}

    def flaky(body, key):                       # first run: batches 3-6 of each run fail twice
        state["n"] += 1
        text = body["contents"][0]["parts"][0]["text"]
        if any(f"{b} film" in text for b in ()) or state["n"] in range(5, 30):
            raise RuntimeError("HTTP 503")
        return good

    gp.run(s, "k", ask=flaky, out=tmp_path, pause=0)
    tags = json.loads((tmp_path / "tags.json").read_text(encoding="utf-8"))
    missing = gp.missing_batches(tags, s.to_dict("records"))
    assert missing and len(missing) < 12
    asked = {"n": 0}

    def ok(body, key):
        asked["n"] += 1
        return good

    res = gp.run(s, "k", ask=ok, out=tmp_path, pause=0, resume=True)
    assert asked["n"] == len(missing) and not gp.missing_batches(res["tags"], s.to_dict("records"))
    assert len(res["calls"]) > asked["n"]                                   # earlier calls kept in the log

    def down(body, key):
        raise RuntimeError("HTTP 503")
    (tmp_path / "tags.json").write_text(json.dumps(tags), encoding="utf-8")
    hits = {"n": 0}

    def counting_down(body, key):
        hits["n"] += 1
        return down(body, key)
    res = gp.run(s, "k", ask=counting_down, out=tmp_path, pause=0, resume=True, stop_after_failures=3)
    assert res["stopped_early"] and hits["n"] == 3


def test_agreement_abstention_and_taste_consistency():
    t1 = {"a": {"mood": ["dark"], "tone": "serious", "pacing": None, "themes": ["family", "love"]},
          "b": {"mood": [], "tone": "light", "pacing": "fast", "themes": []}}
    t2 = {"a": {"mood": ["dark", "tense"], "tone": "serious", "pacing": None, "themes": ["family", "love"]},
          "b": {"mood": [], "tone": "mixed", "pacing": "fast", "themes": []}}
    a = gp.agreement(t1, t2, ["a", "b"])
    assert a["tone"]["exact"] == 0.5 and a["pacing"]["exact"] == 1.0
    assert a["mood"]["exact_set"] == 0.5 and a["mood"]["jaccard"] == pytest.approx(0.75)
    assert gp.abstention(t1, ["a", "b"]) == {"mood": 0.5, "tone": 0.0, "pacing": 0.5, "themes": 0.5}
    sample = pd.DataFrame({"blind_id": ["a", "b"], "keywords": [["dark"], []], "genres": [["Drama"], ["Comedy"]]})
    ev = lambda kw, g: {"dark": 1.5} if "dark" in kw else ({"humour": 1.0} if "Comedy" in g else {})
    c = gp.taste_agreement(t1, sample, ev)
    assert c["dark"]["pilot_agrees"] == 1.0 and c["humour"]["pilot_agrees"] == 1.0


def test_review_sheet_is_blind(tmp_path):
    s = pd.DataFrame({"blind_id": ["P02", "P01"], "title": ["B", "A"], "year": [2000, 1990], "genres": [["Drama"]] * 2,
                      "plot": ["p", "q"], "original_language": ["hi", "en"], "group": ["hindi_control", "english"]})
    t = {i: {"mood": [], "tone": None, "pacing": "fast", "themes": ["love"]} for i in ("P01", "P02")}
    path = tmp_path / "sheet.csv"
    gp.review_sheet(s, t, path)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert [r["blind_id"] for r in rows] == ["P01", "P02"]
    assert not set(rows[0]) & {"original_language", "group", "tmdb_id", "language"}
    assert rows[0]["mood"] == "(none)" and rows[0]["pacing"] == "fast"


def test_score_review_gate_and_groups():
    sheet = [{"blind_id": f"P{i}", "mood_ok": "right", "tone_ok": "r" if i < 9 else "w", "pacing_ok": "unsure",
              "themes_ok": "" if i == 0 else "wrong"} for i in range(10)]
    mapping = {f"P{i}": {"group": "english" if i < 5 else "korean"} for i in range(10)}
    ev = {"repeatability": {"mood": {"jaccard": 0.9}, "tone": {"exact": 0.85}, "pacing": {"exact": 0.9},
                            "themes": {"jaccard": 0.5}}}
    res = sr.score(sheet, mapping, ev)
    f = res["families"]
    assert f["mood"]["correctness"] == 1.0 and f["mood"]["passes_gate"]
    assert f["tone"]["correctness"] == 0.9 and f["tone"]["passes_gate"]
    assert f["pacing"]["correctness"] is None and not f["pacing"]["passes_gate"] and f["pacing"]["unsure"] == 10
    assert f["themes"]["correctness"] == 0.0 and f["themes"]["not_reviewed"] == 1
    assert set(res["by_group"]) == {"english", "korean"} and not res["all_families_pass"]
    assert "pilot gate" in sr.to_markdown(res)
