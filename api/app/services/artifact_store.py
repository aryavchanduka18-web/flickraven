"""Model artifacts for a hosted copy, delivered through the (private) database.

The repository is public and the artifacts are built from MovieLens ratings, which may not be
redistributed, so they are never committed. Instead scripts/deploy_data.py uploads one compact
bundle (artifacts.tar.gz: models/, metrics/, lab/) into the table deploy_artifacts of the hosted
database, and the server unpacks it into artifacts/ when it starts, or on first use if the upload
happened after the server started.

Run at container start:  python -m app.services.artifact_store
"""
import hashlib
import io
import logging
import tarfile
import threading
import time
from pathlib import Path

from sqlalchemy import text

log = logging.getLogger("uvicorn.error")

ROOT = Path(__file__).resolve().parents[3] / "artifacts"
BUNDLE = "artifacts.tar.gz"
MARKER = ROOT / ".bundle_sha256"
TABLE_SQL = """CREATE TABLE IF NOT EXISTS deploy_artifacts (
    name text PRIMARY KEY, sha256 text NOT NULL, data bytea NOT NULL, uploaded_at timestamptz NOT NULL DEFAULT now())"""
# Large bundles travel in chunks (one small insert each survives flaky connections); the deploy_artifacts row
# is the manifest, written last: data is empty and `chunks` says how many rows of the bundle to join.
CHUNKS_SQL = [
    "ALTER TABLE deploy_artifacts ADD COLUMN IF NOT EXISTS chunks int",
    """CREATE TABLE IF NOT EXISTS deploy_artifact_chunks (
        name text NOT NULL, sha256 text NOT NULL, seq int NOT NULL, data bytea NOT NULL,
        PRIMARY KEY (name, sha256, seq))""",
]

_lock = threading.Lock()
_last_try = 0.0
RETRY_S = 30


def _extract(data: bytes) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(ROOT, filter="data")      # "data" refuses absolute paths, links out and ../


def _download(url: str, token: str, timeout: float = 120.0) -> bytes | None:
    """The bundle from ARTIFACT_BUNDLE_URL, or None. GitHub release assets need the API asset URL with
    Accept: application/octet-stream; GitHub then redirects to a signed storage URL, and httpx drops the
    Authorization header on a redirect to another host."""
    import httpx
    headers = {"Accept": "application/octet-stream", "User-Agent": "flickraven-server"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception as exc:          # never take the site down; the caller falls back to the database
        log.warning("artifact bundle download failed (%s); using the database copy", type(exc).__name__)
        return None


def _from_database(conn, sha: str, chunks: int | None) -> bytes | None:
    if chunks:          # chunked upload: join the parts in order
        parts = conn.execute(text("""SELECT data FROM deploy_artifact_chunks WHERE name = :n AND sha256 = :s
            ORDER BY seq"""), {"n": BUNDLE, "s": sha}).scalars().all()
        if len(parts) != chunks:
            log.error("artifact bundle has %d of %d chunks; not unpacking", len(parts), chunks)
            return None
        return b"".join(bytes(x) for x in parts)
    return bytes(conn.execute(text("SELECT data FROM deploy_artifacts WHERE name = :n"),
                              {"n": BUNDLE}).scalar_one())


def sync(force: bool = False) -> bool:
    """Unpack the uploaded bundle if it is newer than what is on disk. True if something was unpacked.

    The deploy_artifacts row (a few bytes) says which bundle is current. The bundle itself comes from
    ARTIFACT_BUNDLE_URL when that is set and its checksum matches, otherwise from the database."""
    from app.config import get_settings
    from app.db import engine
    settings = get_settings()
    with engine.connect() as conn:
        if conn.execute(text("SELECT to_regclass('deploy_artifacts')")).scalar() is None:
            return False
        chunked = conn.execute(text("""SELECT 1 FROM information_schema.columns
            WHERE table_name = 'deploy_artifacts' AND column_name = 'chunks'""")).first() is not None
        row = conn.execute(text(f"SELECT sha256, {'chunks' if chunked else 'NULL'} FROM deploy_artifacts "
                                "WHERE name = :n"), {"n": BUNDLE}).first()
        if row is None:
            return False
        sha, chunks = row[0], row[1]
        if not force and MARKER.exists() and MARKER.read_text().strip() == sha:
            return False
    data = None
    if settings.artifact_bundle_url:
        data = _download(settings.artifact_bundle_url, settings.artifact_bundle_token)
        if data is not None and hashlib.sha256(data).hexdigest() != sha:
            log.warning("downloaded artifact bundle is not the current one (checksum differs); using the database "
                        "copy. Upload deploy-out/artifacts.tar.gz to the file host again.")
            data = None
        elif data is not None:
            log.info("artifact bundle fetched from ARTIFACT_BUNDLE_URL")
    if data is None:
        with engine.connect() as conn:
            data = _from_database(conn, sha, chunks)
        if data is None:
            return False
    if hashlib.sha256(data).hexdigest() != sha:
        log.error("artifact bundle checksum mismatch; not unpacking")
        return False
    _extract(data)
    MARKER.write_text(sha)
    log.info("unpacked artifact bundle %s (%.1f MB)", sha[:12], len(data) / 1e6)
    return True


def try_sync() -> None:
    """Called when artifacts are missing; checks the database at most every RETRY_S seconds."""
    global _last_try
    with _lock:
        if time.monotonic() - _last_try < RETRY_S:
            return
        _last_try = time.monotonic()
        try:
            sync()
        except Exception:      # a missing bundle must never take the site down
            log.exception("could not fetch the artifact bundle")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("artifact bundle unpacked" if sync() else "artifact bundle: nothing new to unpack")
