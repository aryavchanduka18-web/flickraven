# Unified Home phase 5: offline replay per user group (2026-11-14)

**Verdict: FAIL as served. Set `MIXED_HOME=false`.** The mixed Home finds hidden liked anime, K-dramas and Indian films
that today's Home never puts on the first screen, but it costs film-only users 0.0066 NDCG@10 (allowed: 0.003). A
one-line variant (Indian and international films stay in the one film list) passes the guard and keeps the anime and
K-drama gains, but loses the Indian-film gain. It is measured here, not shipped.

Script: `pipeline/mixed_home_replay.py` (tests: `pipeline/tests/test_mixed_home_replay.py`). Raw numbers:
`work/mixed-home-replay/results.json` (served code, main at #156), `results-no_film_lanes.json` (variant),
`results-before-155.json` (code before #155).

## Method

- Served engine (`recommender.load_engine`) over the **local** database, read-only. No production database, no Render
  change, no paid API, no model file written.
- Each user's state is run twice: today's Home (`engine.home`, balanced, no daily seed) and the same plan through
  `mixed_home_plan.mix`. Compared on the **first screen**: hero (5) + first 10 Top Picks, the 15 slots the mix changes.
- Paired differences (same users, same hidden titles), 95% interval = 1.96 standard errors.
- Groups:
  - **Anime fans**: 300 real anime lists (Kaggle anime dataset, 46,847 eligible: 10+ liked matched anime, 60%+ of the
    matched list anime). 20% of liked anime hidden.
  - **K-drama fans**: 300 real MyDramaList lists (55,419 eligible, same rule for Korean series). 20% of liked Korean
    series hidden.
  - **Indian-film fans**: all 102 MovieLens users with 3+ liked Indian-language films; a third of those hidden.
  - **Film-only**: 1,000 MovieLens held-out users (sampler of `availability_calibration.py`); targets are their later
    ratings of 7+ (test split + 500 hold-out films). **Guard: NDCG@10 must not fall by more than 0.003.**
- Leakage: the served anime/drama similarities were learned on all list users. For this run they are re-learned in
  memory without the 600 test users (same `drama_cf` code). The Indian group's hidden films were in MovieLens training
  (helps both arms equally; makes absolute numbers optimistic).

## Results (served code, main at #156)

| Group | Users | Hit on first screen, today → mixed | NDCG@10, today → mixed (diff, 95% CI) | Pass? |
|---|---|---|---|---|
| Anime | 300 | 0% → 26.0% | 0 → 0.034 (+0.034, +0.025..+0.043) | **Pass** |
| K-drama | 300 | 0% → 17.7% | 0 → 0.018 (+0.018, +0.013..+0.023) | **Pass** |
| Indian films | 102 | 2.0% → 7.8% | 0.005 → 0.018 (+0.014, +0.004..+0.024) | **Pass** (small n) |
| Film-only | 1,000 | 60.7% → 60.7% | 0.109 → 0.103 (**−0.0066**, −0.009..−0.004) | **FAIL** |

- Film-only pages changed for 40% of users. On those pages NDCG@10 fell 0.0165.
- Cause: the international-film lane switches on for 82% of film-only users (about 3 liked non-English films is
  enough). Its films enter by rank share in their own list, with no comparison to the film list, and push out films the
  hybrid scored higher, even though both lists are cut from the same `rail_scores`.
- Before #155 the loss was −0.0085; #155 reduced it but not enough.
- Context: the anime and series rows lower on today's Home already show 79% (anime) and 75% (K-drama) of these fans'
  hidden titles in their top 20. The mix moves them up to the first screen; it does not find new ones.

## Variant tested: no separate Indian / international film lanes

`--variant no_film_lanes`: those films stay in the one film list (same scale); only anime, anime films and series
are mixed in.

| Group | Hit on first screen | NDCG@10 diff (95% CI) | Pass? |
|---|---|---|---|
| Anime | 0% → 26.0% | +0.034 (+0.025..+0.043) | Pass |
| K-drama | 0% → 17.7% | +0.018 (+0.013..+0.023) | Pass |
| Indian films | 2.0% → 2.0% | 0.000 | No gain (no loss) |
| Film-only | 60.7% → 60.5% | **−0.0015** (−0.0026..−0.0004) | **Pass** (whole interval inside 0.003) |

Only 8% of film-only pages change (the anime lane, for users with 3+ liked anime films). To ship it: drop
`FILM_EXTRA_LANES` from `mixed_home_plan.mix` (one line), then `MIXED_HOME=true` is supported by this test.

## What phase 3 (calibrated mixing) would need to change

- Film lanes: compare on the film hybrid's own score (or its calibrated P(like 7+)), not on rank share, because they
  share a scale. Only then can Indian films earn slots without displacing better films.
- Series and anime: a held-out calibration set. The anime and MyDramaList lists used here are one (real 7+ labels):
  fit P(like) per lane on list users not used for similarities, and replace `0.5 + 0.5 * lane_weight` and `FLOOR` with
  that probability.
- Re-run this replay (`python -m pipeline.mixed_home_replay`) after any change; the guard stays at 0.003.

## Not measured

Hindi or other Indian **series** (no lists), Hollywood and international series fans, people who mix formats in one
history (list users rate only anime or only dramas), daily freshness (`stale`) and the daily seed, real FlickRaven users.
