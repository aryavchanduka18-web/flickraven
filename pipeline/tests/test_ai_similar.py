"""The Gemini batch script: UTF-8 saving (Windows), reading an old cp1252 file, and retry on rate limits."""
import io
import json
import urllib.error

import pytest

from pipeline import ai_similar as A


def test_save_and_load_handle_non_ascii_names(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "OUT", tmp_path / "ai_similar.json")
    A.save({"titles": {"1": ["Mağlup (2020)", "Café Society (2016)"]}})
    assert A.load()["titles"]["1"][0] == "Mağlup (2020)"
    (tmp_path / "ai_similar.json").write_bytes(json.dumps({"titles": {"2": ["Café (2001)"]}}, ensure_ascii=False).encode("cp1252"))
    assert A.load()["titles"]["2"] == ["Café (2001)"]       # a file written by the old Windows run still loads


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b'{"error": {"message": "slow down"}}'))


class Ok:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, *a): return json.dumps({"candidates": [{"content": {"parts": [{"text": '{"1": ["A (2020)"]}'}]}}]}).encode()


def test_rate_limit_and_server_errors_wait_and_retry_then_succeed(monkeypatch):
    seq = [http_error(429), http_error(503), Ok()]
    waits = []
    monkeypatch.setattr(A.time, "sleep", waits.append)

    def fake_open(req, timeout=0):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(A.urllib.request, "urlopen", fake_open)
    i, answer = A.ask({"contents": []}, "key", 0)
    assert i == 0 and answer == {"1": ["A (2020)"]} and waits == [30, 15]


def test_a_quota_that_never_clears_stops_the_run(monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    monkeypatch.setattr(A.urllib.request, "urlopen", lambda req, timeout=0: (_ for _ in ()).throw(http_error(429)))
    with pytest.raises(RuntimeError, match="quota"):
        A.ask({"contents": []}, "key", 0)


def test_film_traits_keep_only_words_from_the_fixed_lists():
    from pipeline import ai_similar_films as F
    got = F.clean_traits({"mood": ["Dark", "made-up", "tense", "gritty", "eerie"], "tone": "serious", "pacing": ["slow-burn"],
                          "themes": ["revenge", "aliens"]})
    assert got == {"mood": ["dark", "tense", "gritty"], "tone": "serious", "pacing": "slow-burn", "themes": ["revenge"]}
    assert F.clean_traits({"mood": ["nonsense"], "tone": 5}) is None and F.clean_traits("x") is None


def test_film_file_is_separate_and_resumes(tmp_path, monkeypatch):
    from pipeline import ai_similar_films as F
    monkeypatch.setattr(F, "OUT", tmp_path / "ai_similar_films.json")
    assert F.load() == {"titles": {}, "traits": {}}
    F.save({"titles": {"1": ["Café (2001)"]}, "traits": {"1": {"tone": "light"}}})
    assert F.load()["titles"]["1"] == ["Café (2001)"]
