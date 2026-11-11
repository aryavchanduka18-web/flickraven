"""Readable validation tables: docs/phase-3-results.md (baselines) and docs/phase-4-results.md (MF)."""
import json

from pipeline.common import ARTIFACTS, ROOT

NAMES = {"hybrid_blend": "Hybrid (blend, no rerank)", "hybrid_familiar": "Hybrid, Familiar", "hybrid_balanced": "Hybrid, Balanced",
         "hybrid_discover": "Hybrid, Discover", "bias": "Bias baseline", "popularity": "Popularity", "content": "Content-based",
         "user_cf": "User CF", "item_cf": "Item CF", "svd": "Funk SVD", "als": "Implicit ALS"}


def ci(m: dict, digits: int = 4) -> str:
    return f"{m['mean']:.{digits}f} [{m['ci_low']:.{digits}f}, {m['ci_high']:.{digits}f}]"


def table(models: dict) -> list[str]:
    lines = ["| Model | P@10 | R@10 | MAP@10 | NDCG@10 | MAE | RMSE |", "|---|---|---|---|---|---|---|"]
    for key, r in models.items():
        rk, rt = r.get("ranking"), r.get("ratings")
        cells = [ci(rk[m]) if rk else "n/a" for m in ("precision", "recall", "map", "ndcg")]
        cells += [ci(rt[m], 3) if rt else "n/a" for m in ("mae", "rmse")]
        lines.append(f"| {NAMES[key]} | " + " | ".join(cells) + " |")
    lines += ["", "| Model | Coverage | Intra-list diversity | Novelty (bits) | Long-tail share | Mean popularity percentile |",
              "|---|---|---|---|---|---|"]
    for key, r in models.items():
        rk = r.get("ranking")
        if rk:
            lines.append(f"| {NAMES[key]} | {100 * rk['coverage']:.1f}% | {rk['diversity']['mean']:.3f} | "
                         f"{rk['novelty']['mean']:.2f} | {rk['long_tail_share']:.1f}% | {rk['mean_popularity_percentile']:.1f} |")
    lines += ["", "| Model | Tuned settings | Runtime (s) |", "|---|---|---|"]
    for key, r in models.items():
        settings = ", ".join(f"{k}={v}" for k, v in r["settings"].items() if not isinstance(v, dict))
        lines.append(f"| {NAMES[key]} | {settings} | {r.get('runtime_seconds', '')} |")
    return lines


def write(src: str, dest: str, title: str, intro: list[str]) -> None:
    path = ARTIFACTS / "metrics" / src
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = [f"# {title}", "", *intro, "",
             f"Validation split, {data['evaluated_users']:,} evaluated users (fixed sample, seed 42), full ranking over "
             f"{data['universe_films']:,} part-A films, relevant = rating >= {data['relevant_threshold']}/10. "
             "Brackets are 95% bootstrap confidence intervals over users. The test split is not used yet.", "",
             *table(data["models"]), "",
             f"Peak memory of the run: {data['peak_memory_mb']:,} MB.", ""]
    checks = {k: v["fold_in_check"] for k, v in data["models"].items() if "fold_in_check" in v}
    if checks:
        lines += ["## Fold-in check", "",
                  "A few users are removed from training, the model is retrained, and the users are folded back in "
                  "from their own ratings. Compared with the model that saw them in training:", "",
                  "| Model | Users | Top-10 overlap | NDCG@10 full training | NDCG@10 fold-in | RMSE full | RMSE fold-in |",
                  "|---|---|---|---|---|---|---|"]
        for k, c in checks.items():
            lines.append(f"| {NAMES[k]} | {c['users']} | {100 * c['top10_overlap']:.0f}% | {c['ndcg_full_training']:.4f} | "
                         f"{c['ndcg_fold_in']:.4f} | {c.get('rmse_full_training', 'n/a') if isinstance(c.get('rmse_full_training'), str) else format(c.get('rmse_full_training', float('nan')), '.3f')} | "
                         f"{format(c.get('rmse_fold_in', float('nan')), '.3f') if 'rmse_fold_in' in c else 'n/a'} |")
        lines.append("")
    (ROOT / "docs" / dest).write_text("\n".join(lines), encoding="utf-8")


def load(name):
    p = ARTIFACTS / "metrics" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def phase5() -> None:
    h = load("validation_hybrid")
    if not h:
        return
    lines = ["# Phase 5 results: hybrid engine", "",
             "Generated from `artifacts/metrics/validation_hybrid.json`. Validation split, simulated users "
             f"({h['users']:,}): onboarding = 5 earliest films rated 8+, cold = onboarding + 0-2 ratings, "
             "warming = onboarding + 3-10, established = full history.", "",
             "## Tuned blend weights per stage", "", "| Stage | Popularity | Content | Item CF | User CF | SVD | ALS | NDCG@10 |",
             "|---|---|---|---|---|---|---|---|"]
    for stage, v in h["stages"].items():
        w = v["weights"]
        lines.append(f"| {stage} | " + " | ".join(f"{w.get(s, 0):.1f}" for s in ("popularity", "content", "item_cf", "user_cf", "svd", "als"))
                     + f" | {v['ndcg_at_10_tuning']:.4f} |")
    lines += ["", "## Match % calibration (fitted on validation)", "", "| Stage | Pairs | Share rated 7+ | ECE | Match % range |", "|---|---|---|---|---|"]
    for stage, v in h["stages"].items():
        c = v["calibration"]
        lines.append(f"| {stage} | {c['pairs']:,} | {100 * c['base_rate']:.1f}% | {c['ece']:.4f} | {c['match_pct_range'][0]}-{c['match_pct_range'][1]}% |")
    est = h["stages"]["established"]
    lines += ["", "## Discovery Modes (established users)", "", "| Mode | NDCG@10 | Intra-list diversity | Coverage |", "|---|---|---|---|"]
    for mode in ("familiar", "balanced", "discover"):
        r = est.get(f"ranking_{mode}")
        if r:
            lines.append(f"| {mode} | {ci(r['ndcg'])} | {r['diversity']['mean']:.3f} | {100 * r['coverage']:.1f}% |")
    (ROOT / "docs" / "phase-5-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def phase6() -> None:
    t = load("test_comparison")
    if not t:
        return
    lines = ["# Phase 6 results: final evaluation and experiments", "",
             "Generated from `artifacts/metrics/*.json`. Models retrained on train + validation with the tuned "
             f"settings; evaluated once on the test split ({t['evaluated_users']:,} users, full ranking over "
             f"{t['universe_films']:,} films). Brackets: 95% bootstrap CIs.", "", "## 1. Model comparison (test split)", ""]
    lines += table({k: {"ranking": v, "settings": {}} for k, v in t["ranking"].items()})[:2 + len(t["ranking"])]
    lines += ["", "RMSE on test: " + ", ".join(f"{NAMES[k]} {ci(v['rmse'], 3)}" for k, v in t["ratings"].items()), ""]
    g = load("global_cutoff")
    if g:
        lines += ["## 6. Global time-cutoff check", "", f"Same comparison on the global time split ({g['evaluated_users']:,} users).", ""]
        lines += table({k: {"ranking": v, "settings": {}} for k, v in g["ranking"].items()})[:2 + len(g["ranking"])]
        lines.append("")
    c = load("cold_start")
    if c:
        models = ["hybrid_balanced", "popularity", "content", "item_cf", "user_cf", "svd", "als"]
        lines += ["## 2. Cold-start users (NDCG@10)", "", "| k | onboarding | " + " | ".join(NAMES[m] for m in models) + " |",
                  "|---|---|" + "---|" * len(models)]
        for k in c["k_values"]:
            for ob in ("without", "with"):
                r = c["results"][f"k{k}_{ob}_onboarding"]
                lines.append(f"| {k} | {ob} | " + " | ".join(f"{r[m]:.4f}" for m in models) + " |")
        lines.append("")
    n = load("new_movies")
    if n:
        lines += ["## 3. New movies (hit rate@50 on held-out films)", "", "| Model | Hit rate@50 |", "|---|---|"]
        lines += [f"| {NAMES.get(k, k)} | {100 * v['hit_rate_at_50']:.2f}% |" for k, v in n["results"].items()]
        lines += ["", f"Random top-50 baseline: {100 * n['random_baseline_hit_rate']:.2f}%. {n['users']:,} users, "
                      f"{n['liked_pairs']:,} (user, held-out film rated 7+) pairs.", ""]
    d = load("diversity")
    if d:
        lines += ["## 4. Diversity trade-off", "", "| lambda | NDCG@10 | Intra-list diversity |", "|---|---|---|"]
        lines += [f"| {p['lambda']:.2f} | {p['ndcg']:.4f} | {p['diversity']:.3f} |" for p in d["sweep"]]
        lines += ["", "Modes: " + ", ".join(f"{m} (NDCG {v['ndcg']:.4f}, diversity {v['diversity']:.3f})" for m, v in d["modes"].items()), ""]
    k = load("calibration_check")
    if k:
        lines += ["## 5. Calibration check (test split)", "", "| Stage | Pairs | ECE | Passes (ECE < 0.05) | Mean Match % |", "|---|---|---|---|---|"]
        lines += [f"| {s} | {v['pairs']:,} | {v['ece']:.4f} | {'yes' if v['passes'] else 'no'} | {v['mean_match_pct']:.0f}% |" for s, v in k["stages"].items()]
        lines.append("")
    (ROOT / "docs" / "phase-6-results.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    write("validation_baselines.json", "phase-3-results.md", "Phase 3 results: baseline models",
          ["Generated from `artifacts/metrics/validation_baselines.json` by `pipeline/report_validation.py`."])
    write("validation_mf.json", "phase-4-results.md", "Phase 4 results: matrix factorization",
          ["Generated from `artifacts/metrics/validation_mf.json` by `pipeline/report_validation.py`."])
    phase5()
    phase6()


if __name__ == "__main__":
    main()