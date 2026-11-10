"""Discovery missions: progress from real activity only, and a personal genre."""
from app.services import missions as ms


from datetime import datetime, timedelta, timezone

D0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def t(countries=("FR",), lang="fr", year=2010, kind="movie", episodes=None, genres=("Drama",), at=None, id=None):
    d = {"countries": list(countries), "lang": lang, "year": year, "title_type": kind, "episodes": episodes, "genres": list(genres)}
    if at is not None:
        d["at"] = D0 + timedelta(days=at)
    if id is not None:
        d["id"] = id
    return d


def test_progress_counts_and_caps():
    titles = [t(("FR",)), t(("JP",), "ja"), t(("US",), "en"), t(("KR",), "ko", 1975), t(("KR",), "ko"),
              t(("GB",), "en", kind="series", episodes=6)]
    by = {m.key: m for m in ms.progress(titles, "Horror")}
    assert by["world"].progress == 3                         # FR, JP, KR; the US does not count and series are not films
    assert by["mini_series"].done and by["classics"].progress == 1
    assert by["languages"].goal == 4 and by["genre:Horror"].progress == 0
    assert ms.progress(titles, None)[-1].done                # finished missions are listed last


def test_pick_new_genre_skips_watched_and_tv_movie():
    titles = [t(genres=("Drama",))] * 3 + [t(genres=("Comedy",))]
    assert ms.pick_new_genre(titles, ["Drama", "TV Movie", "Comedy", "Horror"]) == "Comedy"   # 1 comedy is still under the goal
    assert ms.pick_new_genre(titles * 3, ["Drama", "Comedy", "Horror"]) == "Horror"


def test_genre_mission_stays_until_done():
    """The genre must not change under the user while they work on it (it used to jump away at 2 of 3)."""
    base = [t(genres=("Drama",))] * 5
    for n in range(3):
        titles = base + [t(genres=("Horror",))] * n
        g = ms.pick_new_genre(titles, ["Drama", "Horror", "Comedy"])
        assert g == "Horror"
        assert next(m for m in ms.progress(titles, g) if m.key == "genre:Horror").progress == n
    assert ms.pick_new_genre(base + [t(genres=("Horror",))] * 3, ["Drama", "Horror", "Comedy"]) == "Comedy"   # done: next genre


def test_main_language_ties_are_stable():
    assert ms.main_language([t(lang="fr"), t(lang="en")]) == "en" and ms.main_language([]) is None


def test_missions_endpoint_never_suggests_a_disliked_title(test_engine):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    with test_engine.begin() as conn:
        ids = [conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 1960, 'fr', ARRAY['FR'], '/b.jpg', 8.0, :v, 'movie')
                RETURNING id"""), {"t": 960000 + i, "n": f"Old {i}", "v": 1000 - i}).scalar() for i in range(3)]
    try:
        with TestClient(app) as c:
            c.post("/api/auth/guest")
            assert c.put(f"/api/reactions/{ids[0]}", json={"value": -1}).status_code == 200
            body = c.get("/api/me/missions").json()
            classics = next(m for m in body["missions"] if m["key"] == "classics")
            shown = [it["movie"]["id"] for it in classics["suggestions"]]
            assert ids[1] in shown and ids[0] not in shown
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})


def test_completion_date_is_when_the_goal_was_reached():
    """Replayed from the activity times: the third classic was watched on day 9, so that is the completion date,
    even though a fourth was added later."""
    titles = [t(year=1950, at=2, id=1), t(year=2015, at=3, id=2), t(year=1960, at=5, id=3), t(year=1970, at=9, id=4),
              t(year=1940, at=20, id=5)]
    by = {m.key: m for m in ms.progress(titles, None)}
    assert by["classics"].done and by["classics"].completed_at == D0 + timedelta(days=9)
    assert by["decades"].done and by["decades"].completed_at == D0 + timedelta(days=20)    # the 5th decade came last
    assert by["world"].completed_at is None                                                 # not done: no date


def test_decades_and_why_use_only_real_numbers():
    titles = [t(year=1950, at=1, id=1), t(year=1955, at=2, id=2), t(("US",), "en", 1995, at=3, id=3)]
    by = {m.key: m for m in ms.progress(titles, ["Horror"])}
    assert by["decades"].progress == 2 and "2 decades" in by["decades"].why
    assert "1 of your 3 films are from the US or India" in by["world"].why
    assert "2 of your 3 titles are in French" in by["languages"].why and "1 other language" in by["languages"].why
    assert "0 Horror titles" in by["genre:Horror"].why and "3 in Drama" in by["genre:Horror"].why
    assert "no films logged" in {m.key: m for m in ms.progress([], None)}["classics"].why


def test_tabs():
    m = ms.progress([t(year=1950, id=i, at=i) for i in range(3)] + [t(("JP",), "ja", id=9, at=9)], None)
    by = {x.key: x for x in m}
    assert ms.tab(by["classics"], False, True) == "completed"                # done wins, even if dismissed
    assert ms.tab(by["classics"], True, True) == "completed"
    assert ms.tab(by["world"], False, True) == "active"                      # 1 of 5: started
    assert ms.tab(by["languages"], True, True) == "explore"                  # dismissed goes to Explore
    assert ms.tab(by["mini_series"], False, True) == "recommended"
    assert ms.tab(by["mini_series"], False, False) == "explore"              # extra ideas live in Explore


def test_pick_new_genres_skips_excluded_and_returns_several():
    titles = [t(genres=("Drama",))] * 3
    assert ms.pick_new_genres(titles, ["Drama", "Comedy", "Horror", "Action"], {"Comedy"}, 2) == ["Horror", "Action"]


def test_journey_endpoint_tabs_dismiss_and_completion_date(test_engine):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    with test_engine.begin() as conn:
        ids = [conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, :y, 'fr', ARRAY['FR'], '/b.jpg', 8.0, :v, 'movie')
                RETURNING id"""), {"t": 961000 + i, "n": f"Journey {i}", "y": 1950 + i, "v": 5000 - i}).scalar() for i in range(5)]
    try:
        with TestClient(app) as c:
            c.post("/api/auth/guest")
            body = c.get("/api/me/missions").json()
            by = {m["key"]: m for m in body["missions"]}
            assert by["classics"]["tab"] == "recommended" and by["classics"]["why"] and "ranked_by_taste" in by["classics"]
            assert body["counts"]["recommended"] >= 4 and body["counts"]["completed"] == 0
            # real actions move progress; three classics complete the mission and it gets a date
            for i in ids[:2]:
                assert c.put(f"/api/watched/{i}").status_code == 200
            assert {m["key"]: m for m in c.get("/api/me/missions").json()["missions"]}["classics"]["tab"] == "active"
            assert c.put(f"/api/watched/{ids[2]}").status_code == 200
            done = {m["key"]: m for m in c.get("/api/me/missions").json()["missions"]}["classics"]
            assert done["tab"] == "completed" and done["completed_at"] and done["suggestions"] == []
            # dismiss and restore
            assert c.put("/api/me/missions/world/dismiss").status_code == 200
            w = {m["key"]: m for m in c.get("/api/me/missions").json()["missions"]}["world"]
            assert w["tab"] == "explore" and w["dismissed"] is True and w["suggestions"] == []
            assert c.delete("/api/me/missions/world/dismiss").status_code == 200
            assert {m["key"]: m for m in c.get("/api/me/missions").json()["missions"]}["world"]["dismissed"] is False
            assert c.put("/api/me/missions/not-a-mission/dismiss").status_code == 404
            # a dismissed mission that is already completed stays completed
            assert c.put("/api/me/missions/classics/dismiss").status_code == 200
            assert {m["key"]: m for m in c.get("/api/me/missions").json()["missions"]}["classics"]["tab"] == "completed"
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})


def test_ideas_are_reordered_by_taste_fit_only_when_there_is_a_profile(test_engine, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.routers import missions as router
    from app.services import taste_dna as dna
    with test_engine.begin() as conn:
        ids = [conn.execute(text("""INSERT INTO movies (tmdb_id, title, year, original_language, countries, backdrop_path,
                popularity_score, tmdb_vote_count, title_type) VALUES (:t, :n, 1950, 'fr', ARRAY['FR'], '/b.jpg', 8.0, :v, 'movie')
                RETURNING id"""), {"t": 962000 + i, "n": f"Idea {i}", "v": 9000 - i}).scalar() for i in range(3)]
    try:
        with Session(test_engine) as db:
            sql = "SELECT movie_id FROM watched WHERE user_id = -1"
            plain, ranked = router._ideas(db, -1, "classics", [], None, sql)
            order = [i["movie"]["id"] for i in plain if i["movie"]["id"] in ids]
            assert not ranked and order == ids                                  # popularity order without a profile
            fits = {ids[0]: -1.0, ids[1]: 2.0, ids[2]: None}
            monkeypatch.setattr(dna, "title_vectors", lambda db, got: {x: {"id": x} for x in got})
            monkeypatch.setattr(dna, "fit", lambda p, v: (fits.get(v["id"]), []) if v and v["id"] in fits else (0.0, []))
            reranked, ranked = router._ideas(db, -1, "classics", [], object(), sql)
            got = [i["movie"]["id"] for i in reranked if i["movie"]["id"] in ids]
            assert ranked and got == [ids[1], ids[0], ids[2]]                    # best fit first, unknown last
    finally:
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})
