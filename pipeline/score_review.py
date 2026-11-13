"""Score the blind human review of the Gemini tag pilot (run AFTER the review sheet is filled in).

    python -m pipeline.score_review                      # reads work/gemini-tag-pilot/review-sheet.csv

Each *_ok cell is right / wrong / unsure (r / w / u and y / n are accepted; empty = not reviewed). Correctness per tag
family = right / (right + wrong); unsure and empty cells are counted separately, never as right. A "(none)" tag (the
model abstained) that the reviewer marks right means "rightly left empty".

Pilot gate (screening, not proof): a family passes if human correctness >= 80% AND repeatability between the two
tags-only runs >= 80% (exact match for tone and pacing, mean Jaccard for mood and themes, from evaluation.json).
60 titles is a pilot gate, not proof that the tags are reliable across languages: with about 10 titles per language
group, one group's correctness has a 95% interval roughly +/- 25 points wide.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "work" / "gemini-tag-pilot"
FAMILIES = ("mood", "tone", "pacing", "themes")
GATE = 0.80
ANSWERS = {"right": "right", "r": "right", "y": "right", "yes": "right", "correct": "right",
           "wrong": "wrong", "w": "wrong", "n": "wrong", "no": "wrong", "incorrect": "wrong",
           "unsure": "unsure", "u": "unsure", "?": "unsure"}


def norm(cell: str):
    c = (cell or "").strip().lower()
    return ANSWERS.get(c) if c else None


def wilson(k: int, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def tally(rows: list, family: str) -> dict:
    v = [norm(r.get(f"{family}_ok", "")) for r in rows]
    right, wrong, unsure = v.count("right"), v.count("wrong"), v.count("unsure")
    judged = right + wrong
    return {"right": right, "wrong": wrong, "unsure": unsure, "not_reviewed": sum(x is None for x in v),
            "correctness": round(right / judged, 3) if judged else None, "ci95": wilson(right, judged)}


def repeatability(evaluation: dict, family: str):
    r = evaluation.get("repeatability", {}).get(family, {})
    return r.get("jaccard", r.get("exact"))


def score(sheet: list, mapping: dict, evaluation: dict) -> dict:
    out = {"families": {}, "by_group": {}, "gate": GATE,
           "note": "60 titles is a pilot gate, not proof of multilingual reliability."}
    for fam in FAMILIES:
        t = tally(sheet, fam)
        rep = repeatability(evaluation, fam)
        t["repeatability"] = rep
        t["passes_gate"] = bool(t["correctness"] is not None and rep is not None
                                and t["correctness"] >= GATE and rep >= GATE)
        out["families"][fam] = t
    groups: dict = {}
    for r in sheet:
        groups.setdefault(mapping.get(r["blind_id"], {}).get("group", "unknown"), []).append(r)
    for g, rows in sorted(groups.items()):
        out["by_group"][g] = {"films": len(rows), **{fam: tally(rows, fam) for fam in FAMILIES}}
    out["all_families_pass"] = all(v["passes_gate"] for v in out["families"].values())
    return out


def to_markdown(res: dict) -> str:
    lines = ["# Gemini tag pilot: human review", "",
             f"Gate: correctness and repeatability both >= {int(GATE * 100)}%. " + res["note"], "",
             "| Family | Right | Wrong | Unsure | Not reviewed | Correctness (95% CI) | Repeatability | Gate |",
             "|---|---|---|---|---|---|---|---|"]
    for fam, t in res["families"].items():
        c = "n/a" if t["correctness"] is None else f"{t['correctness']:.0%} [{t['ci95'][0]:.0%}, {t['ci95'][1]:.0%}]"
        rep = "n/a" if t["repeatability"] is None else f"{t['repeatability']:.0%}"
        lines.append(f"| {fam} | {t['right']} | {t['wrong']} | {t['unsure']} | {t['not_reviewed']} | {c} | {rep} | "
                     f"{'pass' if t['passes_gate'] else 'fail'} |")
    lines += ["", "By language group (revealed after the review):", "",
              "| Group | Films | Mood | Tone | Pacing | Themes |", "|---|---|---|---|---|---|"]
    for g, d in res["by_group"].items():
        cells = ["n/a" if d[f]["correctness"] is None else f"{d[f]['correctness']:.0%}" for f in FAMILIES]
        lines.append(f"| {g} | {d['films']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="review-sheet.csv", help="filled sheet inside work/gemini-tag-pilot/")
    ap.add_argument("--name", default="", help="suffix for the result files, e.g. 'claude'")
    ap.add_argument("--mapping", default="mapping-HIDDEN-until-review.csv", help="hidden language mapping")
    ap.add_argument("--evaluation", default="evaluation.json", help="file with the run-to-run repeatability")
    a = ap.parse_args()
    with (DIR / a.sheet).open(encoding="utf-8-sig") as fh:
        sheet = list(csv.DictReader(fh))
    with (DIR / a.mapping).open(encoding="utf-8") as fh:
        mapping = {r["blind_id"]: r for r in csv.DictReader(fh)}
    evaluation = json.loads((DIR / a.evaluation).read_text(encoding="utf-8"))
    res = score(sheet, mapping, evaluation)
    suffix = f"-{a.name}" if a.name else ""
    (DIR / f"review-results{suffix}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    (DIR / f"review-results{suffix}.md").write_text(to_markdown(res), encoding="utf-8")
    print(to_markdown(res))


if __name__ == "__main__":
    main()
