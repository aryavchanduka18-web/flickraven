"""Run a built image like Render (512 MB cap, Linux, PRELOAD_ENGINE, start.sh) and measure container memory.

    .\.venv\Scripts\python.exe work/memory/docker_measure.py flickraven-mem:before before

Uses the LOCAL Docker database (host.docker.internal) and the local artifacts folder (read-only). Never prints the
database URL. Reads cgroup memory.current / memory.peak inside the container and Docker's OOMKilled flag.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PORT = 18000


def env_value(key):
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} missing from .env")


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def cg(name, what):
    r = sh(["docker", "exec", name, "cat", f"/sys/fs/cgroup/{what}"])
    if r.returncode == 0 and r.stdout.strip().isdigit():
        return round(int(r.stdout.strip()) / 2**20, 1)
    return None


def snap(name):
    return {"current_mb": cg(name, "memory.current"), "peak_mb": cg(name, "memory.peak")}


def main():
    image, label = sys.argv[1], sys.argv[2]
    name = f"fr-mem-{label}"
    sh(["docker", "rm", "-f", name])
    url = re.sub(r"@(localhost|127\.0\.0\.1)", "@host.docker.internal", env_value("DATABASE_URL"))
    r = sh(["docker", "run", "-d", "--name", name, "--memory=512m", "--memory-swap=512m", "-p", f"{PORT}:8000",
            "-e", "DATABASE_URL", "-e", "JWT_SECRET=local-memory-test-only", "-e", "COOKIE_SECURE=false",
            "-e", f"WEB_ORIGIN=http://localhost:{PORT}", "-e", "GEMINI_API_KEY=",
            "-v", f"{ROOT / 'artifacts'}:/app/artifacts:ro", image], env={**os.environ, "DATABASE_URL": url})
    if r.returncode:
        raise SystemExit(r.stderr[-500:])
    stages = {}
    t0 = time.time()
    ids = []
    with httpx.Client(base_url=f"http://localhost:{PORT}", timeout=120) as c:
        while time.time() - t0 < 300:
            try:
                if c.get("/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        stages["server_up"] = {**snap(name), "s": round(time.time() - t0)}
        c.post("/api/auth/guest")
        for _ in range(90):                                  # wait for the preload thread
            try:
                if c.get("/api/recs/home").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        stages["engine_loaded_first_home"] = {**snap(name), "s": round(time.time() - t0)}
        try:
            hits = c.get("/api/search?q=the").json()
            items = hits.get("results") or hits.get("items") or hits.get("movies") or [] if isinstance(hits, dict) else hits
            ids = [h["id"] for h in items if isinstance(h, dict) and "id" in h][:30]
        except Exception:
            ids = []
        for i, mid in enumerate(ids):
            c.put(f"/api/ratings/{mid}", json={"rating": 6 + (i % 5)})
        c.get("/api/recs/home")
        stages["home_with_ratings"] = snap(name)
        c.post("/api/recs/perfect-pick", json={"kind": "movie", "genres": ["Crime"]})
        stages["perfect_pick"] = snap(name)
        c.get("/api/recs/series-rails")
        c.get("/api/recs/anime")
        stages["series_anime"] = snap(name)
        paths = ["/api/recs/home", "/api/recs/kind/tv", "/api/recs/series-rails", "/api/recs/anime",
                 "/api/search?q=love", "/api/me/taste-dna", "/api/recs/surprise", "/api/discover/options"]
        for i in range(20):
            c.get(paths[i % len(paths)])
        stages["after_20_mixed"] = snap(name)
    insp = json.loads(sh(["docker", "inspect", name]).stdout)[0]["State"]
    out = {"image": image, "label": label, "rated": len(ids), "stages": stages,
           "oom_killed": insp.get("OOMKilled"), "status": insp.get("Status")}
    (ROOT / "work" / "memory" / f"docker-{label}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    logs = sh(["docker", "logs", "--tail", "12", name])
    sh(["docker", "rm", "-f", name])
    print(json.dumps(out, indent=1))
    print("--- last log lines ---")
    print("\n".join(l for l in (logs.stdout + logs.stderr).splitlines()[-12:] if "postgres" not in l.lower()))


if __name__ == "__main__":
    main()
