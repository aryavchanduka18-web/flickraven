"""The "New Releases For You" row: films only, last three years, one title per page, never Top Picks."""
import numpy as np

from app.services import recent_row as rr


class Cat:
    def __init__(self, years, kinds):
        self.year = np.array(years, dtype=float)
        self.kind = np.array(kinds, dtype=object)


def world(n=30):
    years = [2026, 2025, 2024, 2023, 2010] * (n // 5)
    kinds = ["movie", "movie", "movie", "series", "movie"] * (n // 5)
    return Cat(years, kinds), np.linspace(1.0, 0.0, n)


def test_only_recent_films_best_first():
    cat, scores = world()
    row = rr.recent_rail(cat, scores, set(), set(), 2026)
    assert row["key"] == "recent_for_you" and row["title"] == "New Releases For You"
    rows = row["rows"]
    assert len(rows) == 18 and rows == sorted(rows)                   # all qualifying films (3 of every 5), best score first
    assert all(cat.year[r] >= 2024 and cat.kind[r] == "movie" for r in rows)   # 2026, 2025, 2024 only; no series, no 2023


def test_never_repeats_a_title_from_another_row_and_respects_hidden_titles():
    cat, scores = world()
    base = rr.recent_rail(cat, scores, set(), set(), 2026)["rows"]
    row = rr.recent_rail(cat, scores, set(base[:3]), {base[3]}, 2026)["rows"]
    assert not set(row) & set(base[:4])


def test_acted_on_films_never_appear():
    cat, scores = world()
    scores = scores.copy()
    scores[[0, 1, 2]] = -np.inf                                        # rated, liked or watched
    assert not {0, 1, 2} & set(rr.recent_rail(cat, scores, set(), set(), 2026)["rows"])


def test_too_few_recent_films_means_no_row():
    cat, scores = world(10)
    assert rr.recent_rail(cat, scores, set(), set(), 2026, min_rows=8) is None
    cat2, scores2 = world(30)
    assert rr.recent_rail(cat2, scores2, set(), set(), 2020) is None          # nothing dated 2018 to 2020


def test_size_cap_and_year_window_moves_with_the_year():
    cat = Cat([2020 + i % 7 for i in range(200)], ["movie"] * 200)
    scores = np.linspace(1, 0, 200)
    assert len(rr.recent_rail(cat, scores, set(), set(), 2026)["rows"]) == 20
    r2022 = rr.recent_rail(cat, scores, set(), set(), 2022)["rows"]
    assert all(2020 <= cat.year[r] <= 2022 for r in r2022)


def test_row_goes_right_after_top_picks():
    rails = [{"key": "top_picks"}, {"key": "current_phase"}, {"key": "because_you_liked:5"}]
    new = {"key": "recent_for_you"}
    assert [r["key"] for r in rr.insert_after_top_picks(rails, new)] == ["top_picks", "recent_for_you", "current_phase", "because_you_liked:5"]
    assert [r["key"] for r in rr.insert_after_top_picks([{"key": "x"}], new)] == ["recent_for_you", "x"]
    assert rr.insert_after_top_picks(rails, None) == rails


# ---- the Home route with a fake engine ---------------------------------------------------------------
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.auth import current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import recs as recs_router  # noqa: E402
from app.services import daily  # noqa: E402

N = 40


class HomeCat:
    def __init__(self, ids):
        self.movie_ids = np.array(ids)
        self.row_of = {m: r for r, m in enumerate(ids)}
        self.year = np.array([2026 if r % 2 == 0 else 2010 for r in range(len(ids))], dtype=float)
        self.kind = np.array(["movie"] * len(ids), dtype=object)


class HomeEngine:
    def __init__(self, cat):
        self.cat = cat

    def scores(self, st):
        return {}

    def home(self, st, mode, tuning=None, recent_rows=None, scores=None, seed=None):
        rail = np.linspace(1.0, 0.0, N)
        entry = lambda r: {"row": r, "score": float(rail[r]), "match_pct": None, "shares": {}}
        top = [r for r in range(2, 14)]
        return {"stage": "established", "hero": [entry(0), entry(1)], "rail_scores": rail,
                "rails": [{"key": "top_picks", "title": "Top Picks For You", "source": "hybrid", "rows": top, "reason": None,
                           "scored": {r: entry(r) for r in top}},
                          {"key": "based_on_ratings", "title": "Based On Your Ratings", "source": "svd",
                           "rows": list(range(14, 24)), "reason": None, "scored": {}}]}

    def match(self, stage, s):
        return None

    def reasons(self, st, row, shares, reranked):
        return []


class HomeState:
    stage = "established"
    ratings, likes, picks, in_list, languages = {}, set(), set(), set(), []


@pytest.fixture
def home_client(test_engine, monkeypatch):
    ids = []
    with test_engine.begin() as conn:
        for n in range(N):
            ids.append(conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path, poster_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, :y, 'en', ARRAY['US'], '/b.jpg', '/p.jpg', 7, 5000, 'movie') RETURNING id"""),
                {"t": 993000 + n, "n": f"recent-{n}", "y": 2026 if n % 2 == 0 else 2010}).scalar())
        uid = conn.execute(text("INSERT INTO users (email, display_name, password_hash, is_guest) VALUES ('recent-row@example.com', 'x', 'x', false) RETURNING id")).scalar()
    cat = HomeCat(ids)
    monkeypatch.setattr(recs_router, "engine_or_503", lambda db: HomeEngine(cat))
    monkeypatch.setattr(recs_router.rec, "user_state", lambda db, u, e: HomeState())
    monkeypatch.setattr(recs_router.rec, "user_tuning", lambda db, u: None)
    monkeypatch.setattr(recs_router.rec, "recent_positive_rows", lambda db, u, e: [])
    monkeypatch.setattr(recs_router, "agreement_all", lambda e, s, sc: np.full(N, np.nan))
    monkeypatch.setattr(daily, "today", lambda: __import__("datetime").date(2026, 11, 12))
    app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "x@example.com", "display_name": "x", "is_guest": False}
    with TestClient(app) as c:
        c.ids, c.uid = ids, uid
        yield c
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        for t in ("recommendation_logs", "interactions", "rec_feedback"):
            conn.execute(text(f"DELETE FROM {t} WHERE user_id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM movies WHERE tmdb_id BETWEEN 993000 AND 993999"))


def test_home_has_the_new_row_after_top_picks_without_repeats(home_client):
    rails = home_client.get("/api/recs/home").json()["rails"]
    keys = [r["key"] for r in rails]
    assert keys[:2] == ["top_picks", "recent_for_you"]
    top = [i["movie"]["id"] for i in rails[0]["items"]]
    recent = [i["movie"]["id"] for i in rails[1]["items"]]
    assert recent and all(i["movie"]["year"] >= 2024 for i in rails[1]["items"])
    assert not set(top) & set(recent)                                   # a title appears once on the page
    hero = [i["movie"]["id"] for i in home_client.get("/api/recs/home").json()["hero"]]
    assert not set(hero) & set(recent)
    assert rails[1]["title"] == "New Releases For You"


def test_the_new_row_can_be_hidden_and_its_titles_can_be_turned_down(home_client):
    first = home_client.get("/api/recs/home").json()["rails"][1]["items"][0]["movie"]["id"]
    assert home_client.put(f"/api/feedback/not-interested/{first}", json={"source": "rail:recent_for_you"}).status_code == 200
    rails = home_client.get("/api/recs/home").json()["rails"]
    assert first not in [i["movie"]["id"] for r in rails for i in r["items"]]
    assert home_client.put("/api/feedback/rows", json={"source": "rail:recent_for_you"}).status_code == 200
    assert "recent_for_you" not in [r["key"] for r in home_client.get("/api/recs/home").json()["rails"]]
