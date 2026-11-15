"""The anime model file: missing, broken or switched off all mean no model (anime lists keep the earlier order)."""
import json

from app.services import recommender as rec


def write(tmp_path, models):
    (tmp_path / "anime_model.json").write_text(json.dumps({"models": models}), encoding="utf-8")


GOOD = {"long": {"10": [[11, 0.5]]}, "mid": {"10": [[11, 0.4]]}, "short": {"10": [[11, 0.3], [12, 0.1]]}}


def test_a_good_file_gives_three_catalog_matrices(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "MODELS", tmp_path)
    monkeypatch.delenv("ANIME_MODEL_DISABLED", raising=False)
    write(tmp_path, GOOD)
    m = rec._anime_model([10, 11, 12])
    assert set(m) == {"long", "mid", "short"}
    assert m["short"][0, 1] > m["short"][0, 2] > 0 and m["long"][1, 0] == 0      # votes go one way (row = voter)


def test_missing_broken_partial_or_disabled_means_no_model(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "MODELS", tmp_path)
    monkeypatch.delenv("ANIME_MODEL_DISABLED", raising=False)
    assert rec._anime_model([10, 11]) is None                                    # no file
    (tmp_path / "anime_model.json").write_text("{not json", encoding="utf-8")
    assert rec._anime_model([10, 11]) is None                                    # broken file
    write(tmp_path, {"long": GOOD["long"]})
    assert rec._anime_model([10, 11]) is None                                    # a tier is missing
    write(tmp_path, GOOD)
    assert rec._anime_model([98, 99]) is None                                    # nothing in this catalog
    monkeypatch.setenv("ANIME_MODEL_DISABLED", "true")
    assert rec._anime_model([10, 11]) is None                                    # off switch
