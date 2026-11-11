# FlickRaven: an explainable hybrid movie recommender

*Recommender Systems mini project. Every number in this report is read from a file in `artifacts/`
produced by the pipeline; the detailed tables are in `docs/phase-3-results.md` to `docs/phase-6-results.md`.*

## Abstract
FlickRaven is an explainable hybrid movie recommendation engine that combines content-based filtering,
collaborative filtering, matrix factorization, implicit and explicit feedback, cold-start adaptation and
diversity-aware reranking to give personalized, user-controllable movie discovery. On a time-split test
of 5,000 MovieLens users with full ranking over 9,495 films, the hybrid reaches NDCG@10 = 0.163
[0.157, 0.168], comparable to the strongest single model (implicit ALS, 0.157 [0.152, 0.162]) and well
above item CF (0.123), user CF (0.118) and popularity (0.083). Beyond accuracy, it serves brand-new users
(onboarding lifts cold-start NDCG@10 from 0.085 to 0.093 at zero ratings), recommends films nobody has
rated (content hit rate@50 = 4.8% versus 0.5% at random and 0% for every collaborative model), explains
every recommendation from the sources that really produced it, and lets the user trade accuracy for
variety (Discovery Mode).

## 1. Problem and claim
Recommenders face six practical problems: new users (no history), new films (no ratings), popularity
bias, repetitive lists, unexplained recommendations and no user control. Our claim is deliberately
modest: the hybrid gives a **better overall trade-off** between relevance, cold-start performance,
coverage, diversity and novelty than any single model. We do not claim it wins every metric.

## 2. Data
- **MovieLens 32M** (ratings until October 2023): collaborative signals and evaluation.
- **TMDB**: metadata, images, credits, keywords, certifications; recent releases.
- **Wikidata**: awards (15,634 award rows in the catalog).
- **Product catalog: 14,292 films** in four parts: A MovieLens films 10,230, of which 9,995 form the
  evaluation backbone (>= 154 ratings, original metadata gate), B international enrichment 3,370
  (18 languages; Tamil, Telugu and Malayalam reach the 150-film onboarding rule), C recent releases 476
  (last 18 months before the build date), D Hollywood enrichment 216 (famous US productions missing
  from A-C). The catalog audit measures 100% coverage of the 1,000 most-voted US films.
- **Metadata gate:** poster, English overview of 10+ words, genre, director, 1+ cast. Films that fail
  are dropped, never filled in. The gate was first 15+ words and 3+ cast; it was relaxed because it
  dropped famous films such as The Graduate, Annie Hall and The Big Short. The 305 films that only the
  relaxed gate lets in (235 A, 68 B, 2 C) were added on top of the original cut and are not part of the
  evaluation backbone, so the ratings sample, splits, models and every result below are unchanged.
- **Ratings sample:** 30,000 users with 20+ ratings on part-A films (4.6 million ratings), scaled to
  1-10. Per-user time split 70/10/20, a global time cutoff (2018-08-14) as a robustness check, and
  500 part-A films held out completely for the new-movie experiment.

## 3. Methods
| Model | Idea | Role |
|---|---|---|
| Popularity | Bayesian average (m tuned) | baseline, cold start, "Most Loved" |
| Content-based | TF-IDF of overview/keywords/tagline + genre, language, country, director, cast, studio blocks; cosine to a liked-minus-disliked profile | new films, international films, explanations |
| User CF | Pearson on co-rated films, significance weighting min(n,50)/50, top-k neighbors computed in batches | "People With Your Taste" |
| Item CF | adjusted cosine with shrinkage n/(n+lambda), top-50 neighbors | "Because You Liked X" |
| Funk SVD | biased matrix factorization by SGD (scikit-surprise), closed-form fold-in | "Based On Your Ratings", best RMSE |
| Implicit ALS | weighted ALS (Hu, Koren, Volinsky 2008), confidence 1 + alpha w, closed-form fold-in | implicit feedback |
| Hybrid | candidates (50 per source) -> percentile normalization -> stage-weighted blend -> logistic Match % -> MMR rerank -> explanations | everything personal |

- **Switching + weighted + cascade hybrid.** The user stage comes from the behavioral count b only
  (cold 0-2, warming 3-10, established 11+); onboarding picks never count. Stage weights were tuned
  by grid search on simulated users that match the live definition. Result: cold = popularity 0.4,
  content 0.2, user CF 0.2, ALS 0.2; warming = user CF 0.4, content 0.3, ALS 0.2, popularity 0.1;
  established = ALS 0.7 with 0.1 each for content, item CF and user CF.
- **Knowledge-based recommendation:** For Tonight maps mood, runtime, language and genres to hard
  filters through a rule table (`moods.yaml`), ranks the survivors with the hybrid, and relaxes the
  constraints in a fixed order, telling the user what was relaxed.
- **Explanations:** at most 3 reasons, each from a source that gave at least 20% of the final score,
  with real evidence (the liked film, the real count of similar users).

## 4. Evaluation protocol
Full ranking over every part-A film the user has not rated (no sampled negatives; Krichene and Rendle
2020), a fixed sample of 5,000 users with at least one relevant film (rating >= 7), 95% bootstrap
confidence intervals over users, all settings tuned on validation and the test split used once.

## 5. Results
### 5.1 Model comparison (test)
| Model | NDCG@10 [95% CI] | P@10 | Coverage | Long-tail share |
|---|---|---|---|---|
| Hybrid, Familiar | 0.163 [0.157, 0.168] | 0.130 | 12.2% | 0.1% |
| Hybrid, Balanced | 0.161 [0.155, 0.166] | 0.128 | 12.3% | 0.1% |
| Hybrid, Discover | 0.158 [0.152, 0.163] | 0.126 | 12.9% | 0.2% |
| Implicit ALS | 0.157 [0.152, 0.162] | 0.127 | 12.5% | 0.1% |
| Item CF | 0.123 [0.118, 0.127] | 0.098 | 12.0% | 0.2% |
| User CF | 0.118 [0.113, 0.123] | 0.094 | 5.9% | 0.0% |
| Popularity | 0.083 [0.078, 0.087] | 0.069 | 1.3% | 0.0% |
| Content-based | 0.032 [0.029, 0.034] | 0.025 | 45.7% | 53.2% |
| Funk SVD | 0.032 [0.029, 0.034] | 0.026 | 39.8% | 49.0% |

Funk SVD has the best rating accuracy (RMSE 1.653 versus 1.721 for the bias baseline on the 1-10 scale)
but ranks poorly: it is trained to predict rating values, not to rank the whole catalog. The global
time-cutoff check (1,184 users) gives the same order (hybrid 0.219, ALS 0.213, item CF 0.164).

**Honest reading.** The hybrid and ALS intervals overlap, so on accuracy alone they are comparable.
The hybrid's advantage is everything else below.

### 5.2 Cold start (NDCG@10 against known ratings k)
| k | Hybrid without onboarding | Hybrid with onboarding | Popularity | ALS with onboarding | Item CF without |
|---|---|---|---|---|---|
| 0 | 0.085 | 0.093 | 0.083 | 0.082 | 0.008 |
| 2 | 0.093 | 0.095 | 0.083 | 0.084 | 0.031 |
| 5 | 0.096 | 0.104 | 0.083 | 0.087 | 0.057 |
| 10 | 0.103 | 0.110 | 0.083 | 0.096 | 0.071 |
| 20 | 0.115 | 0.123 | 0.083 | 0.117 | 0.097 |
Onboarding (5 picked films) helps most when nothing else is known; as real ratings accumulate the
collaborative sources take over (`docs/phase-6-results.md`, section 2, has every k and model).

### 5.3 New movies
Held-out films with no training ratings: hit rate@50 = 4.8% for the content model, 1.0% for the
hybrid, 0% for popularity, item CF, user CF, SVD and ALS, against 0.5% at random. This is the
new-item cold-start problem in numbers, and the reason the hybrid keeps a content source and the
site has a New & Notable rail.

### 5.4 Diversity
MMR lambda from 0.5 to 1.0 trades NDCG@10 for intra-list diversity. The Discovery Modes sit on that
curve: Familiar 0.163 / 0.835, Balanced 0.162 / 0.844, Discover 0.159 / 0.855 (NDCG / diversity).

### 5.5 Calibration
Match % is a logistic calibration of the blend score per stage, fitted on validation. On test the
expected calibration error is 0.013 (cold), 0.015 (warming) and 0.028 (established), all under the
0.05 pass threshold, with Match % values mostly between 70% and 93%.

**Limit found on 2026-11-10 (read this before quoting those numbers).** That check scores only films that were in the
candidate pool. The app shows the Match % for every film from the catalog-wide hybrid score, a different scale. Measured
on 600 test users with each user's own later ratings (`pipeline/segment_eval.py`, `artifacts/metrics/segments.json`):
the Match % shown averages 88% (cold), 85% (warming) and 83% (established), while 61% of the films these users went on
to rate were rated 7 or more. So the displayed Match % runs about 22 to 27 points high on films a user actually rates.
A one-feature refit on the catalog-wide score, fitted on half the users and judged on the other half, brings the gap
to about 2 points for every stage. It is not applied yet (it changes every number on the site).

### 5.6 Evaluation by segment
Per segment: share of later ratings that were 7+ ("positive"), mean Match % shown, gap = match/100 - positive, and the
within-user chance that a positive film outranked a non-positive one (AUC; 0.5 is chance). Segments under 100 ratings
are left out. Film vs series cannot be measured this way: series have no ratings in MovieLens, and are checked by their
own hit@10 tests (MyDramaList 31.6% vs popularity 17.2%; anime 31.8% vs 19.6%).

| Segment | Group | Ratings | Positive | Mean Match % | Gap | AUC |
|---|---|---|---|---|---|---|
| Film source | MovieLens factors | 57,510 | 60% | 87.1 | +0.27 | 0.60 |
| Film source | No MovieLens factors | 17,799 | 65% | 80.4 | +0.16 | 0.53 |
| User stage | Cold | 25,103 | 61% | 88.0 | +0.27 | 0.53 |
| User stage | Warming | 25,103 | 61% | 85.3 | +0.24 | 0.56 |
| User stage | Established | 25,103 | 61% | 83.3 | +0.22 | 0.59 |
| Language | English | 71,439 | 60% | 85.5 | +0.25 | 0.55 |
| Language | French | 897 | 70% | 86.7 | +0.17 | 0.47 |
| Language | Japanese | 888 | 80% | 87.3 | +0.07 | 0.49 |
| Language | Korean | 156 | 79% | 87.3 | +0.08 | 0.57 |
| Language | Spanish | 360 | 82% | 87.2 | +0.05 | 0.51 |
| Country | United States | 57,378 | 58% | 85.6 | +0.27 | 0.56 |
| Country | United Kingdom | 11,295 | 69% | 84.9 | +0.16 | 0.51 |
| Country | India | 222 | 76% | 82.9 | +0.07 | 0.61 |
| Country | Japan | 1,116 | 75% | 87.0 | +0.12 | 0.60 |
| Country | South Korea | 168 | 79% | 87.3 | +0.09 | 0.57 |

What it says: ranking is only mildly better than chance everywhere (AUC 0.47 to 0.61), best for films with MovieLens
factors and for established users, and weakest for films without MovieLens factors, cold users and French and
Japanese films. The Match % is too high in every segment, most for US films and cold users. After the refit above the
segment gaps are within about 0.1 for the large segments; the small ones (Korean, Indian, 100 to 170 ratings) move
the other way (the Match % becomes too low by up to 0.2), so one global curve is not enough for them yet. The ratings are
those users chose to make, so these are not recommendations the users were shown; the live report (`/performance`)
measures that.

### 5.7 New-user ranking experiments (2026-11-10)
Question: can the early blend (0 to 6 signals) be made more accurate? `pipeline/cold_eval.py` runs every variant on the same held-out
MovieLens users, scored the way the site scores (availability-aware blend, stored popularity), NDCG@10 against later ratings of
7+. Regimes: 2 ratings, 5 onboarding picks, 6 ratings. 700 users, repeated on 1,000 fresh users.

| Variant | 2 ratings | 5 picks | 6 ratings |
|---|---|---|---|
| Current hybrid | 0.043 | 0.049 | 0.039 |
| Popularity only | 0.072 | 0.073 | 0.073 |
| Hybrid with 80% popularity | 0.057 | 0.051 | 0.058 |
| Title-similarity table added to content | 0.041 | 0.047 | 0.040 |
| Popular-first, then re-rank (best variant) | 0.052 | 0.060 | 0.053 |

What it says, plainly:
- With so few signals, the personal models (content, user CF, item CF, ALS) are each worse than just ranking by popularity; mixing them in lowers accuracy. The held-out ratings are mostly of popular films, so this benchmark favours popularity, but it does mean the early personal signal is weak.
- Raising the popularity weight raises NDCG (+0.014 to +0.019, standard error 0.002 to 0.003) but makes lists almost identical: 1,000 cold users received 18 distinct films at 80% popularity against 221 today. That is not a better product, so it was not shipped.
- The new title-similarity table as a taste source gave +/-0.002, no gain. Popular-first re-ranking is worse than popularity alone.
- Not measurable from MovieLens: onboarding languages and genres, session signals, series and anime (no ratings), and what real users actually click. Those need the live report (`/performance`) over real users.
Nothing in the blend was changed because of this.

## 6. The website
React + TypeScript front end and a FastAPI back end over PostgreSQL. Every visitor is a user (guest
accounts upgrade on registration). The home page is planned in one call: hero (top 5 picks), up to 13
rails, de-duplicated, short rails hidden. Every action writes both the current-state tables and an
append-only interactions log; every shown card is logged in `recommendation_logs`. The 12 scenario
tests of the spec (cold users stay cold after onboarding, 3 ratings make a user warming, dislikes
disappear, no duplicates, every reason has at least 20% of the score, ...) all pass on the live catalog.

### 6.1 After the evaluation: hosting and product additions

The site is hosted on Render (one Docker service and one PostgreSQL 17 database; models delivered through the
private database because MovieLens ratings may not be redistributed). Sharing the sparsity structure of user CF's
derived matrices cut peak memory from 504 to 378 MB with bit-identical scores. Added afterwards, none of it
changing the evaluated models or results (a SHA-256 fingerprint of 46 evaluation files is identical):
- 470 missing parts of franchises already in the catalog (part D, outside the evaluation universe), shown as
  "More from <franchise>" and studio rows such as "More from Marvel";
- More Like This by content similarity only (content cosine plus genre, language and era terms);
- cast and crew pages, themed collections, accounts with password rules, lockout and session revocation;
- a recommendation-confidence measure: model agreement = 100 x (1 - 2 x the standard deviation of the
  weighted sources' percentile ranks of the film), shown with the per-model ranks;
- user-controlled re-ranking (Tune: MMR lambda, novelty weight, language and runtime terms; neutral = the
  evaluated system), a "current phase" row from the last 21 days, and dislike reasons that update preferences.

## 7. Advanced modules (lab only)
See `artifacts/lab/shilling.json`, `taste_map.json`, `ncf.json` and the Research Lab page.

## 8. Limitations

- No email service: no email verification or password reset. Sign-in lockout counters live in one process's
  memory. The free hosting plan sleeps when idle and its database expires after a month unless upgraded.
- Model agreement measures how consistently the sources rank a film, not whether the user will like it; it has
  not been evaluated against held-out ratings.
- MovieLens ratings stop in October 2023; parts B, C and D rely on content and popularity until site
  users rate them.
- Offline implicit feedback is derived from ratings (7+); live implicit feedback comes from real events.
- Several tuned settings sit at the edge of wide grids (popularity m, item CF shrinkage): validation
  rewards popular, well-supported recommendations, a known popularity bias of the evaluation itself.
- Kannada has 133 films, below the 150-film onboarding rule, even at the lowest vote floor.

## References
Hu, Koren and Volinsky (2008), Collaborative filtering for implicit feedback datasets. Koren (2008),
Factorization meets the neighborhood. Krichene and Rendle (2020), On sampled metrics for item
recommendation. Rendle et al. (2020), Neural collaborative filtering vs. matrix factorization revisited.
He et al. (2017), Neural collaborative filtering. Carbonell and Goldstein (1998), MMR. Harper and
Konstan (2015), The MovieLens datasets.