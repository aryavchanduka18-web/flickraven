"""Check the Gemini similarity file before it is exported and uploaded, and stamp it.

    python -m pipeline.ai_similar_check --limit 6000            # report only; exit code 1 if a blocking check fails
    python -m pipeline.ai_similar_check --limit 6000 --finalize # also clean duplicates/self-links and write the metadata

Run it after the full `python -m pipeline.ai_similar --limit 6000` run (use the same --limit). All counts come from the
real database, none are typed in. The report is also written to artifacts/metrics/ai_similar_report.json.
Optional: --previous path/to/older/ai_similar.json to prove no earlier good edges were lost (copy the file before a
re-run: `copy artifacts\\models\\ai_similar.json artifacts\\models\\ai_similar.prev.json`).

What is checked, and where:
 1 Every eligible seed (the --limit most-voted series and anime) is in the file; missing seeds are listed and block.
 2 Language table (Hindi, Tamil, Telugu, Malayalam, Bengali, other): catalogue titles, seeds processed, seeds with at
   least one suggestion found in the catalog. A language under 50% processed is a warning.
 3 Every suggestion found in the catalog: reported as a rate (the rest are real shows we do not stock, dropped at
   match time, not an error). Seeds with suggestions but none found are listed.
 4 No films in series neighbourhoods: enforced at match time (the site only matches series and anime). Here: how many
   suggestions would only match a film (informational) and none can ever show.
 5 Anime and live action: by design they share one pool (a Death Note fan can get live-action crime dramas). Reported:
   share of cross-kind suggestions.
 6 No loss versus --previous: seeds lost block; edges lost are reported.
 7 Duplicates and self-links: block until --finalize removes them.
 8 Metadata (generated date, model, catalogue version, checksum): added by --finalize, verified here.
"""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import date

from sqlalchemy import create_engine, text

from pipeline.ai_similar import OUT, load, save
from pipeline.common import ARTIFACTS, env, get_logger, write_json

log = get_logger("ai_similar_check")
NAME = re.compile(r"^(.+?)\s*\((\d{4})\)$")
LANGS = {"hi": "Hindi", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam", "bn": "Bengali"}
SHOW = ("series", "anime")


def group(lang: str | None) -> str:
    return LANGS.get(lang or "", "Other")


def checksum(titles: dict) -> str:
    return hashlib.sha256(json.dumps(titles, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def catalogue_version(rows: list[dict]) -> str:
    return hashlib.sha256(",".join(str(t) for t in sorted(r["tmdb_id"] for r in rows if r["title_type"] in SHOW)).encode()).hexdigest()[:12]


def parse(n: str) -> tuple[str, int] | None:
    m = NAME.match(n.strip())
    return (m.group(1).strip(), int(m.group(2))) if m else None


def build_index(rows: list[dict]) -> dict[str, list[dict]]:
    """lower(title) -> catalog rows, most voted first (the same tie-break as the site)."""
    idx: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: -(r["votes"] or 0)):
        idx[r["title"].lower()].append(r)
    return idx


def resolve(idx, name: str, year: int, kinds=SHOW) -> dict | None:
    """The site's rule: same title (case-insensitive), a series or anime, first-air year within one."""
    for r in idx.get(name.lower(), []):
        if r["title_type"] in kinds and (r["year"] is None or abs(r["year"] - year) <= 1):
            return r
    return None


def clean_titles(titles: dict, by_tmdb: dict) -> tuple[dict, int, int]:
    """(titles without duplicates and self-links, duplicates removed, self-links removed)."""
    out, dups, selfs = {}, 0, 0
    for tid, names in titles.items():
        seed = by_tmdb.get(int(tid))
        seen, keep = set(), []
        for n in names:
            key = n.strip().lower()
            p = parse(n)
            if key in seen:
                dups += 1
            elif seed and p and p[0].lower() == seed["title"].lower() and seed["year"] is not None and abs(p[1] - seed["year"]) <= 1:
                selfs += 1
            else:
                seen.add(key)
                keep.append(n.strip())
        if keep:
            out[tid] = keep
    return out, dups, selfs


def analyze(rows: list[dict], file: dict, previous: dict | None, limit: int) -> dict:
    """The whole report from plain data (rows: tmdb_id, title, year, title_type, original_language, votes)."""
    titles = file.get("titles", {})
    shows = [r for r in rows if r["title_type"] in SHOW]
    by_tmdb = {r["tmdb_id"]: r for r in shows}
    idx = build_index(rows)
    eligible = sorted(shows, key=lambda r: -(r["votes"] or 0))[:limit]
    missing = [r for r in eligible if str(r["tmdb_id"]) not in titles]

    table = {g: {"catalogue": 0, "eligible": 0, "processed": 0, "matched": 0} for g in [*LANGS.values(), "Other"]}
    for r in shows:
        table[group(r["original_language"])]["catalogue"] += 1
    for r in eligible:
        table[group(r["original_language"])]["eligible"] += 1
    asked = found = film_only = cross = unknown_seed = 0
    no_match = []
    for tid, names in titles.items():
        seed = by_tmdb.get(int(tid))
        if seed is None:
            unknown_seed += 1
            continue
        t = table[group(seed["original_language"])]
        t["processed"] += 1
        hit = 0
        for n in names:
            p = parse(n)
            if not p:
                continue
            asked += 1
            r = resolve(idx, *p)
            if r:
                found += 1
                hit += 1
                cross += (r["title_type"] == "anime") != (seed["title_type"] == "anime")
            elif resolve(idx, *p, kinds=("movie",)):
                film_only += 1
        if hit:
            t["matched"] += 1
        elif names:
            no_match.append(seed["title"])
    dups = selfs = 0
    _, dups, selfs = clean_titles(titles, by_tmdb)

    lost_seeds = lost_edges = 0
    if previous:
        for tid, names in previous.get("titles", {}).items():
            if tid not in titles:
                lost_seeds += 1
            else:
                now = {n.strip().lower() for n in titles[tid]}
                lost_edges += sum(1 for n in names if n.strip().lower() not in now)

    meta = file.get("meta") or {}
    meta_ok = bool(meta) and all(meta.get(k) for k in ("generated", "model", "catalogue", "checksum")) and meta.get("checksum") == checksum(titles)
    checks = {
        "1 every eligible seed processed": ("PASS" if not missing else "FAIL", f"{len(eligible) - len(missing)} of {len(eligible)}; missing {len(missing)}"
                                            + (": " + ", ".join(r["title"] for r in missing[:8]) if missing else "")),
        "2 Indian-language coverage": ("PASS" if all(t["eligible"] == 0 or t["processed"] / t["eligible"] >= 0.5 for g, t in table.items() if g != "Other") else "WARN",
                                       "see the table (a language under 50% of its eligible seeds processed is a warning)"),
        "3 suggestions found in the catalog": ("PASS" if not no_match else "WARN", f"{found} of {asked} ({(100 * found / asked if asked else 0):.0f}%); "
                                               f"{len(no_match)} seeds with suggestions but none found" + (": " + ", ".join(no_match[:6]) if no_match else "")),
        "4 no films in series lists": ("PASS", f"enforced at match time (series and anime only); {film_only} suggestions only match a film and are dropped"),
        "5 anime and live action": ("PASS", f"one shared pool by design; {cross} of {found} found suggestions cross between anime and live action"),
        "6 nothing lost versus the previous file": (("PASS" if lost_seeds == 0 else "FAIL") if previous else "SKIP",
                                                     f"{lost_seeds} seeds and {lost_edges} suggestions missing now" if previous else "no --previous file given"),
        "7 no duplicates or self-links": ("PASS" if dups + selfs == 0 else "FAIL", f"{dups} duplicates, {selfs} self-links (--finalize removes them)"),
        "8 metadata and checksum": ("PASS" if meta_ok else "FAIL", f"{meta}" if meta_ok else "missing or stale (--finalize writes it)"),
    }
    return {"table": table, "checks": checks, "seeds_in_file": len(titles), "not_in_catalogue": unknown_seed,
            "ok": all(v[0] in ("PASS", "WARN", "SKIP") for v in checks.values())}


def finalize(file: dict, rows: list[dict], limit: int) -> dict:
    by_tmdb = {r["tmdb_id"]: r for r in rows if r["title_type"] in SHOW}
    titles, dups, selfs = clean_titles(file["titles"], by_tmdb)
    file["titles"] = titles
    file["meta"] = {"generated": str(date.today()), "model": file.get("model", "unknown"), "catalogue": catalogue_version(rows),
                    "seeds": len(titles), "limit": limit, "checksum": checksum(titles)}
    log.info("finalized: removed %d duplicates and %d self-links; %d seeds", dups, selfs, len(titles))
    return file


def print_report(rep: dict) -> None:
    print(f"\n{'Language':<11}{'Catalogue':>10}{'Eligible':>10}{'Processed':>11}{'Matched':>9}")
    for g, t in rep["table"].items():
        print(f"{g:<11}{t['catalogue']:>10}{t['eligible']:>10}{t['processed']:>11}{t['matched']:>9}")
    print()
    for name, (status, note) in rep["checks"].items():
        print(f"[{status:<4}] {name}: {note}")
    print("\nREADY TO EXPORT" if rep["ok"] else "\nNOT READY: fix the FAIL lines, then run again")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2500, help="the same --limit as the ai_similar run")
    ap.add_argument("--previous", help="an older ai_similar.json, to prove nothing was lost")
    ap.add_argument("--finalize", action="store_true")
    a = ap.parse_args()
    db = create_engine(env("DATABASE_URL", "postgresql+psycopg://cinematch:cinematch@localhost:5432/cinematch"))
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(text("""SELECT tmdb_id, title, year, title_type, original_language, tmdb_vote_count AS votes
                                                   FROM movies WHERE title_type IN ('series', 'anime', 'movie')""")).mappings()]
    file = load()
    previous = json.loads(open(a.previous, encoding="utf-8").read()) if a.previous else None
    if a.finalize:
        file = finalize(file, rows, a.limit)
        save(file)
    rep = analyze(rows, file, previous, a.limit)
    print_report(rep)
    write_json(ARTIFACTS / "metrics" / "ai_similar_report.json", rep)
    if not rep["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
