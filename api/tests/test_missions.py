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
    titles = [t(genres=("Drama",)), t(genres=("Drama",)), t(genres=("Comedy",))]
    assert ms.pick_new_genre(titles, ["Drama", "TV Movie", "Comedy", "Horror"]) == "Comedy"   # 1 comedy still counts as barely
    assert ms.pick_new_genre(titles * 2, ["Drama", "Comedy", "Horror"]) == "Horror"
