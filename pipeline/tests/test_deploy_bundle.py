import io
import tarfile

import pytest

from scripts.deploy_data import (
    REQUIRED_MODEL_FILES,
    validate_model_bundle,
    validate_model_directory,
)


def _write_bundle(path, members):
    with tarfile.open(path, "w:gz") as bundle:
        for name in members:
            info = tarfile.TarInfo(name)
            info.size = 1
            bundle.addfile(info, io.BytesIO(b"x"))


def test_model_bundle_requires_availability_calibration_and_core_assets(tmp_path):
    path = tmp_path / "artifacts.tar.gz"
    files = [f"models/{name}" for name in REQUIRED_MODEL_FILES if name != "availability_calibration.json"]
    _write_bundle(path, files)

    with pytest.raises(ValueError, match="models/availability_calibration.json"):
        validate_model_bundle(path)


def test_complete_model_bundle_passes_validation(tmp_path):
    path = tmp_path / "artifacts.tar.gz"
    _write_bundle(path, [f"models/{name}" for name in REQUIRED_MODEL_FILES])

    validate_model_bundle(path)


def test_model_directory_requires_availability_calibration_and_core_assets(tmp_path):
    for name in REQUIRED_MODEL_FILES:
        if name != "availability_calibration.json":
            (tmp_path / name).write_bytes(b"x")

    with pytest.raises(ValueError, match="availability_calibration.json"):
        validate_model_directory(tmp_path)


def test_complete_model_directory_passes_validation(tmp_path):
    for name in REQUIRED_MODEL_FILES:
        (tmp_path / name).write_bytes(b"x")

    validate_model_directory(tmp_path)


def test_invalid_model_bundle_reports_that_it_cannot_be_read(tmp_path):
    path = tmp_path / "artifacts.tar.gz"
    path.write_bytes(b"not a gzip archive")

    with pytest.raises(ValueError, match="Cannot read model bundle"):
        validate_model_bundle(path)
