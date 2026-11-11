"""Step 15 (advanced, lab only): NeuMF evaluated with exactly the same full-ranking protocol (spec 14.3).

Trained on train + validation positives, evaluated on the test split with the same 5,000 users as the
model comparison. Reported plainly even if it loses to ALS or SVD (Rendle et al., 2020).
"""
import json
import time

import numpy as np
import torch

from cinematch_engine.data.splits import load_split
from cinematch_engine.eval.protocol import evaluate_ranking, sample_eval_users, top_k
from cinematch_engine.models.ncf import train_ncf
from pipeline.common import ARTIFACTS, PROCESSED, SEED, get_logger, write_json
from pipeline.models_io import content_sim_for

log = get_logger("15_ncf")


def main() -> None:
    t0 = time.time()
    torch.set_num_threads(max(1, torch.get_num_threads()))
    data = load_split(PROCESSED, "test", train_parts=("train", "val"))
    users = sample_eval_users(data, 5000, SEED)
    model = train_ncf(data.train, log=log)
    model.eval()
    seen = [data.train.indices[data.train.indptr[u]:data.train.indptr[u + 1]] for u in users]
    recs = np.vstack([top_k(model.score_users(users[s:s + 200], data.n_items), seen[s:s + 200], 10)
                      for s in range(0, len(users), 200)])
    result = evaluate_ranking(recs, users, data, content_sim_for(data), 10)
    comparison = json.loads((ARTIFACTS / "metrics" / "test_comparison.json").read_text(encoding="utf-8"))["ranking"]
    write_json(ARTIFACTS / "lab" / "ncf.json", {
        "split": "test", "evaluated_users": int(len(users)), "ranking": result,
        "settings": {"gmf_dim": 32, "mlp": [64, 32, 16], "negatives_per_positive": 4, "epochs": 6, "lr": 0.002},
        "compare_ndcg": {k: comparison[k]["ndcg"]["mean"] for k in ("als", "svd", "item_cf", "hybrid_balanced") if k in comparison},
        "seconds": round(time.time() - t0, 1),
        "note": "Lab only: NCF learns one vector per training user and has no cheap fold-in, so it is never served."})
    log.info("NCF NDCG@10 %.4f (%.0fs)", result["ndcg"]["mean"], time.time() - t0)


if __name__ == "__main__":
    main()