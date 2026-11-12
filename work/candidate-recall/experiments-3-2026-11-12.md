# Candidate experiments, round 3 (2026-11-12)

Harness: `pipeline/candidate_experiments_3.py` on `pipeline/candidate_recall.py`. Offline and read-only:
- Part D swaps the content source's scores for one call and rearranges lists in memory.
- Part G fits models **in memory**; nothing is written to `artifacts/models`.
- No change to the engine, served models, calibration, Match %, Neon or Render.

Raw numbers: `experiments-3-2026-11-12.json`.

## Summary

- **D (strongest-likes blend with a long-tail-aware guard): no arm wins under the strict rule.**
  - The new guard (D3) does what it was built for. In the Balanced mode the site serves, for established users, the
    language mix is unchanged, long-tail share rises (+1.3 pts) and distinct films hold at w 0.25.
  - **But NDCG@10 falls for established users.** At w 0.25: −0.0058, 95% CI [−0.0105, −0.0011]. At w 0.5: −0.0090,
    95% CI [−0.0137, −0.0043]. ILD also falls slightly.
  - Keeping the mix costs ranking quality, because the guard swaps lower-ranked films into the top 10.
  - For cold and warming users the blend does not raise non-MovieLens recall at all.
  - Verdict: the strongest-likes profile finds more films without MovieLens data (+6 to +15 pts in the pool for
    established users), but no version is safe to ship.
- **G (one shared cutoff, models retrained on ratings before it).**
  - With 400 users, every one of them active on both sides of 2017-07-09, pool recall is **17 / 18 / 25%**
    (cold / warming / established). The per-user split in #126 gave **32 / 35 / 41%**, so those figures are optimistic.
  - Most of the gap comes from the protocol, not leakage. On the same users and cutoff, the served models get
    20 / 20 / 29%, only 2.5 to 4.3 pts more than the honest cutoff-trained models. The rest comes from evaluating
    years of later likes (75 relevant films per user, against 29 in #126).
  - **Corrected statement:** under a strict global-time protocol, 75 to 83% of later-liked films never reach the
    pool, not 59 to 68%. The audit's conclusion ("most later-liked films never enter the pool") holds even more
    strongly.

## D. Blended strongest-likes profile, four arms × two weights

`content = (1 − w) · full-profile content + w · content from ratings ≥ 9`, with w = 0.25 or 0.5. Same 400 users,
seed 11, strict per-user temporal protocol as #126 to #129. Balanced mode, the one the site serves. Familiar is kept in
the JSON as a secondary column.

| Arm | Meaning |
|---|---|
| baseline | shipped |
| D1 | blend, no guard |
| D2 | blend + language/genre guard (as #129, with the guard's no-progress bug fixed) |
| D3 | blend + guard on language, genre, long tail and "rare" films |

**Long tail** uses the engine's existing definition: `cat.fame_pct < rerank.TAIL_PCT` (80), meaning outside the 20%
most-voted films of the catalog. It was reused, not invented.

**Distinct films** is a property of all users' lists together, so the guard protects a per-user proxy. A "rare" film
is one the baseline's Balanced top 10 shows to at most one user of that stage, or to nobody. Each user's list keeps at
least the baseline's count of long-tail and rare films. Its paired SE and CI come from a 1,000-resample user bootstrap.

**Strict acceptance (per stage, and every stage must pass):**
- Later-liked films without MovieLens data in the pool go up by more than 2 SE.
- Each of these stays within noise (> −2 SE) or improves: NDCG@10, ILD, long-tail share, distinct films, and the
  non-English, Hindi, Korean and Japanese top-10 shares.

**Established users (Balanced).** Δ is paired against baseline, with the 95% CI in brackets. Baseline: non-ML in pool
20.9%, NDCG@10 0.1589, long-tail share 20.0%, non-English 15.7%, Hindi 0.93%, 1,106 distinct films.

| Arm | Non-ML in pool Δ | NDCG@10 Δ | ILD Δ | Long tail Δ | Non-English Δ | Hindi Δ | Distinct Δ | Stage verdict |
|---|---|---|---|---|---|---|---|---|
| D1 0.25 | +6.2 pts [3.4, 9.0] | −0.0004 [−0.003, 0.003] | **−0.0166** | 0 | **−6.8 pts** | **−0.90 pts** | **−95** | fail: ILD, language, distinct |
| D2 0.25 | +6.2 pts | +0.0005 [−0.004, 0.005] | **−0.0019** | **−3.0 pts** | 0 | −0.10 | **−112** | fail: ILD, tail, distinct |
| **D3 0.25** | +6.2 pts | **−0.0058 [−0.0105, −0.0011]** | **−0.0013** | **+1.3 pts** | 0 | −0.03 | +5 [−10, +20] | fail: NDCG, ILD |
| D1 0.5 | +14.7 pts [11.0, 18.3] | −0.0015 [−0.005, 0.002] | **−0.0197** | 0 | **−7.9 pts** | **−0.93 pts** | **−175** | fail: ILD, language, distinct |
| D2 0.5 | +14.7 pts | −0.0038 [−0.008, 0.000] | **−0.0028** | **−3.0 pts** | 0 | −0.03 | **−150** | fail: ILD, tail, distinct |
| **D3 0.5** | +14.7 pts | **−0.0090 [−0.0137, −0.0043]** | **−0.0021** | **+1.3 pts** | 0 | −0.03 | **−27 [−43, −11]** | fail: NDCG, ILD, distinct |

**Warming (Balanced).** Non-ML recall rises only +1.7 to +2.0 pts (SE 1.0 to 1.2), under 2 SE, so every arm fails.
- D1 loses 0.5 to 0.7 pts of non-English share.
- D2 loses 1.0 to 1.6 pts of long-tail share.
- D3 keeps language and long tail (+0.4 to +0.5 pts tail) and raises distinct films (+44 to +46). But NDCG moves −0.0015
  and −0.0007 (within noise), and ILD falls about 0.001 (3 SE).

**Cold (Balanced).** With 2 ratings the blend changes almost nothing. Non-ML recall moves −0.6 to −0.7 pts, so every
arm fails on the first condition. D3 is otherwise neutral to positive: distinct films +22 to +27, long tail flat,
language unchanged.

Note: D2's numbers differ from #129 because #129's guard had a no-progress bug, fixed here. Its tail loss is larger
now (−3.0 pts vs −1.6) because the fixed guard makes more swaps.

Reading:
- The long-tail-aware guard solves the side effects the brief named (language, long tail, distinct films), but at the
  price of ranking quality for established users. NDCG falls 0.006 to 0.009, about 4 to 6% of baseline, and both
  95% CIs exclude 0.
- Every guarded swap puts a lower-scored film in place of a higher-scored one. So a list-level guard cannot make this
  profile change free. A version worth trying would change how the strong-likes candidates are scored, rather than
  fixing the list afterwards.

## G. Shared global cutoff with models trained before it

- **Cutoff choice:** of ten candidate dates (the 50th to 95th percentiles of rating time), 2017-07-09 gives the most
  usable users. That is 1,250 users with ≥ 11 ratings before it and ≥ 1 eligible positive after it. Counts by date are
  in the JSON (784 to 1,250).
- **Training:** every source model was fitted in memory on the 3,258,895 MovieLens ratings before the cutoff. They use
  the same tuned settings and the served item space (9,495 films), in 46 s. Hybrid weights, calibration and the
  availability map are the served ones, which were tuned on the per-user split. Treat that as a small remaining
  difference.
- **Users and labels:** 400 users sampled from the 1,250 (seed 11). Profile = the 2 / 6 / all most recent ratings
  before the cutoff. Relevant = eligible unseen films rated ≥ 7 after it, including hold-out films. Mean relevant per
  user: 74.6.

| Stage | Models | Pool recall (SE) | R@50 | R@100 | R@200 | NDCG@10 balanced | NDCG@10 familiar |
|---|---|---|---|---|---|---|---|
| Cold | **trained before cutoff** | **17.1% (0.9)** | 6.0% | 9.6% | 15.1% | 0.041 | 0.053 |
| | served (saw post-cutoff data) | 19.6% (1.0) | 6.8% | 10.2% | 17.4% | 0.049 | 0.059 |
| Warming | **trained before cutoff** | **17.6% (0.9)** | 5.6% | 9.2% | 15.0% | 0.053 | 0.064 |
| | served | 20.5% (1.0) | 6.3% | 10.6% | 17.1% | 0.065 | 0.079 |
| Established | **trained before cutoff** | **24.7% (1.0)** | 11.3% | 14.5% | 21.6% | 0.177 | 0.207 |
| | served | 29.0% (1.1) | 11.6% | 15.0% | 24.4% | 0.183 | 0.215 |
| #126, per-user split (reference) | served | 32.4 / 34.9 / 41.4% | | | | | |

Reading:
- **The 32 / 35 / 41% figures are not confirmed. They are optimistic.** Under a clean global-time protocol the pool
  holds 17 to 25% of later-liked films.
- **Leakage explains only a small part.** On the same users the served models score 2.5 to 4.3 pts higher. The
  per-user split also sees each user's own later ratings in the CF models' item factors through other users, but
  that effect is small.
- **Most of the gap is the target set.** Here each user has years of later likes (74.6 on average vs 28.6). Films liked
  long after the cutoff are harder to predict, and many were released after it.
- **The direction of every earlier conclusion holds.** Most later-liked films never reach the pool, and ALS-driven
  established users are retrieved best. Only the size changes: worse than #126 said.

## What MovieLens cannot judge

- Hindi and Indian films (6 relevant in the D sample).
- Series and anime.
- Most films without MovieLens data (only the 500 hold-out films can be hits).
- Real-user behaviour on FlickRaven.

## Recommendation

1. Do not ship any strongest-likes arm.
2. Correct the recall headline in docs to the global-cutoff figures, about 17 / 18 / 25% pool recall, and keep #126's
   per-user numbers as the per-user-split view.
3. Any future retrieval change should be judged on the global-cutoff protocol too. `run_g` can be reused for that.
