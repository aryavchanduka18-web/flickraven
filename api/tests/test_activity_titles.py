"""Recent Activity groups events per title; the raw list stays available and names the title type."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


@pytest.fixture()
def titles(test_engine):
    with test_engine.begin() as conn:
        ids = [conn.execute(text("INSERT INTO movies (tmdb_id, title, year, original_language, title_type) "
                                 "VALUES (:t, :n, 2001, 'en', :k) RETURNING id"), {"t": t, "n": n, "k": k}).scalar()
               for t, n, k in ((951001, "Group Film", "movie"), (951002, "Group Show", "series"))]
    yield ids
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = ANY(:i)"), {"i": ids})


def test_events_are_grouped_per_title_and_series_is_labelled(titles):
    film, show = titles
    with TestClient(app) as c:
        c.post("/api/auth/guest")
        for _ in range(4):
            c.post("/api/events", json={"event_type": "detail_view", "movie_id": film})
        c.post("/api/events", json={"event_type": "detail_view", "movie_id": show})
        c.put(f"/api/ratings/{film}", json={"rating": 8})
        grouped = c.get("/api/activity/titles").json()["items"]
        by_title = {i["title"]: i for i in grouped}
        assert len(grouped) == 2
        assert by_title["Group Film"]["counts"]["detail_view"] == 1 and by_title["Group Film"]["rating"] == 8
        assert by_title["Group Show"]["title_type"] == "series"
        raw = c.get("/api/activity").json()["items"]
        assert len(raw) >= 3 and {i["title_type"] for i in raw} == {"movie", "series"}
