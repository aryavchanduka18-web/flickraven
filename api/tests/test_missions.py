"""Discovery missions: progress from real activity only, and a personal genre."""
from app.services import missions as ms


def t(countries=("FR",), lang="fr", year=2010, kind="movie", episodes=None, genres=("Drama",)):
    return {"countries": list(countries), "lang": lang, "year": year, "title_type": kind, "episodes": episodes, "genres": list(genres)}


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
