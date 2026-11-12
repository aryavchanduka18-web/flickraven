"""Hosting: database URL forms, the model bundle delivered through the database, and the SPA fallback."""
import hashlib
import io
import tarfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.main import WEB_DIST, app
from app.services import artifact_store


@pytest.mark.parametrize("given", ["postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d",
                                   "postgresql+psycopg://u:p@h:5432/d"])
def test_render_database_urls_get_the_psycopg_driver(given):
    assert Settings(database_url=given).database_url == "postgresql+psycopg://u:p@h:5432/d"


def _bundle(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def store(test_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "ROOT", tmp_path)
    monkeypatch.setattr(artifact_store, "MARKER", tmp_path / ".bundle_sha256")
    with test_engine.begin() as conn:
        conn.execute(text(artifact_store.TABLE_SQL))
    yield tmp_path
    with test_engine.begin() as conn:      # keep the schema identical to the models for test_migrations
        conn.execute(text("DROP TABLE deploy_artifacts"))
        conn.execute(text("DROP TABLE IF EXISTS deploy_artifact_chunks"))


def _put(test_engine, data: bytes, sha: str | None = None) -> None:
    with test_engine.begin() as conn:
        conn.execute(text("""INSERT INTO deploy_artifacts (name, sha256, data) VALUES (:n, :s, :d)
            ON CONFLICT (name) DO UPDATE SET sha256 = :s, data = :d"""),
                     {"n": artifact_store.BUNDLE, "s": sha or hashlib.sha256(data).hexdigest(), "d": data})


def test_bundle_is_unpacked_once_and_again_after_a_new_upload(store, test_engine):
    assert artifact_store.sync() is False                          # nothing uploaded yet
    _put(test_engine, _bundle({"models/hybrid_weights.json": b"{}"}))
    assert artifact_store.sync() is True
    assert (store / "models" / "hybrid_weights.json").read_bytes() == b"{}"
    assert artifact_store.sync() is False                          # same bundle: nothing to do
    _put(test_engine, _bundle({"models/hybrid_weights.json": b'{"v": 2}'}))
    assert artifact_store.sync() is True
    assert (store / "models" / "hybrid_weights.json").read_bytes() == b'{"v": 2}'


def test_bundle_with_a_wrong_checksum_is_refused(store, test_engine):
    _put(test_engine, _bundle({"models/x.json": b"1"}), sha="0" * 64)
    assert artifact_store.sync() is False
    assert not (store / "models").exists()


def test_bundle_cannot_write_outside_the_artifacts_folder(store, test_engine):
    _put(test_engine, _bundle({"../escape.txt": b"no"}))
    with pytest.raises(tarfile.TarError):
        artifact_store.sync()
    assert not (store.parent / "escape.txt").exists()


@pytest.mark.skipif(not (WEB_DIST / "index.html").exists(), reason="web/dist not built")
def test_website_routes_fall_back_to_index_html_but_api_does_not():
    c = TestClient(app)
    page = c.get("/movie/123")
    assert page.status_code == 200 and "<div id=\"root\">" in page.text
    assert c.get("/api/no-such-endpoint").status_code == 404
    assert c.get("/api/health").json()["status"] == "ok"


def test_chunked_bundle_is_joined_in_order_and_checked(store, test_engine):
    bundle = _bundle({"models/fitted.npz": bytes(range(256)) * 400})
    sha = hashlib.sha256(bundle).hexdigest()
    parts = [bundle[i:i + 1000] for i in range(0, len(bundle), 1000)]
    with test_engine.begin() as conn:
        for sql in artifact_store.CHUNKS_SQL:
            conn.execute(text(sql))
        for seq in reversed(range(len(parts))):          # stored out of order on purpose
            conn.execute(text("INSERT INTO deploy_artifact_chunks VALUES (:n, :s, :q, :d)"),
                         {"n": artifact_store.BUNDLE, "s": sha, "q": seq, "d": parts[seq]})
        conn.execute(text("INSERT INTO deploy_artifacts (name, sha256, data, chunks) VALUES (:n, :s, '', :c)"),
                     {"n": artifact_store.BUNDLE, "s": sha, "c": len(parts) + 1})
    assert artifact_store.sync() is False                # a part is missing: nothing is unpacked
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE deploy_artifacts SET chunks = :c"), {"c": len(parts)})
    assert artifact_store.sync() is True
    assert (store / "models" / "fitted.npz").read_bytes() == bytes(range(256)) * 400


def test_bundle_comes_from_the_url_when_set_and_the_database_is_not_read(store, test_engine, monkeypatch):
    from app.config import get_settings
    bundle = _bundle({"models/hybrid_weights.json": b'{"from": "url"}'})
    _put(test_engine, _bundle({"models/hybrid_weights.json": b'{"from": "db"}'}),
         sha=hashlib.sha256(bundle).hexdigest())           # the row names the current bundle
    monkeypatch.setattr(get_settings(), "artifact_bundle_url", "https://files.example/bundle")
    monkeypatch.setattr(get_settings(), "artifact_bundle_token", "t")
    calls = []
    monkeypatch.setattr(artifact_store, "_download", lambda url, token: calls.append((url, token)) or bundle)
    assert artifact_store.sync() is True
    assert calls == [("https://files.example/bundle", "t")]
    assert (store / "models" / "hybrid_weights.json").read_bytes() == b'{"from": "url"}'
    assert artifact_store.sync() is False                  # marker matches: no second download
    assert len(calls) == 1


@pytest.mark.parametrize("downloaded", [None, b"stale bundle"])
def test_failed_or_stale_download_falls_back_to_the_database(store, test_engine, monkeypatch, downloaded):
    from app.config import get_settings
    _put(test_engine, _bundle({"models/hybrid_weights.json": b'{"from": "db"}'}))
    monkeypatch.setattr(get_settings(), "artifact_bundle_url", "https://files.example/bundle")
    monkeypatch.setattr(artifact_store, "_download", lambda url, token: downloaded)
    assert artifact_store.sync() is True
    assert (store / "models" / "hybrid_weights.json").read_bytes() == b'{"from": "db"}'
