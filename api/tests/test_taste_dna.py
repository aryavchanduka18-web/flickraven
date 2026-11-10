"""Taste DNA: trait rules, provenance, the profile maths, and the API (tags, profile, overrides)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services import taste_dna as dna

MEAN = {t.key: 0.2 for t in dna.TRAITS}


def kw(*names):
    return list(names)


def test_vector_is_unknown_without_enough_keywords():
    assert dna.vector(["murder"], ["Crime"]) is None                       # too thin: unknown, never zero
    v = dna.vector(["plot twist", "murder", "whodunit"], ["Mystery"])
    assert v["twists"] > 0.8 and v["mystery"] > 0.9 and v["humour"] == 0.0
    assert "dialogue" not in v                                              # no keyword rule: only viewer tags can fill it


def test_viewer_tags_need_several_users():
    base = dict(names=["a", "b", "c"], genres=[])
    assert "dialogue" not in dna.vector(**base, viewer={"dialogue": 2})
    assert dna.vector(**base, viewer={"dialogue": 3})["dialogue"] > 0.7
    assert dna.vector([], [], {"dialogue": 3}) is not None                  # viewer tags alone are enough evidence


def vec(**kw_):
    return {k: kw_.get(k, 0.0) for k in MEAN}


def test_one_title_does_not_dominate_but_five_do():
    one = dna.Signals(weights={1: 1.0})
    p1 = dna.build_profile(one, {1: vec(slow_burn=0.9)}, MEAN)
    assert "slow_burn" not in p1.preferred()                                # 1 title: below MIN_EVIDENCE
    five = dna.Signals(weights={i: 1.0 for i in range(1, 6)})
    p5 = dna.build_profile(five, {i: vec(slow_burn=0.9) for i in range(1, 6)}, MEAN)
    assert p5.preferred()[0] == "slow_burn" and p5.lean("slow_burn") > p1.lean("slow_burn")


def test_negative_preferences_are_kept_separate():
    sig = dna.Signals(weights={**{i: 1.0 for i in range(1, 6)}, **{i: -1.0 for i in range(6, 10)}})
    vectors = {**{i: vec(fast=0.9) for i in range(1, 6)}, **{i: vec(violence=0.9) for i in range(6, 10)}}
    p = dna.build_profile(sig, vectors, MEAN)
    assert "fast" in p.preferred() and "violence" in p.avoided() and "violence" not in p.preferred()
    s_fast, because = dna.fit(p, vec(fast=0.9))
    s_viol, _ = dna.fit(p, vec(violence=0.9))
    assert s_fast > 0 > s_viol and because == ["fast"]


def test_tags_count_and_overrides_win():
    sig = dna.Signals(tags=[(1, "slow_burn"), (2, "slow_burn"), (3, "too_slow")], weights={1: 1.0, 2: 1.0, 3: -1.0})
    p = dna.build_profile(sig, {}, MEAN)
    assert p.n_like["slow_burn"] == 2 and p.n_dislike["slow_burn"] == 1
    sig.overrides = {"humour": "more", "slow_burn": "less"}
    p = dna.build_profile(sig, {}, MEAN)
    assert "humour" in p.preferred() and "slow_burn" not in p.preferred() and "slow_burn" in p.avoided()


def test_reason_and_personality_only_from_evidence():
    assert dna.reason([]) is None
    assert "complex, layered plots and sharp" not in dna.reason(["complexity"])
    sig = dna.Signals(weights={i: 1.0 for i in range(1, 4)})
    p = dna.build_profile(sig, {i: vec(complexity=0.9) for i in range(1, 4)}, MEAN)
    assert dna.personality(p, ["Drama"], ["English"]) is None               # fewer than 5 titles: no personality
    sig = dna.Signals(weights={i: 1.0 for i in range(1, 7)})
    p = dna.build_profile(sig, {i: vec(complexity=0.9) for i in range(1, 7)}, MEAN)
    out = dna.personality(p, ["Drama", "Thriller"], ["English"])
    assert "complex, layered plots" in out and "Drama and Thriller" in out


@pytest.fixture()
def titles(test_engine):
    ids = []
    with test_engine.begin() as conn:
        for i, (name, kws, genre) in enumerate([
                ("Slow Mystery", ["slow burn", "whodunit", "psychological"], "Mystery"),
                ("Quiet Dread", ["slow burn", "dread", "psychological thriller"], "Thriller"),
                ("Cold Case", ["slow burn", "grim", "investigation"], "Mystery"),
                ("Dark Twist", ["plot twist", "dark", "murder"], "Thriller"),
                ("Funny Film", ["hilarious", "witty", "parody"], "Comedy"),
                ("Loud Chase", ["car chase", "explosion", "heist"], "Action")]):
            mid = conn.execute(text("INSERT INTO movies (tmdb_id, title, year, original_language) VALUES (:t, :n, 2000, 'en') RETURNING id"),
                               {"t": 970000 + i, "n": name}).scalar()
            ids.append(mid)
            gid = conn.execute(text("""INSERT INTO genres (name, slug) VALUES (:g, lower(:g))
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"""), {"g": genre}).scalar()
            conn.execute(text("INSERT INTO movie_genres (movie_id, genre_id) VALUES (:m, :g)"), {"m": mid, "g": gid})
            for k in kws:
                kid = conn.execute(text("INSERT INTO keywords (name) VALUES (:k) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"),
                                   {"k": k}).scalar()
                conn.execute(text("INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (:m, :k)"), {"m": mid, "k": kid})
    dna._MEAN_CACHE["mean"] = None
    yield ids
    dna._MEAN_CACHE["mean"] = None
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})


def test_api_tags_profile_and_overrides(titles):
    slow, quiet, cold, twist, funny, chase = titles
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        assert c.get("/api/me/taste-dna").json()["ready"] is False
        # tags need an opinion first
        assert c.put(f"/api/feedback/tags/{slow}", json={"tags": ["slow_burn"]}).status_code == 409
        r = c.put(f"/api/ratings/{slow}", json={"rating": 9})
        assert r.status_code == 200, r.text
        for m in (quiet, cold):
            assert c.put(f"/api/ratings/{m}", json={"rating": 9}).status_code == 200
        assert c.put(f"/api/feedback/tags/{slow}", json={"tags": ["slow_burn", "psychological_tension", "slow_burn"]}).json()["tags"] \
            == ["slow_burn", "psychological_tension"]
        assert c.put(f"/api/feedback/tags/{slow}", json={"tags": ["nonsense"]}).status_code == 422
        assert c.get(f"/api/feedback/tags/{slow}").json()["tags"] == ["psychological_tension", "slow_burn"]
        body = c.get("/api/me/taste-dna").json()
        assert body["ready"] and body["titles_used"] == 3 and body["titles_tagged"] == 1
        assert "slow_burn" in body["preferred"] or "psychological" in body["preferred"]
        assert body["traits"][0]["source"] == "keywords" and body["personality"] is None   # 3 titles < 5
        assert c.put("/api/me/taste-dna/overrides", json={"overrides": {"humour": "more"}}).json()["overrides"] == {"humour": "more"}
        assert "humour" in c.get("/api/me/taste-dna").json()["preferred"]
        assert c.put("/api/me/taste-dna/overrides", json={"overrides": {"humour": None}}).json()["overrides"] == {}
        assert c.put("/api/me/taste-dna/overrides", json={"overrides": {"bogus": "more"}}).status_code == 422


def test_tags_are_private_and_deleted_with_the_account(titles):
    slow = titles[0]
    with TestClient(app) as a, TestClient(app) as b:
        a.post("/api/auth/guest"); b.post("/api/auth/guest")
        assert a.put(f"/api/ratings/{slow}", json={"rating": 8}).status_code == 200
        a.put(f"/api/feedback/tags/{slow}", json={"tags": ["slow_burn"]})
        assert b.get(f"/api/feedback/tags/{slow}").json()["tags"] == []


def test_catalog_mean_in_sql_matches_the_python_rules(titles, test_engine):
    """The database computes the catalog averages; they must agree with vector() title by title."""
    from app.db import SessionLocal
    with SessionLocal() as db:
        mean, coverage = dna.catalog_mean(db)
        ids = [r[0] for r in db.execute(text("SELECT movie_id FROM movie_keywords GROUP BY movie_id HAVING count(*) >= 3"))]
        vecs = [v for v in dna.title_vectors(db, ids).values() if v]
    assert vecs
    for k in mean:
        if k == "dialogue":
            continue
        assert mean[k] == pytest.approx(sum(v[k] for v in vecs) / len(vecs), abs=1e-3), k
        assert coverage[k] == pytest.approx(sum(v[k] >= 0.5 for v in vecs) / len(vecs), abs=1e-3), k
