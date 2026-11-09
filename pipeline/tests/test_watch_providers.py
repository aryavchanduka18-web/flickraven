"""Where to watch keeps India's services, falls back to the US only when India has none, and never invents any."""
from pipeline.watch_providers import pick


def svc(pid, name):
    return {"provider_id": pid, "provider_name": name, "logo_path": f"/{pid}.png", "display_priority": pid}


IN = {"link": "https://www.themoviedb.org/movie/1/watch?locale=IN", "flatrate": [svc(8, "Netflix")],
      "rent": [svc(2, "Apple TV"), svc(2, "Apple TV")]}
US = {"link": "https://www.themoviedb.org/movie/1/watch?locale=US", "flatrate": [svc(1899, "Max")]}


def test_india_first():
    rows = pick(1, {"results": {"IN": IN, "US": US}}, "IN", "US")
    assert {(r["region"], r["kind"], r["provider_name"]) for r in rows} == {("IN", "flatrate", "Netflix"), ("IN", "rent", "Apple TV")}
    assert all(r["link"] == IN["link"] for r in rows)


def test_fallback_only_when_india_has_nothing():
    rows = pick(1, {"results": {"IN": {"link": "x"}, "US": US}}, "IN", "US")
    assert [(r["region"], r["provider_name"]) for r in rows] == [("US", "Max")]


def test_nothing_listed_means_no_rows():
    assert pick(1, {"results": {"GB": US}}, "IN", "US") == []
    assert pick(1, None, "IN", "US") == []
