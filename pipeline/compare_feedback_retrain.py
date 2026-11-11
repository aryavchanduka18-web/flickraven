"""Judge a retrain that used live site feedback: ship it or keep the old models.

Run by scripts\\retrain_with_feedback.ps1 after steps 9-11 were repeated with FLICKRAVEN_SITE_FEEDBACK=1.
It compares the new test_comparison.json with the copy saved before the retrain. Both were measured on the SAME
held-out MovieLens ratings (site ratings only join training), so the numbers are comparable.

Rule: ship only if the hybrid's NDCG@10 did not drop by more than MAX_DROP. A rise inside the confidence interval
is reported as "no measurable change", never as an improvement. With a handful of site users this is the expected
outcome: their ratings are a tiny share of the millions in MovieLens.

    python -m pipeline.compare_feedback_retrain <before.json> <after.json>
Exit code 0 = safe to ship, 1 = keep the old models.
"""
import sys
from pathlib import Path

from pipeline.common import PROCESSED, read_json

MAX_DROP = 0.003
MODELS = ("hybrid_balanced", "als", "svd", "item_cf", "user_cf", "popularity", "content")


def verdict(before: dict, after: dict) -> tuple[bool, str, dict]:
    rows = {}
    for name in MODELS:
        b, a = before["ranking"].get(name), after["ranking"].get(name)
        if b and a:
            rows[name] = {"before": b["ndcg"]["mean"], "after": a["ndcg"]["mean"], "delta": a["ndcg"]["mean"] - b["ndcg"]["mean"],
                          "after_ci": [a["ndcg"]["ci_low"], a["ndcg"]["ci_high"]], "before_ci": [b["ndcg"]["ci_low"], b["ndcg"]["ci_high"]]}
    h = rows.get("hybrid_balanced")
    if h is None:
        return False, "The hybrid is missing from one of the files, so nothing can be compared. Keep the old models.", rows
    if h["delta"] < -MAX_DROP:
        return False, f"Hybrid NDCG@10 fell by {-h['delta']:.4f} (limit {MAX_DROP}). Keep the old models.", rows
    overlap = not (h["after_ci"][0] > h["before_ci"][1] or h["after_ci"][1] < h["before_ci"][0])
    if h["delta"] > 0 and not overlap:
        return True, f"Hybrid NDCG@10 rose by {h['delta']:.4f}, outside the confidence intervals. Safe to ship.", rows
    return True, (f"Hybrid NDCG@10 changed by {h['delta']:+.4f}, inside the confidence intervals: no measurable change. "
                  "Safe to ship, but do not call it an improvement."), rows


def main(argv: list[str]) -> int:
    before, after = read_json(Path(argv[0])), read_json(Path(argv[1]))
    site = PROCESSED / "site_feedback" / "ratings.parquet"
    if site.exists():
        import pandas as pd
        df = pd.read_parquet(site, columns=["user_id", "rating"])
        print(f"Site feedback used: {len(df)} ratings from {df['user_id'].nunique()} site users.")
    ok, text, rows = verdict(before, after)
    for name, r in rows.items():
        print(f"{name:16s} NDCG@10 {r['before']:.4f} -> {r['after']:.4f}  ({r['delta']:+.4f})")
    print("\n" + text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
