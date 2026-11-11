"""SHA-256 fingerprint of everything the evaluation depends on, to prove a catalog change left it alone.

    python -m pipeline.eval_fingerprint save      # before the change: writes artifacts/metrics/eval_fingerprint.json
    python -m pipeline.eval_fingerprint check     # after: lists any file that changed (exit code 1 if one did)

Covered: the ratings sample and splits, the training features, every fitted model and setting, and every
evaluation result. Not covered, because a catalog change is meant to change them: the serving content
matrix and its row list (pipeline/extend_serving.py keeps every existing row identical and checks it),
the serving-extension and catalog-audit reports, and this fingerprint file.
"""
import hashlib
import json
import sys

from pipeline.common import ARTIFACTS, PROCESSED

SERVING_ONLY = {"models/content_matrix.npz", "models/content_rows.parquet", "metrics/serving_extension.json",
                "metrics/catalog_audit.json", "metrics/eval_fingerprint.json"}
OUT = ARTIFACTS / "metrics" / "eval_fingerprint.json"


def fingerprint() -> dict[str, str]:
    files = [PROCESSED / "ratings.parquet", *sorted((PROCESSED / "splits").rglob("*"))]
    files += [p for p in sorted(ARTIFACTS.rglob("*"))
              if p.relative_to(ARTIFACTS).as_posix() not in SERVING_ONLY and ".bundle" not in p.name]
    out = {}
    for p in files:
        if p.is_file():
            key = p.relative_to(PROCESSED.parent if p.is_relative_to(PROCESSED) else ARTIFACTS.parent).as_posix()
            out[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main(cmd: str) -> int:
    now = fingerprint()
    if cmd == "save":
        OUT.write_text(json.dumps(now, indent=1), encoding="utf-8")
        print(f"saved fingerprint of {len(now)} files")
        return 0
    before = json.loads(OUT.read_text(encoding="utf-8"))
    changed = sorted(k for k in before.keys() | now.keys() if before.get(k) != now.get(k))
    print(f"{len(before)} files fingerprinted; " + (f"{len(changed)} changed: {changed}" if changed else "all identical"))
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
