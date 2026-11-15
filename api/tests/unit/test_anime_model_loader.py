"""The anime model file: missing, broken, malformed or switched off all mean no model (anime lists keep the earlier order)."""
import numpy as np

from app.services import recommender as rec


def write(tmp_path, **over):
    a = {"settings": np.array("{}")}
    for t, w in (("long", 0.5), ("mid", 0.4), ("short", 0.3)):
        a[f"{t}_src"], a[f"{t}_dst"], a[f"{t}_w"] = np.array([10]), np.array([11]), np.array([w], dtype=np.float32)
    a["short_src"], a["short_dst"], a["short_w"] = np.array([10, 10]), np.array([11, 12]), np.array([0.3, 0.1], dtype=np.float32)
    a.update(over)
    with open(tmp_path / "anime_model.npz", "wb") as f:
        np.savez_compressed(f, **{k: v for k, v in a.items() if v is not None})


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "MODELS", tmp_path)
    monkeypatch.delenv("ANIME_MODEL_DISABLED", raising=False)


def test_a_good_file_gives_three_catalog_matrices(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    write(tmp_path)
    m = rec._anime_model([10, 11, 12])
    assert set(m) == {"long", "mid", "short"}
    assert m["short"][0, 1] > m["short"][0, 2] > 0 and m["long"][1, 0] == 0      # votes go one way (row = voter)


def test_missing_broken_partial_or_disabled_means_no_model(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    assert rec._anime_model([10, 11]) is None                                    # no file
    (tmp_path / "anime_model.npz").write_bytes(b"not a zip file")
    assert rec._anime_model([10, 11]) is None                                    # broken file
    (tmp_path / "anime_model.npz").write_bytes(b"PK\x03\x04truncated")
    assert rec._anime_model([10, 11]) is None                                    # cut-off zip
    write(tmp_path, mid_src=None)
    assert rec._anime_model([10, 11]) is None                                    # a tier is missing
    write(tmp_path)
    assert rec._anime_model([98, 99]) is None                                    # nothing in this catalog
    monkeypatch.setenv("ANIME_MODEL_DISABLED", "true")
    assert rec._anime_model([10, 11]) is None                                    # off switch


def test_bad_values_or_pickled_objects_mean_no_model(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    for over in ({"long_w": np.array([np.nan])}, {"long_w": np.array([1e300])}, {"long_w": np.array([0.0])},
                 {"long_w": np.array([-1.0])}, {"long_src": np.array(["x"])}, {"long_src": np.array([10.5])},
                 {"long_src": np.array([10, 10])}, {"long_src": np.array([10, None], dtype=object)}):
        write(tmp_path, **over)
        assert rec._anime_model([10, 11]) is None, over
