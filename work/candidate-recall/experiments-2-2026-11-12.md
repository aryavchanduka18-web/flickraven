# Candidate experiments, round 2 (2026-11-12)

Harness: `pipeline/candidate_experiments_2.py`, on `pipeline/candidate_recall.py`. Read-only.
- Arms swap the content source's scores for one `top_picks` call, or rearrange or build lists in memory.
- No change to the engine, models, calibration, Match %, Neon or Render.

Setup:
- Same 400 users and seed (11) as before.
- Strict temporal protocol; the stages are cold (2 ratings), warming (6) and established (all).
- Paired per user, with standard errors (SE) in brackets.

Raw numbers: `experiments-2-2026-11-12.json`. Runtime 7 min.

## Summary

- **D (strongest-likes content mixed with the full profile).** It finds many more later-liked films without
  MovieLens data. For established users, those films' recall in the pool goes up +6.2 pts (w 0.25) and +14.7 pts
  (w 0.5), from 20.9%.
  - In **Familiar mode** (no tail channel), D2 with the mix guard passes the full win rule. So does D1 at w 0.25.
  - In **Balanced, the shipped mode**, every D arm fails:
    - Without the guard (D1), the non-English top-10 share falls 15.7% → 8 to 9% and Hindi falls to about 0. That is
      the same problem as round 1, only smaller.
    - With the guard (D2), the language mix holds, but long-tail share falls 1.6 pts (4.6 SE), distinct films fall
      8 to 12%, and at w 0.5 NDCG@10 falls 0.005 (2.3 SE).
  - **Not shippable as is.** The guard works for language and genre but takes slots from the long-tail channel. A
    next version would guard long-tail share too.
- **E ("recent for you" row).**
  - Top Picks today shows almost no recent films: 1 to 4% of the recent films a user later likes, and 0.9 to
    1.6 recent films per top 10.
  - A separate recent row shows 11 to 16% of them. That is +0.10 to +0.12 over Top Picks, SE 0.013, about 9 SE.
  - **But the plain most-popular-recent row shows more** (15 to 19%) on MovieLens.
  - The personalised row is far more international than the popular row. For established users: non-English 29.7%
    vs 10.6%, Hindi 0.56% vs 0%, films without MovieLens data 37% vs 16%. MovieLens cannot score most of those, and
    its targets lean popular.
  - **A recent row is clearly worth having. Which ranking to use cannot be settled on MovieLens.**
- **C (one global cutoff, 2018-08-14): inconclusive.** Only 15 of the 400 sampled users have training ratings on both
  sides of the cutoff. Their pool recall is 20 / 21 / 14%, but 15 users with long horizons (66 relevant films each)
  cannot confirm or refute the 32 / 35 / 41% per-user-split numbers. A proper check needs users sampled for activity
  across the cutoff and, ideally, models trained only up to it. Neither exists yet.

## D. Blended strongest-likes content profile

`content = (1 − w) · full-profile content + w · content from ratings ≥ 9`, with w = 0.25 or 0.5. D2 adds the mix
guard: the top 10 must keep at least the baseline's count of English, non-English, Hindi, Korean, Japanese and each
primary genre.

Win rule (from the brief): all of these must hold.
- Later-liked films without MovieLens data in the pool go up (> 2 SE).
- NDCG@10 does not get worse (> −2 SE).
- ILD, long-tail share and the non-English, Hindi, Korean and Japanese top-10 shares stay within 2 SE of baseline.
- Distinct films stay within 5%.

**Established users.** Baseline: films without MovieLens data in the pool 20.9%; NDCG@10 0.1589 balanced / 0.1844
familiar; non-English top-10 share 15.7% (balanced); Hindi 0.93%; 1,106 distinct films (balanced).

| Arm | Non-ML in pool (Δ) | R@50 | Mode | ΔNDCG@10 | ΔILD | ΔLong tail | Non-English (Δ) | Hindi | Distinct | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 0.25 | 27.1% (+6.2, SE 1.4) | 23.2% | familiar | 0.0000 (0.0009) | −0.0003 | 0 | 6.3% (−0.05) | 0 | 653 | **win** |
| | | | balanced | −0.0004 (0.0015) | **−0.0166 (0.0009)** | 0 | **8.9% (−6.8)** | **0.03%** | **1,011** | no: mix, distinct |
| D1 0.5 | 35.6% (+14.7, SE 1.9) | 24.4% | familiar | −0.0007 (0.0013) | −0.0002 | 0 | 6.2% (−0.13) | 0 | 652 | no: mix |
| | | | balanced | −0.0015 (0.0018) | **−0.0197** | 0 | **7.8% (−7.9)** | **0%** | **931** | no: mix, distinct |
| D2 0.25 | 27.1% (+6.2) | 23.2% | familiar | +0.0001 (0.0008) | 0.0000 | 0 | 6.3% (0) | 0 | 652 | **win** |
| | | | balanced | −0.0008 (0.0020) | −0.0020 (0.0004) | **−0.0156 (0.0034)** | 15.4% (−0.4) | 0.88% | **1,016** | no: mix, distinct |
| D2 0.5 | 35.6% (+14.7) | 24.4% | familiar | −0.0004 (0.0011) | −0.0001 | 0 | 6.3% (0) | 0 | 651 | **win** |
| | | | balanced | **−0.0048 (0.0021)** | −0.0031 (0.0004) | **−0.0156 (0.0032)** | 15.2% (−0.6) | 0.90% | **976** | no: NDCG, mix, distinct |

- **Warming:** non-ML recall +1.7 to +2.0 pts (SE 1.0 to 1.2), under 2 SE. Every arm fails. In balanced mode D1
  loses 0.5 to 0.7 pts of non-English share. D2 keeps the language mix but loses 0.7 to 1.0 pts of long-tail share.
- **Cold:** with only 2 ratings, D barely changes anything (non-ML recall −0.6 pts). Every arm fails.

Reading:
- The familiar-mode "wins" are retrieval wins. NDCG is unchanged and the familiar top 10 stays very English (6%
  non-English) whatever happens.
- In the shipped balanced mode, the guard restores the language mix. But the guard puts the swapped-in film in the
  lowest positions, and those are often the long-tail channel's reserved slots. So long-tail share and distinct films
  fall.
- A next version should count "long tail" as a guarded group, or protect tail slots from swaps. Then rerun.

## E. "Recent for you" row (separate from Top Picks)

For each user, the 10 best unseen films released in the 3 years up to the split time.
- **E:** ranked by the user's catalog-wide hybrid score (`rail_scores`, the score other rows already use).
- **E1:** ranked by popularity only.
- **E0:** what the current Top Picks top 10 (balanced) already shows.

Judged on the recent films the user later liked. 306 users have at least one, 6.1 on average. "Share shown" is the
share of those films that appear in the row.

| Stage | Row | Share shown | Any hit | NDCG@10 (recent) | Δ share vs Top Picks | Non-English | Hindi | Korean | Japanese | Non-ML | Overlap with Top Picks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Cold | E0 Top Picks | 0.8% | 3.9% | 0.006 | | 5.3% | 0.20% | 0.13% | 0.56% | 8.0% | |
| | E recent for you | 10.7% | 35.0% | 0.090 | +0.099 (0.013) | 11.4% | 0.16% | 0.26% | 2.6% | 19.8% | 2.9% |
| | E1 popular recent | 15.2% | 44.8% | 0.115 | +0.144 (0.014) | 9.2% | 0% | 1.6% | 1.3% | 13.2% | 6.7% |
| Warming | E0 Top Picks | 1.2% | 7.2% | 0.011 | | 6.6% | 0.16% | 0.29% | 1.4% | 7.5% | |
| | E recent for you | 12.7% | 38.6% | 0.098 | +0.115 (0.013) | 11.8% | 0.16% | 0.69% | 1.5% | 7.0% | 3.9% |
| | E1 popular recent | 15.8% | 45.4% | 0.118 | +0.145 (0.015) | 9.2% | 0% | 1.6% | 1.3% | 13.4% | 8.2% |
| Established | E0 Top Picks | 3.6% | 13.4% | 0.029 | | 15.4% | 0.92% | 0.72% | 2.7% | 13.1% | |
| | E recent for you | 15.8% | 43.5% | 0.124 | +0.123 (0.015) | **29.7%** | **0.56%** | 1.3% | 6.5% | **37.4%** | 5.6% |
| | E1 popular recent | 19.3% | 51.6% | 0.156 | +0.157 (0.016) | 10.6% | 0% | 1.4% | 2.3% | 16.0% | 5.8% |

Cost of the row: p95 latency 0.015 to 0.029 s, traced peak 1.6 MB per request. It is one extra pass over
`rail_scores`. Home already computes those scores, so in production the cost could be close to zero.

Reading:
- A recent row adds what Top Picks never shows. It barely overlaps Top Picks (3 to 6%) and shows 4 to 13 times more
  of the recent films users go on to like.
- The popular row beats the personalised row on MovieLens. But MovieLens targets favour popular films, as the audit
  noted, and 37% of the personalised row for established users is films without MovieLens data, which can never count
  as hits here.
- The personalised row is the more international one (29.7% non-English vs 10.6%), which matters for Aryav's goal.
  The decision between the two (or a blend) needs FlickRaven's own impressions and feedback (#119, #120), not
  MovieLens.

## C. One global cutoff (2018-08-14) instead of per-user split times

| Stage | Users | Mean relevant | Pool recall | R@50 / R@100 / R@200 | Per-user split (for reference) |
|---|---|---|---|---|---|
| Cold | 15 | 66.2 | 20.3% | 8.7 / 12.6 / 17.9% | 32.4% |
| Warming | 15 | 66.2 | 20.5% | 3.9 / 9.6 / 17.1% | 34.9% |
| Established | 15 | 66.2 | 14.4% | 3.4 / 5.4 / 11.1% | 41.4% |

**Inconclusive.** The audit's 400 users were sampled for having hold-out-film and test positives, not for activity
around 2018. Only 15 have training ratings both before and after the cutoff.
- Those 15 have years of later ratings (66 relevant films each), so their recall is naturally lower.
- 15 users is far too few to compare.
- The served models were trained on the per-user split, so they have seen other users' post-cutoff ratings, and
  there are no global-cutoff models.

A real check needs users sampled for activity across the cutoff, and ideally models retrained on
`global_train.parquet`. I did not retrain anything. Treat the 32 / 35 / 41% numbers as confirmed only for the
per-user split.

## What MovieLens cannot judge

- Hindi and Indian films (6 relevant in the sample).
- Series and anime.
- Films without MovieLens data other than the 500 hold-out films. They make up 37% of the personalised recent row
  for established users, and they can never be hits here.
- "Recent" is recent at each user's split time (MovieLens ends in 2023), not 2024 to 2026 releases.

## Recommendation

1. **E is the most promising next step.** Add a "recent for you" row as a separate row, never touching Top Picks.
   Choose between personalised, popular, or a blend using live impressions and feedback. Not built here; it would be
   a product change, which needs Aryav's go.
2. **D:** keep researching, do not ship. Next run: guard long-tail share as well, then retest in balanced mode.
3. **C:** sample users active across 2018-08-14 and retrain on the global split before drawing any conclusion.
