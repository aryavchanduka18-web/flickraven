"""Compare two anime_rank_eval runs on the users they share (for example 7+ and 8+ relevance).

    python -m pipeline.anime_compare work/anime-rank-eval-2023-final work/anime-rank-eval-2023-like8

Reads per_user_test.csv of both runs. For each list and scenario: users in each run, users in both, and on the common
users the mean NDCG@10 of today and of the served rule with the paired difference and a 95% interval, per run. Also
the share of users per tier (none, short 1-7, mid 8-24, long 25+ liked anime the model knows) in each run.
"""
import sys

import numpy as np
import pandas as pd


def ci(d):
    se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else 0.0
    return [round(float(d.mean() - 1.96 * se), 4), round(float(d.mean() + 1.96 * se), 4)]


def main() -> None:
    a, b = (pd.read_csv(f"{p}/per_user_test.csv") for p in sys.argv[1:3])
    for (lst, scen), ga in a.groupby(["list", "scenario"]):
        gb = b[(b["list"] == lst) & (b["scenario"] == scen)]
        common = sorted(set(ga["uid"]) & set(gb["uid"]))
        print(f"## {lst}/{scen}: users {len(ga)} vs {len(gb)}, common {len(common)}")
        for name, g in (("A", ga), ("B", gb)):
            c = g[g["uid"].isin(common)]
            d = c["served"] - c["today"]
            print(f"  {name} common: today {c['today'].mean():.4f} served {c['served'].mean():.4f} diff {d.mean():+.4f} {ci(d)}")
            shares = (g["tier"].value_counts(normalize=True).round(3)).to_dict()
            print(f"  {name} tiers (all users of this run): {shares}")


if __name__ == "__main__":
    main()
