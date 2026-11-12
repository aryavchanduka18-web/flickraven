# Candidate-source experiments (2026-11-12)

Harness: `pipeline/candidate_experiments.py` on `pipeline/candidate_recall.py`. Read-only.
- Every arm runs the real `top_picks` at 50 per source.
- An arm either adds films to the pool, through the engine's own `_add_unavailable_candidates`, so the added films are
  scored and placed exactly as the engine would place them, or swaps the content source's scores for that call.
- No change to the engine, models, calibration, Match % or the database.

Setup:
- Same 400 users and seed (11) as the recall report.
- Strict temporal protocol: profile = 2 / 6 / all most recent training ratings; relevant = eligible unseen films rated
  ≥ 7 after the user's split time.
- Every arm uses the same users, profiles and baseline pool, so all differences are paired per user.

Raw numbers: `experiments-2026-11-12.json`. Runtime 11 min.

**Win rule (from the brief):** NDCG@10 rises by more than 2 SE, and diversity (ILD) and long-tail share do not fall by
more than 2 SE. It is checked in both modes:
- Balanced: the shipped default, with the tail channel.
- Familiar: tail 0, the benchmark convention.

## Verdict: no arm wins

| Arm | What it does | Pool recall effect | NDCG@10 (balanced / familiar) | Verdict |
|---|---|---|---|---|
| recent_20 | + 20 most popular unseen films released in the 3 years up to the split time | +1.6 to +2.7 pts | flat / flat | no significant change |
| recent_50 | + 50 of them | **+3.6 to +4.6 pts**; recent films' recall roughly doubles | flat / flat | no significant change |
| nonml_quota_5 | established only: + 5 films without MovieLens data most similar by content | 0 | flat / flat | no significant change |
| nonml_quota_10 | + 10 of them | 0, and R@100 falls 2.8 pts | flat / flat | familiar: ILD −0.0002 (2 SE) |
| strong9_content | content source from ratings ≥ 9 only | +1.8 pts (established); recall of films without MovieLens data 20.9 → **45.3%** | flat / flat | **regresses diversity** (ILD −0.020, 20 SE) |
| top5_content | content source from the 5 highest ratings | +1.1 pts (established) | flat / flat | **regresses diversity** (ILD −0.020) |

No NDCG@10 change is anywhere near 2 SE. The largest is +0.0006 with SE 0.0015.

- **The added-film arms** (recent, non-MovieLens quota) put the new films into the pool, but the engine places them
  below the top 10 almost every time. The top 10 changes for 2 to 10 of 400 users in familiar mode and 12 to 163 in
  balanced, where the tail channel and MMR reshuffle.
- **The strong-likes content arms** do change the list, but they make it narrower and more English.

## Per stage

Pool recall and NDCG are user averages. Δ is paired against baseline, with SE in brackets. "Recent recall" is pool
recall restricted to relevant films released in the 3 years up to T (306 of 398 users have such a film). "Non-ML
recall" is restricted to relevant films without MovieLens data, the 500 hold-out films (275 users).

**Cold (2 ratings)**: baseline pool recall 32.4%, NDCG@10 0.0586 balanced / 0.0693 familiar.

| Arm | Pool recall | R@50 / R@100 / R@200 | Recent recall | Non-ML recall | ΔNDCG bal. | ΔNDCG fam. | ΔILD bal. | p95 s |
|---|---|---|---|---|---|---|---|---|
| baseline | 32.4% | 14.5 / 19.4 / 30.0% | 21.3% | 32.6% | | | | 0.031 |
| recent_20 | 35.3% | 14.6 / 19.9 / 30.7% | 39.7% | 35.5% | +0.0001 (0.0001) | 0 | +0.0001 | 0.051 |
| recent_50 | 37.0% | 14.7 / 19.9 / 29.6% | **50.0%** | 36.4% | +0.0001 (0.0002) | 0 | +0.0004 | 0.052 |
| strong9_content | 32.5% | 14.4 / 19.4 / 30.1% | 21.4% | 32.5% | 0.0000 (0.0003) | −0.0002 (0.0002) | −0.0004 | 0.060 |
| top5_content | identical to baseline (a cold profile has only 2 ratings) | | | | | | | 0.035 |

**Warming (6 ratings)**: baseline pool recall 34.9%, NDCG@10 0.0719 / 0.0856.

| Arm | Pool recall | R@50 / R@100 / R@200 | Recent recall | Non-ML recall | ΔNDCG bal. | ΔNDCG fam. | ΔILD bal. | p95 s |
|---|---|---|---|---|---|---|---|---|
| baseline | 34.9% | 13.9 / 20.4 / 31.7% | 23.6% | 29.3% | | | | 0.067 |
| recent_20 | 37.6% | 13.9 / 20.8 / 31.5% | 40.4% | 33.3% | +0.0001 (0.0001) | 0 | −0.0001 | 0.084 |
| recent_50 | 39.4% | 13.9 / 21.0 / 29.8% | **49.9%** | 34.4% | +0.0002 (0.0002) | 0 | −0.0001 | 0.086 |
| strong9_content | 35.0% | 13.7 / 20.6 / 31.6% | 23.6% | 29.8% | −0.0004 (0.0010) | −0.0001 (0.0010) | **−0.0031 (0.0007)** | 0.101 |
| top5_content | 34.9% | 13.8 / 20.6 / 31.7% | 23.6% | 30.4% | −0.0005 (0.0010) | −0.0002 (0.0009) | **−0.0035 (0.0006)** | 0.101 |

**Established (whole training history)**: baseline pool recall 41.4%, NDCG@10 0.1589 / 0.1844.

| Arm | Pool recall | R@50 / R@100 / R@200 | Recent recall | Non-ML recall | ΔNDCG bal. | ΔNDCG fam. | ΔILD bal. | p95 s |
|---|---|---|---|---|---|---|---|---|
| baseline | 41.4% | 21.2 / 26.7 / 38.9% | 27.7% | 20.9% | | | | 0.025 |
| recent_20 | 43.8% | 21.2 / 26.1 / 39.4% | 42.1% | 25.3% | −0.0004 (0.0004) | 0.0000 | −0.0001 | 0.039 |
| recent_50 | 45.4% | 21.2 / 25.6 / 38.9% | **51.8%** | 27.1% | 0.0000 (0.0005) | −0.0002 (0.0002) | −0.0003 | 0.038 |
| nonml_quota_5 | 41.4% | 21.2 / 25.5 / 38.4% | 27.7% | 20.9% | 0.0000 (0.0005) | 0.0000 | −0.0001 | 0.040 |
| nonml_quota_10 | 41.4% | 21.2 / 24.0 / 38.0% | 27.7% | 20.9% | 0.0000 (0.0005) | 0.0000 | −0.0002 | 0.041 |
| strong9_content | 43.1% | **24.6 / 28.9 / 40.9%** | 29.3% | **45.3%** | −0.0002 (0.0020) | +0.0005 (0.0013) | **−0.0201 (0.0010)** | 0.093 |
| top5_content | 42.4% | 24.6 / 28.4 / 40.0% | 28.6% | 35.7% | −0.0004 (0.0021) | +0.0006 (0.0015) | **−0.0204 (0.0010)** | 0.081 |

Notes on the established arms:
- The quota adds films that are never relevant here: 0 hits in 400 users. Its content-similar films without MovieLens
  data are not the hold-out films users later liked. Because every film it adds pushes other films down, R@100 drops.
- The strong-likes content arms are the only arms that improve early recall (R@50 +3.4 pts) and find many more of the
  later-liked films without MovieLens data (20.9 → 45.3%). That gain does not reach NDCG@10. It costs diversity: ILD
  −0.020, 20 SE, in balanced mode.

## Top-10 composition (balanced, the shipped mode)

| Stage / arm | English | Non-English | Hindi | Korean | Japanese | Non-ML in top 10 | Non-ML at #1 | Can never be a hit here | Distinct films |
|---|---|---|---|---|---|---|---|---|---|
| Cold baseline | 94.7% | 5.3% | 0.18% | 0.10% | 0.55% | 8.0% | 3.5% | 4.3% | 610 |
| Cold recent_50 | 94.6% | 5.4% | 0.18% | 0.10% | 0.53% | 7.9% | 3.5% | 4.4% | 625 |
| Warming baseline | 93.1% | 6.9% | 0.18% | 0.23% | 1.58% | 7.6% | 0.0% | 6.8% | 827 |
| Warming strong9 | 93.9% | 6.1% | 0.13% | 0.23% | 1.48% | 8.2% | 0.0% | 7.4% | 843 |
| Established baseline | 84.3% | **15.7%** | **0.93%** | 0.70% | 2.66% | 13.7% | 0.0% | 11.9% | 1,106 |
| Established recent_50 | 84.4% | 15.6% | 0.93% | 0.70% | 2.66% | 13.5% | 0.0% | 11.6% | 1,092 |
| Established nonml_quota_10 | 84.3% | 15.8% | 0.75% | 0.78% | 2.71% | 13.7% | 0.0% | 12.0% | 1,095 |
| Established strong9_content | 92.3% | **7.7%** | **0.00%** | 0.33% | 1.21% | 7.6% | 0.0% | 2.5% | **850** |
| Established top5_content | 92.7% | 7.3% | 0.00% | 0.35% | 1.06% | 8.5% | 0.0% | 4.9% | 871 |

Familiar mode (tail 0) shows 0% films without MovieLens data in the top 10 for warming and established users, under
every arm.

**What this means for under-represented films (Aryav's concern):**
- The strong-likes content arms halve the non-English share for established users (15.7% → 7.7%).
- They remove the few Hindi films (0.93% → 0%).
- They cut distinct films by 23%.
- They also cut the films MovieLens cannot score (11.9% → 2.5%). That is part of why their NDCG is not lower: they
  swap unscoreable non-MovieLens films for scoreable MovieLens ones.

So on MovieLens they look neutral, but they would move FlickRaven away from the international discovery Aryav wants.
I would not ship them in this form.

## What MovieLens cannot judge

- **Hindi, other Indian and most Korean films.** This sample has 6 relevant Hindi films. An arm that brings more of
  them into the top 10 can only lose NDCG here, because they can never be hits.
- **Series and anime.** Not in MovieLens at all.
- **The non-MovieLens quota.** It adds catalog films without MovieLens data, and those films can never be relevant in
  this benchmark. The quota's "0 hits" means only that it never adds one of the 500 hold-out films. Whether its picks
  are good films for the user cannot be measured here; it needs real FlickRaven feedback (the impressions and Perfect
  Pick logging from #119 and #120).
- **"Recent" means recent at the user's split time** (MovieLens ratings end in 2023), not 2024 to 2026 releases.
  Popularity is today's vote count, so slightly informed by the future.

## Cost

- **Memory:** peak traced memory per `top_picks` call is unchanged at 1.8 MB in every arm.
- **Latency (p95, untraced calls):**
  - The added-film arms add 0.01 to 0.02 s: one extra availability-aware placement.
  - The content arms add 0.03 to 0.07 s: one extra `scores()` call for the reduced profile. In production that call
    could be avoided by computing the content source once.
- Not measured: concurrent requests.

## Recommendation

1. **Ship none of these arms as they are.**
2. **Recent-films retrieval works as retrieval.** Recall of later-liked recent films doubles (21 to 28% → 50 to 52%)
   at a small cost, but the engine's blend never ranks those films high enough to reach the top 10. If recent films
   matter for FlickRaven, as they do for Indian releases, the next step is ranking, not retrieval: a recent-films row
   or reserved slots, judged by real user feedback. MovieLens cannot score it fairly.
3. **The strong-likes content profile is the only arm with a real retrieval signal** for films without MovieLens data
   (20.9 → 45.3%). It needs a guard that keeps language and genre spread, for example by blending it with the
   full-profile content instead of replacing it, before it is worth another run.
4. **Retrieval-only changes cannot move NDCG@10 here,** because the ranker does not promote what they add. Future
   experiments need to change retrieval and ranking together and be judged on this harness with the same win rule.
