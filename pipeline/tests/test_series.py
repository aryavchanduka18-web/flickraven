"""A TV series is reshaped into a film-shaped record that the existing gate and parser accept."""
from pipeline.catalog import gate_failures, parse_credits, parse_movie
from pipeline.series import TV_OFFSET, is_anime, normalize, tv_id

TV = {
    "id": 1396, "name": "Breaking Bad", "original_name": "Breaking Bad", "first_air_date": "2008-01-20",
    "overview": "A high school chemistry teacher diagnosed with cancer turns to making and selling methamphetamine to secure his family's future.",
    "original_language": "en", "origin_country": ["US"], "poster_path": "/p.jpg", "backdrop_path": "/b.jpg",
    "genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}, {"id": 10765, "name": "Sci-Fi & Fantasy"},
               {"id": 10764, "name": "Reality"}],
    "status": "Ended", "number_of_seasons": 5, "number_of_episodes": 62, "episode_run_time": [47],
    "vote_count": 14000, "vote_average": 8.9, "adult": False, "tagline": "Remember my name",
    "networks": [{"name": "AMC"}], "production_companies": [{"name": "Sony Pictures Television"}],
    "created_by": [{"id": 66633, "name": "Vince Gilligan", "profile_path": "/v.jpg"}],
    "credits": {"cast": [{"id": 17419, "name": "Bryan Cranston", "character": "Walter White", "order": 0, "profile_path": None}]},
    "keywords": {"results": [{"id": 1, "name": "Drug Dealer"}]},
    "content_ratings": {"results": [{"iso_3166_1": "US", "rating": "TV-MA"}, {"iso_3166_1": "IN", "rating": "A"}]},
    "external_ids": {"imdb_id": "tt0903747"}, "images": {"logos": [{"iso_639_1": "en", "file_path": "/l.png"}]},
}


def test_series_gets_its_own_id_range_and_film_shape():
    d = normalize(TV)
    assert d["id"] == TV_OFFSET + 1396 and tv_id(d["id"]) == 1396
    m = parse_movie(d)
    assert (m["title"], m["year"], m["runtime_min"], m["imdb_id"], m["certification"]) == ("Breaking Bad", 2008, 47, "tt0903747", "A")
    assert (m["title_type"], m["seasons"], m["episodes"], m["series_status"]) == ("series", 5, 62, "Ended")
    assert m["genres"] == ["Drama", "Crime", "Science Fiction", "Fantasy"]      # Reality has no film genre
    assert m["keywords"] == ["drug dealer"] and m["studios"] == ["AMC", "Sony Pictures Television"]


def test_creators_are_credited_and_a_series_needs_no_director():
    d = normalize(TV)
    assert gate_failures(d) == []
    assert [(r["name"], r["role"]) for r in parse_credits(d)] == [("Bryan Cranston", "cast"), ("Vince Gilligan", "writer")]
    assert "no_director" in gate_failures({**d, "_media": None})              # films still need one


def test_anime_is_japanese_animation_and_a_planned_show_is_not_released():
    anime = {**TV, "original_language": "ja", "genres": [{"id": 16, "name": "Animation"}, {"id": 10759, "name": "Action & Adventure"}]}
    assert is_anime(anime) and normalize(anime)["title_type"] == "anime"
    assert not is_anime({**anime, "original_language": "en"})
    assert normalize({**TV, "status": "Planned"})["status"] == "Planned"
    assert normalize(TV)["status"] == "Released"
