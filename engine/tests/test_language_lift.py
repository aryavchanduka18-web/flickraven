"""New users see films in their onboarding languages first (language_lift)."""
from types import SimpleNamespace

import numpy as np
import scipy.sparse as sp

import cinematch_engine.online as online_module
from cinematch_engine.online import OnlineEngine, UserState
from cinematch_engine.sources import SOURCES


def lift(langs, behavioral, film_langs=("en", "hi", "ta", "en")):
    fake = SimpleNamespace(cat=SimpleNamespace(language=list(film_langs)))
    st = UserState(languages=list(langs), behavioral_count=behavioral)
    scores = {"popularity": np.full(len(film_langs), 7.0, dtype=np.float32), "content": np.zeros(len(film_langs))}
    return OnlineEngine.language_lift(fake, st, scores)


def test_cold_user_who_picked_hindi_gets_hindi_lifted_only():
    out = lift(["hi"], 0)
    assert np.allclose(out["popularity"], [7.0, 8.2, 7.0, 7.0])
    assert out["content"].tolist() == [0, 0, 0, 0]          # other sources untouched


def test_lift_fades_with_feedback():
    assert np.isclose(lift(["hi"], 5)["popularity"][1], 7.6)   # warming: half
    assert lift(["hi"], 20)["popularity"][1] == np.float32(7.0)  # established: none


def test_english_gets_half_when_picked_with_another_language():
    out = lift(["en", "hi"], 0)["popularity"]
    assert out[1] > out[0] > 7.0


def test_no_languages_no_change():
    scores = {"popularity": np.ones(4, dtype=np.float32)}
    fake = SimpleNamespace(cat=SimpleNamespace(language=["en"] * 4))
    assert OnlineEngine.language_lift(fake, UserState(), scores) is scores


def test_explicit_language_preference_persists_for_established_candidate_retrieval():
    fake = SimpleNamespace(cat=SimpleNamespace(language=["en", "hi", "ta", "en"]))
    st = UserState(languages=["en", "hi"], behavioral_count=20)
    scores = {"popularity": np.full(4, 7.0, dtype=np.float32), "content": np.zeros(4)}

    out = OnlineEngine.persistent_language_candidate_scores(fake, st, scores)

    assert np.allclose(out["popularity"], [8.2, 9.4, 7.0, 8.2])
    assert out["content"] is scores["content"]


def test_explicit_language_preference_bonus_is_established_only_and_reportable():
    fake = SimpleNamespace(cat=SimpleNamespace(language=["en", "hi", "ta", "en"]))
    established = UserState(languages=["hi"], behavioral_count=20)
    warming = UserState(languages=["hi"], behavioral_count=5)

    assert np.allclose(OnlineEngine.persistent_language_bonus(fake, established, np.arange(4)), [0, .24, 0, 0])
    assert np.allclose(OnlineEngine.persistent_language_bonus(fake, warming, np.arange(4)), [0, 0, 0, 0])


def test_top_picks_uses_saved_language_for_retrieval_and_ranking_without_changing_match_score(monkeypatch):
    captured_popularity = []

    def fake_candidate_pool(scores, excluded):
        captured_popularity.append(scores["popularity"][0].copy())
        norm = np.zeros((len(SOURCES), 1, 3), dtype=np.float32)
        norm[SOURCES.index("popularity"), 0] = [0.9, 0.8, 0.7]
        return np.array([[0, 1, 2]], dtype=np.int64), norm

    monkeypatch.setattr(online_module, "candidate_pool", fake_candidate_pool)
    fake = SimpleNamespace(
        cat=SimpleNamespace(
            language=["en", "hi", "ta"],
            content=sp.identity(3, format="csr", dtype=np.float32),
            novelty=np.zeros(3, dtype=np.float32),
            fame_pct=np.full(3, 90.0, dtype=np.float32),
        ),
        weights={"established": {"popularity": 1.0}},
        availability=None,
        excluded=lambda st: np.array([], dtype=np.int64),
        onboarding_constraint=lambda st: np.array([], dtype=np.int64),
        language_lift=lambda st, scores: OnlineEngine.language_lift(fake, st, scores),
        persistent_language_candidate_scores=lambda st, scores: OnlineEngine.persistent_language_candidate_scores(fake, st, scores),
        persistent_language_bonus=lambda st, rows: OnlineEngine.persistent_language_bonus(fake, st, rows),
        rail_scores=lambda st, scores: np.array([5.0, 6.0, 7.0], dtype=np.float32),
        match=lambda stage, score: int(round(score * 10)),
    )
    scores = {name: np.full(3, -np.inf, dtype=np.float32) for name in SOURCES}
    scores["popularity"] = np.full(3, 8.0, dtype=np.float32)

    without_preference = OnlineEngine.top_picks(fake, UserState(behavioral_count=20), mode="familiar", k=2, scores=scores)
    with_preference = OnlineEngine.top_picks(
        fake, UserState(behavioral_count=20, languages=["hi"]), mode="familiar", k=2, scores=scores
    )

    assert np.allclose(captured_popularity[0], [8.0, 8.0, 8.0])
    assert np.allclose(captured_popularity[1], [8.0, 10.4, 8.0])
    assert with_preference[0]["row"] == 1
    assert with_preference[0]["shares"]["language_preference"] > 0
    assert {p["row"]: p["match_pct"] for p in without_preference} == {
        p["row"]: p["match_pct"] for p in with_preference
    }
