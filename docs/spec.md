# FlickRaven Spec

**Version 1.1. Approved by Aryav on 2026-10-07 with the changes listed below. No more redesign; build from this.**

- This is the single source of truth for the build.
- It is Aryav's v1.0 plan (posted in the project chat) with the fixes from [plan-review.md](plan-review.md) applied. Details Aryav's plan adopted from [plan.md](plan.md) (schema, API, folders) are copied in here, so this file stands alone.
- 2026-10-07 changes from Aryav's review: 2–3 large cards per row on desktop; onboarding picks no longer count toward the user's stage; American spelling throughout.
- Home rails: Aryav chose "Use real data" on 2026-10-07 (13 rails; awards from Wikidata; Trending merged into New & Notable; Critically Acclaimed dropped).
- Rule for the build: follow this spec. If something in it turns out wrong or impossible during the build, raise it in the thread before changing it. Never change it silently.

Change log:
- v1.0: Aryav's plan, 2026-10-07.
- v1.1: merged spec with review fixes, plus Aryav's two final changes (card density, stage counter), 2026-10-07.

---

## 1. Product

**One line (for the report):** FlickRaven is an explainable hybrid movie recommendation engine that combines content-based filtering, collaborative filtering, matrix factorization, implicit and explicit feedback, cold-start adaptation and diversity-aware reranking to give personalized, user-controllable movie discovery.

**What it is:** a movie discovery website whose job is to show a recommendation engine working. It is **not** a streaming site.
- No video player, no Play button, no playback, no trailers hosted by us.
- Clicking a movie opens its detail page.

**Problems it addresses (and the claim we make):**
- New-user cold start, new-movie cold start, popularity bias, repetitive lists, unexplained recommendations, no user control.
- Claim: the hybrid gives a **better overall trade-off** between relevance, cold-start performance, coverage, diversity and novelty than any single model. Not "hybrid wins every metric". Never "better than Netflix".
- **Hybrid versus ALS, stated plainly:** on the offline test (5,000 users) the hybrid scores NDCG@10 0.163 [0.157, 0.168] and Implicit ALS 0.157 [0.152, 0.162]. The intervals overlap, so the difference is inside the statistical noise: **the hybrid is not shown to be more accurate than ALS.** What the hybrid adds is cold-start handling, films without MovieLens data, explanations, a diversity control and a long-tail channel. Do not describe it as more accurate.

**Three ideas that define the product:**
1. **Why this movie?** Every personal recommendation carries a real, plain-English reason.
2. **Familiar ↔ Balanced ↔ Discover.** The user controls how adventurous the list is, and the control really changes the reranking.
3. **Diverse lists.** The engine checks whether its picks are too alike before showing them.

**Not built:** streaming or video, multiple profiles per account, real-time model retraining, microservices or distributed infrastructure, chatbots, invented data (subtitles, audio tracks, content advisories, critic scores).

---

## 2. Scope

**Core (the finished project must have all of these):**
- Models: popularity, content-based, user CF, item CF, Funk SVD with fold-in, implicit ALS with fold-in, hybrid.
- Engine: candidate generation, filters, score normalization, switching + weighted blend by user stage, calibrated Match %, MMR diversity and novelty reranking, Discovery Mode, explanations, Surprise Me, For Tonight (constraint-based, with relaxation).
- Cold start: onboarding for new users; content features for new movies.
- Product: accounts and database-backed guests, onboarding, home with hero and 13 rails, movie pages, Quick View, Discover, Genres, Search, My List, Activity, Taste Profile.
- Research Lab at `/lab` and the full offline evaluation.
- Viva notes for every phase (section 15).

**Advanced (built after the core is evaluated and stable, in this order):**
1. Shilling attack and defense (lab only).
2. Taste map with PCA (lab only).
3. Neural Collaborative Filtering (lab only, never served on the website).

---

## 3. Architecture, stack and where it runs

```
             OFFLINE (pipeline, run by us)
  MovieLens + TMDB + Wikidata -> pipeline scripts -> artifacts/ (models, metrics, lab data)
                                                  -> Postgres (catalog, aggregates)

             ONLINE (the website)
  Browser (React) <-> FastAPI <-> Postgres (users, ratings, events, lists)
                         |
                         +-- loads artifacts/ once at startup
                         +-- engine package: profile -> candidates -> blend -> calibrate -> rerank -> explain
```

- The same `cinematch_engine` Python package is used by the offline evaluation and by the live API. **The model we evaluate is the model the website serves.**
- Heavy work (feature building, training, evaluation) is offline. Per request, the API only does cheap work: fold-in, neighbor look-ups, blending, reranking, explanations.

| Layer | Choice |
|---|---|
| Frontend | React + TypeScript + Vite, React Router, TanStack Query, Tailwind CSS, Framer Motion |
| Backend | Python 3.12 (already on the laptop), FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL 17 in Docker (Docker Desktop and WSL2 are already on the laptop) |
| ML | NumPy, pandas, SciPy (sparse matrices), scikit-learn, scikit-surprise (Funk SVD), implicit (ALS), PyTorch (NCF only) |
| Tests | pytest (engine, API, scenario tests), Vitest for key frontend logic |

**Where it runs:**
- On Aryav's laptop, in `C:\PROJECTS\RS PROJECT`, built through Remote Control.
- Reason: the data sites (MovieLens, TMDB, Wikidata) are blocked from the cloud workspace, and the demo runs on the laptop anyway.
- Code is pushed to a private GitHub repository after every phase.
- Laptop checked on 2026-10-07: Windows 11, 15.4 GB RAM, Intel Core Ultra 9 185H, 200 GB free; Git, Python 3.12, Node 24, Docker and WSL2 installed; no PostgreSQL. So the project uses **Python 3.12** (changed from 3.11 to avoid an extra install) and **PostgreSQL in Docker**. scikit-surprise 1.1.5 and implicit 0.7.3 both ship ready-made Windows packages for Python 3.12, so no compiler is needed.

---

## 4. Data

### 4.1 Sources
| Source | Used for | Notes |
|---|---|---|
| **MovieLens 32M** | All ratings: CF, SVD, ALS, evaluation, community-rating aggregates | Ratings run up to 2023. `links.csv` maps each film to its TMDB and IMDb ids. |
| **TMDB API** | Metadata, posters, backdrops, title logos, credits, keywords, certifications; recent releases | Needs Aryav's free API key. Attribution notice and logo in the site footer (TMDB terms). |
| **Wikidata** | Awards (won / nominated) | Free, no key. Matched by TMDB movie id (property P4947). Award received = P166, nominated for = P1411. |
| Not used | OMDb, critic scores, any scraping, the piracy site in the reference screenshots | |

**Rating scale:** MovieLens 0.5–5.0 stars × 2 = FlickRaven 1–10. The site's 5-star widget with half stars gives exactly the same 10 levels.

**Implicit data, stated honestly in the report:** "Implicit training signals are derived from explicit ratings for offline experiments. Live FlickRaven implicit feedback comes from real user interactions."

### 4.2 Catalog (product catalog; size set by the rules below, measured in the catalog audit)
The **product catalog** is everything the website can show. The **evaluation universe** (section 12) is only the MovieLens-linked part A films in the ratings sample, so model comparisons stay fair however large the product catalog grows.

| Part | How it's selected | Built (2026-10-08) |
|---|---|---|
| A. MovieLens backbone | Films with enough MovieLens ratings to train and evaluate user CF, item CF, SVD and ALS (threshold tuned so this part lands near 10,000; 154 ratings at the first build) that pass the metadata gate | 9,995 |
| B. International enrichment | TMDB "discover" by original language, sorted by vote count: Hindi, Tamil, Telugu, Malayalam, Kannada, Bengali, Marathi, Korean, Japanese, Spanish, French, German, Italian, Chinese and others. Tamil, Telugu, Malayalam and Kannada use a lower vote minimum so they can reach the 150-film onboarding rule (Aryav, 2026-10-08) | ~3,000 |
| C. Recent releases | Releases from the 18 months before the **catalog build date** (MovieLens 32M stops at 12 October 2023), with a minimum TMDB vote count | ~475 |
| D. Hollywood enrichment | Famous US films missing from A, B and C. A film is a candidate if the US is among its TMDB production countries (co-productions count). It qualifies if TMDB votes ≥ 2,000, or ≥ 1,000 and released before 1990, or ≥ 1,000 and part of a TMDB collection (franchise). "Franchise" means only that TMDB's `belongs_to_collection` field is set; no film is judged a franchise by hand. No minimum vote average: famous films count even if they are poorly rated. Thresholds live in `pipeline/catalog_config.yaml` | measured |

- **Hollywood coverage is a product-catalog goal**, not a requirement that every Hollywood film has collaborative ratings. Films without MovieLens ratings (parts B, C and D) are recommended through content, popularity and live site feedback, which is how FlickRaven demonstrates new-movie cold start.
- **Catalog audit:** the pipeline writes `artifacts/metrics/catalog_audit.json` and `docs/catalog-audit.md`: size of each part, films per language, US candidates found, how many were already in A, how many were added as D, how many failed the gate and why, measured coverage of the top 500 and top 1,000 US films by TMDB votes, and the list of top-1,000 films still missing with the reason for each. Claims about coverage use only these measured numbers.

- **Metadata gate** (every film): poster, English overview of at least 15 words, at least 1 genre, a director, at least 3 cast members. A backdrop is optional (fallback: blurred poster). *Amended 2026-10-08 (Aryav): at least 10 words and at least 1 cast member; films that pass only the relaxed gate are added on top of the original cut and stay outside the evaluation backbone (see docs/decisions-log.md).*
- **Language rule:** onboarding only offers a language that has **at least 150 films** in the catalog.
- **Thin-text rule:** films with short overviews or no keywords get more weight on structured features (genre, director, cast, language) in the content model.
- Parts B, C and D have no MovieLens ratings. Only content, popularity (TMDB vote counts) and live site feedback can recommend them. This is the new-movie cold-start story.

### 4.3 One threshold table (used everywhere)
| Use | Rule |
|---|---|
| "Relevant" in every ranking metric | rating ≥ 7/10 |
| Positive signal for ALS training (offline) | rating ≥ 7/10; confidence rises with the rating |
| Ratings ≤ 5/10 | not an ALS positive; they feed SVD and the dislike logic |
| Match % calibration target | probability that the user rates the film ≥ 7/10 |
| Onboarding simulation picks | the user's earliest films rated ≥ 8/10 |

### 4.4 Ratings preparation and splits
- Keep ratings on catalog films only. Keep users with at least 20 such ratings.
- Sample about 30,000 users with a fixed seed (the laptop has 15.4 GB of RAM, which is enough). All models train on the same sample, so the comparison is fair.
- **Split per user by time:** oldest 70% train, next 10% validation, newest 20% test.
- **Second check:** one global time cutoff (everything after a date is test), reported as a robustness check.
- **New-movie holdout:** 5% of part-A films have all their ratings removed from train and validation. They are used only in the new-movie test.
- The test set is used **once**, at the end of tuning.

### 4.5 Pipeline steps
Scripts in `pipeline/`, run in order; `python -m pipeline.run_all` runs everything. Every raw download is cached on disk, so nothing is fetched twice.

| Step | Script | Output |
|---|---|---|
| 1 | `01_download_movielens.py`: download and unzip MovieLens 32M | `data/raw/ml-32m/` |
| 2 | `02_select_catalog.py`: parts A, B and C of the catalog | `catalog_ids.csv` |
| 3 | `03_fetch_tmdb.py`: one call per film with credits, keywords, release dates and images appended | `data/raw/tmdb/*.json` |
| 4 | `04_fetch_awards_wikidata.py`: awards for catalog films in a few bulk queries | `awards.parquet` |
| 5 | `05_clean.py`: metadata gate, duplicates, language codes, certifications, genre names, dominant color of each backdrop, completeness report per language | `movies_clean.parquet`, `metadata_report.json` |
| 6 | `06_ratings_prep.py`: filter, sample users, scale to 1–10 | `ratings.parquet` |
| 7 | `07_split.py`: time split, global-cutoff split, new-movie holdout | `train/val/test.parquet` |
| 8 | `08_features_content.py`: TF-IDF and structured feature blocks | `content.npz`, `vectorizer.joblib` |
| 9 | `09_train_models.py`: tune each model on validation, then train final models | `artifacts/models/` |
| 10 | `10_tune_hybrid.py`: blend weights per user stage, Match % calibration per stage | `hybrid_weights.json`, `calibration.joblib` |
| 11 | `11_evaluate.py`: every metric and experiment in section 12 | `artifacts/metrics/*.json` |
| 12 | `12_load_db.py`: movies, people, keywords, awards, aggregates, colors into Postgres | DB rows |
| 13+ | `13_shilling.py`, `14_taste_map.py`, `15_ncf.py` (advanced) | `artifacts/lab/*.json` |
| any | `export_site_feedback.py`: adds live site ratings and events to training before a retrain (run by hand) | |

---

## 5. Models

| # | Model | How it works | Settings tuned on validation | Role on the site |
|---|---|---|---|---|
| 1 | **Popularity** | Bayesian average: `score = v/(v+m)·R + m/(v+m)·C` (R = film's mean, v = its rating count, C = global mean, m = minimum-count constant). Language-aware variant. | m | "Most Loved", cold-start fallback, baseline |
| 2 | **Content-based** | TF-IDF on overview + keywords + tagline (English stop words, sublinear tf, ignore words in >50% of films) plus weighted blocks for genres, language, country, director, top-5 cast, studio. Cosine similarity. User profile = weighted average of liked films' vectors minus disliked ones. | block weights, n-grams | New films, international films, cold start, explanations (More Like This uses its own title-to-title model, `cinematch_engine/similar.py`) |
| 3 | **User-based CF** | Pearson correlation on co-rated films, with significance weighting `min(n, 50)/50` (n = films in common). Prediction from the k most similar users' mean-centered ratings. | k, minimum overlap | "People With Your Taste Loved", explanations |
| 4 | **Item-based CF** | Adjusted cosine (ratings centered on each user's mean), shrunk when few users rated both films. Top-50 neighbors per film stored offline. | shrinkage, neighbors | "Because You Liked X", "More Like This" |
| 5 | **Funk SVD** | Matrix factorization with user and film biases, learned by SGD from known ratings only (scikit-surprise `SVD`). **Fold-in** for new users: film factors fixed, solve a small regularized least-squares problem for the user's vector from their ratings. | factors, epochs, learning rate, regularization | "Based On Your Ratings", main ranker for established users |
| 6 | **Implicit ALS** | Weighted ALS (Hu, Koren and Volinsky 2008, `implicit` library). Confidence `c = 1 + α·w`. Offline, w comes from ratings ≥ 7/10; live, from the event weights (section 6.2). Fold-in through the library's single-user recalculation. | factors, regularization, α, iterations | Uses likes, list adds, views; candidate source |
| 7 | **Hybrid** | Section 6. | blend weights per user stage | Everything personal on the site |
| A1 | Shilling defense | Section 14 | | Lab only |
| A2 | Taste map | PCA of SVD film vectors to 2D | | Lab only |
| A3 | NCF | NeuMF (GMF + MLP) in PyTorch, trained on positives with 4 sampled negatives each | | Lab only, never served (no cheap fold-in) |

Knowledge/constraint-based recommendation is covered by onboarding constraints, hard dislike filters, Discover filters and For Tonight (section 6.10). No separate ML model.

---

## 6. Recommendation engine

### 6.1 User profile (built per request)
- Explicit: site ratings (1–10), centered on the user's mean.
- Implicit: events turned into a weight per film (section 6.2), then ALS confidence.
- **Onboarding answers are preference signals, not behavior.** The picked films feed the content profile and ALS with the same weight as a like, and the chosen languages and genres feed the constraints. They are counted separately as `onboarding_count` and **never** add to the stage counter.
- **Behavioral interaction count b** = distinct films the user has rated, liked, disliked, added to My List or marked watched on the site. Views, Quick Views and search clicks still feed ALS, but they do not count toward b (opening 11 pages is not 11 opinions).
- **User stage** comes from b only: **cold** (b = 0–2), **warming** (3–10), **established** (11+).
- So a new user who picks 5 films in onboarding is still **cold** (onboarding_count = 5, b = 0) and gets onboarding + content + popularity. They move to warming only after 3 real actions.

### 6.2 Event weights (config file `engine/config/event_weights.yaml`, starting values, not "truth")
| Event | Weight |
|---|---|
| detail_view | 0 for taste (weak, short-term only; logged once per film per day) |
| quick_view | 0 for taste (weak) |
| search_click | 0 for taste (weak) |
| hero_view | 0 for taste (weak) |
| list_add | +3 |
| list_remove | -2 |
| watched | +2 |
| like | +4 |
| dislike | -5, and the film is filtered out |
| rate | explicit rating, plus +1 for showing interest |
| hover | not logged |

Three tiers (2026-11-10, `cinematch_engine/profile.py`): **weak** (opening a page, quick view, search click, banner click) never enters the long-term taste profile, because anyone opens a page for any reason and what is opened depends on what was shown; it only drives short-term things such as Continue Exploring. **Strong** (list add / remove, watched, like, dislike) uses the weights above. **Confirmed** (a rating) sets its own weight from the rating. Exposure and position bias: each recommendation shown is logged with its surface and rank (`recommendation_logs`), and clicks with their source and position, so click rates by position can be measured; no click feeds taste any more, so there is nothing to correct yet. Each kind of event counts at most once per film when the weights are added up (2026-11-10), so opening the same film many times on different days is not many times the interest.

### 6.3 Candidates
About 50 films from each source: popularity, content, item CF, user CF, SVD, ALS. Merged into one pool of up to ~300.

### 6.4 Filters
Remove: films already rated, marked watched, or disliked; films in disliked genres (hard rule); films already placed higher on the same page (section 7.2); films outside the catalog.

### 6.5 Normalization
Each source's scores become a 0–1 percentile rank within the user's candidate pool. A source that didn't propose a film gives it 0. Raw scores from different models are never added directly.

### 6.6 Switching + weighted blend
- `final = Σ weight[stage][source] × normalized_score[source]`.
- Weights are tuned per stage by grid search on NDCG@10 over validation users.
- **Stage tuning uses simulated users that match the live definition.** Each validation user gets simulated onboarding (5 of their earliest films rated ≥ 8/10, plus those films' genres and languages, counted as onboarding, not as b), then: cold = onboarding + 0–2 further ratings; warming = onboarding + 3–10; established = full training history. (Every MovieLens user has 20+ ratings, so without this, the cold and warming stages would be tuned on nothing.)
- Expected pattern (the real numbers come from tuning and are shown in the lab): cold = popularity + content; warming = content, item CF, ALS rising; established = SVD, ALS, item CF, user CF, small content, little popularity.
- This is a **switching hybrid** (weights change with stage) inside a **weighted hybrid** (the blend) inside a **cascade** (candidates, then blend, then rerank). Use those three names in the report.

### 6.7 Match %
- One-feature logistic regression per stage, fitted on validation: blend score → probability the user rates the film ≥ 7/10.
- Match % = that probability × 100, rounded, capped at 99.
- Expect most values between 60% and 90%. Do not stretch them.
- **Community rating** is separate: Bayesian average of MovieLens and site ratings on the 1–10 scale.

### 6.8 Diversity reranking (MMR) and Discovery Mode
- Take the top 100 by blend score and pick one film at a time:
  `next = argmax [ λ·relevance(i) − (1−λ)·max_similarity(i, picked) + β·novelty(i) ]`
- similarity = content cosine; novelty = −log(popularity share), scaled 0–1.

| Mode | λ | β | Extra |
|---|---|---|---|
| Familiar | 0.95 | 0 | none |
| Balanced (default) | 0.75 | 0.05 | none |
| Discover | 0.55 | 0.20 | small boost for films outside the user's languages and for genres rare in their history |

The mode is saved in `user_preferences.discovery_mode`.

**Long-tail channel (2026-11-10).** MMR only reorders the top 100, and ALS carries 70% of the established blend, so the offline long-tail share was 0.1% (films outside the 20% most-rated MovieLens films). A tail channel now adds the best long-tail films (outside the 20% most-voted films of the catalog, scored by the same availability-aware hybrid) to the candidate pool and **reserves slots** for them: Familiar 0%, Balanced 10%, Discover 20% of a list (never more than half), spread through the list rather than piled at the end. Measured on 500 test users (`pipeline/tail_eval.py`, `artifacts/metrics/long_tail.json`), Balanced: NDCG@10 0.110 with no slots, 0.105 with 10%, 0.100 with 20%; Discover: 0.105, 0.102 (10%), 0.095 (20%). Coverage of MovieLens films in the top 10 rises from 7.6% to 9.7% (Balanced 20%). The NDCG cost is an upper bound, because a film nobody in MovieLens rated cannot score. Note the two definitions of "long tail": the report's 0.1% counts MovieLens rating counts; the engine counts TMDB votes across the whole catalog, so its no-slot figure is 1.3%.

### 6.9 Surprise Me
1. Unseen hybrid candidates with Match % ≥ 60 and community rating ≥ 6.5/10.
2. Main genre not in the user's top 3 genres.
3. Below the 70th popularity percentile.
4. Weighted random pick by Match %. Reason: "Outside your usual genres, but people with similar taste rated it highly." Logged with `source = surprise_me`.

### 6.10 For Tonight (constraint-based recommendation)
- **Inputs:** mood (Funny / Scary / Intense / Relaxed / Feel-good / Mind-bending), runtime band (< 90, 90–120, 120+), language (any or chosen), optional genres.
- **Knowledge base:** `engine/config/moods.yaml` maps each mood to genres and keywords. Example: Scary = Horror, or Thriller with keywords such as "supernatural" or "serial killer". This rule table *is* the knowledge base; the viva notes say so.
- **Steps:** apply the constraints as hard filters, then rank the survivors by the user's hybrid score, then show the top 10 with reasons.
- **Relaxation when nothing matches:** relax in this order: runtime band (widen by one band), then genres, then mood (nearest mood), and language last. Tell the user what was relaxed: "No Malayalam horror under 90 minutes, so here are some up to 120."
- "Perfect Popcorn Films" is a fixed preset of this feature (section 7).

### 6.11 Explanations
- Each film keeps its per-source scores. Reasons come from the sources that really contributed.
- Rules: at most 3 reasons; a reason is shown only if its source gave **at least 20% of the final score**; evidence must be real (a real film the user liked, a real count of similar users). The lab's User Inspector shows the numbers behind every reason.

| Source | Example | Evidence |
|---|---|---|
| Item CF | Because you liked *Prisoners* | the user's liked film with the highest similarity |
| Content | Similar themes to *Zodiac* and *Se7en* | top 2 liked films by content similarity |
| User CF | 14 people with similar taste rated this 8+ | real neighbor count |
| SVD / ALS | Fits the kind of films you rate highly | the user's top genre among high ratings |
| Preferences | Matches your interest in Korean thrillers | onboarding answers |
| Popularity | Loved by FlickRaven viewers | none |
| Rerank | Adds variety to your list | the genre it adds |

### 6.12 Freshness
Personal rails are recomputed on every home-page load, and any rating, like, dislike or list change takes effect on the next load. No stale caching of personal results.

---

## 7. Home page rails

### 7.1 The rails
Hero: the top 5 picks (hybrid + MMR in the user's current mode), rotating. Hero films are not repeated in the rails.

| # | Rail | Powered by | Definition | Shown when |
|---|---|---|---|---|
| 1 | Top Picks For You | Full hybrid + MMR | the main output | always |
| 2 | Because You Liked "X" | Item CF (content fallback for films with few ratings) | neighbors of the film the user most recently liked, rated ≥ 8/10 or picked in onboarding; up to 2 of these rails | ≥ 1 like, high rating or onboarding pick |
| 3 | Continue Exploring | Recent views | films opened in the last 14 days and not yet rated, listed or disliked; newest first | ≥ 1 view |
| 4 | Based On Your Ratings | SVD only | the explicit-ratings model on its own | ≥ 5 ratings |
| 5 | People With Your Taste Loved | User CF only | films the user's nearest neighbors rated highly | ≥ 10 ratings and ≥ 20 usable neighbors |
| 6 | Movies In Your Languages | Hybrid + language constraint | the user's chosen languages | always |
| 7 | New & Notable | Content + TMDB popularity | releases from the last 18 months (catalog part C), ranked by content match × popularity; live new-movie cold start | always |
| 8 | Hidden Gems | Hybrid + popularity rule | Bayesian rating ≥ 7.5/10 and in the less popular half of the catalog | always |
| 9 | Award Winners & Nominees | Wikidata awards + hybrid | award-won or nominated films, ranked for the user | enough items |
| 10 | Perfect Popcorn Films | For Tonight preset | Action, Adventure, Comedy, Animation or Sci-Fi; 90–130 min; Bayesian rating ≥ 6.5/10; ranked by hybrid | always |
| 11 | International Cinema | Hybrid + language constraint | films **outside** the user's chosen languages | always |
| 12 | Most Loved | Popularity baseline | Bayesian average, language-aware | always |
| 13 | Discover Something Different | Discover-mode MMR | λ = 0.55, β = 0.20 whatever the slider says | always |

Dropped from v1.0: **Trending Now** (no live trend data; merged into New & Notable) and **Critically Acclaimed** (no critic data; would copy Most Loved).

### 7.2 Page rules
- **No duplicates:** the server plans the whole page in one call, filling rails top-down, and a film appears **at most once** on the page.
- **Hide short rails:** a rail with fewer than 8 films after de-duplication is hidden.
- **Stage-based rail count:** about 7 rails for a brand-new user, up to 13 for an established one (from the "Shown when" column).
- **Page weight:** only rails near the screen are drawn; images load lazily at the size they are displayed.
- Every card shown is logged in `recommendation_logs` with its rail, position, scores and reason.

---

## 8. Pages, navigation and UI

### 8.1 Navigation
Desktop (v5, 2026-11-11, Apple TV look): a floating dark-glass sidebar on the left, no top bar.
```
[FlickRaven logo] [hide]
[Search]
Home  Discover  Perfect Pick  Genres  My List  Activity
...
[avatar + name]  (menu: Taste DNA, Taste Profile, Recommendation report, Preferences, Account, Sign in / out)
```
- Active page: light pill that slides to the new page. Inactive: plain, subtle hover.
- A tall button at the top right of the sidebar hides it (a window icon, left half filled). When hidden, a small glass button with the same icon (and a search button) floats at the top left; the choice is remembered in this browser. Content and hero glide over when it opens or closes (transforms only, no layout animation); reduced-motion users get no glide.
- Phone: logo, search and avatar at the top; the five tabs in a bottom tab bar (no sidebar).
- There is no Missions tab: the Discovery Journey page and its link were removed (2026-11-11). `/missions` redirects Home. The API and the `mission_state` table remain, unused.
- `/lab` is not in the navigation (a small footer link for the demo).
- The logo is Aryav's own artwork (`web/public/flickraven-logo.png`, bird alone in `flickraven-mark.png`, also the browser icon), made transparent from the PNG he supplied; a larger or SVG original would be sharper.

### 8.2 Routes
`/` Home · `/discover` · `/genres` · `/genres/:slug` · `/movie/:id` · `/my-list` · `/activity` · `/search?q=` · `/login` · `/register` · `/onboarding` · `/lab`

### 8.3 Pages
| Page | Contents |
|---|---|
| Onboarding | Step 1: pick 5–10 liked films from a grid mixing popular and international titles. Step 2: languages (only those with ≥ 150 films). Step 3: favorite genres. Step 4: optional disliked genres. Step 5: first recommendations. |
| Home | Hero, Discovery Mode control, For Tonight entry button, rails (section 7). |
| Movie page | (v5) Full-bleed header like the Home hero (the title's own backdrop on the right, black fade on the left, back button), then title, year, certification, runtime, genres, Match % chip, IMDb score, synopsis, buttons Where to watch / Add to list / Why this?, Like, Dislike, Watched and the rating stars, and a tab row (Overview, More like this, Cast & crew) that scrolls to each part. Where to watch: each service is a button that opens that service's own search for the title (a search link, not a confirmed page; unknown services fall back to a web search), plus a JustWatch link. More Like This is 3 portrait tiles per row (2 on phones), 9 titles, with the Match % badge on the poster (only where it exists), then title, IMDb score and year, and one real reason. Older text follows: backdrop, poster, title, Match %, community rating, year, runtime, genres, language, country, certification, release date, synopsis, the user's rating (5 stars, half steps), rating distribution (1–10 bars), "Why you're seeing this", director, writers, cast, studios, keywords, awards (when Wikidata has them), More Like This (poster grid, 8 titles, "View all" page at `/movie/:id/similar` with Load more; same type only, with reasons). Actions: Add to / Remove from List, Like, Dislike, Rate, Mark Watched. |
| Quick View | Opened by the card's chevron: backdrop, title, Match %, rating, year, runtime, genres, language, short synopsis, Why This, actions, "View full details". |
| Discover | Type tabs (Movies, Series, Anime, All), a scrolling genre pill row (Anime is its own genre), a Filters panel (language, country, released from / until, length, IMDb score, Match % for films with a personal sort, streaming service, with a count of filters on and Clear), sort, Surprise Me, For Tonight panel. Country and streaming-service choices come from `GET /api/discover/options` (what the catalog really holds); the streaming filter means a subscription or free service as TMDB lists it for India. |
| Perfect Pick | `/pick`: three one-tap questions (mood, time: under 90 min / about 2 h / plenty / a series of 25 h or less, familiar / a bit of both / adventurous), then three picks with real reasons. `POST /api/recs/perfect-pick`. Films: For Tonight's mood and runtime rules ranked by the hybrid score; familiar = best scores, adventurous = score and novelty together (never below a score floor), balanced = best two plus one surprise. Profile languages by default; if fewer than three fit, other languages are included and the page says so (switch to include them anyway). Series: 25 hours or less in total, ranked by the series ranking, no Match %. "Not these" asks again excluding what was shown. |
| Genres | Genre grid; a genre page ranks its films **for this user** with the hybrid score. |
| Search | Title, cast, director, genre, language (Postgres full-text search). |
| My List | Saved films; sort by recently added, rating, year, genre. |
| Activity | Timeline of views, ratings, likes, dislikes, list changes, watched marks. |
| Taste Profile | Top genres (bar chart), top languages, preferred eras, average rating given, like/dislike ratio, films rated, films saved, Discovery preference. All from real interaction data. No giant dashboard. |
| Lab | Section 13. |

### 8.4 Movie cards
- **Shape:** landscape 16:9 backdrop. Title drawn as text over a dark gradient at the bottom; TMDB title logo used where it exists.
- **Density (Aryav's design decision, 2026-10-07):** large cards, about 2–3 visible per rail on desktop with the next card partly visible; about 2 on tablet; about 1–1.5 on phone.
- **Normal state:** artwork, title, year, community rating, language, Match % on personal rails.
- **Hover (desktop only):** scale about 1.05, lift 4 px, 150–250 ms, after a short hover-intent delay so moving across a rail doesn't flicker. Reveals Match %, genre, one-line synopsis, Like, Dislike, Add to List, and the Quick View chevron. Rails have vertical padding so enlarged cards are never clipped.
- **Touch:** no hover panel. Tap opens the movie page. The chevron is always visible.
- **Rail arrows (v5):** dark-glass round buttons, always visible on every rail (desktop), hidden at the start and end of a rail, eased smooth scroll of about one screen. Card widths are a share of the space next to the sidebar.

### 8.5 Hero
- Full-bleed header (reaches behind the sidebar): the pick's own 16:9 backdrop fills the screen, black fade on the left for the text, picture clear on the right (v5, from Aryav's reference screenshot of a film page).
- Shows: title, year, runtime, genres, language, Match % chip, IMDb score, short synopsis, one-line reason, and three glass buttons: **View details**, **Add to list** (toggles), **Why this?** (opens the explanation panel). Like and Dislike live on cards and film pages. **No Play button.**
- Side arrows (desktop) and dots to move between the 5 picks. Changing pick: 0.9 s eased crossfade with a slight zoom, text rises in.
- On scroll: the picture drifts and dims.

### 8.6 Visual identity
- Colors: background `#080808`, surface `#141414`, surface 2 `#1B1B1B`, text `#FFFFFF`, muted `#A7A7A7`. Accent: FlickRaven crimson about `#C8102E` (hover `#E0263F`), used for Match %, active rating stars and focus rings, never for large blocks.
- Fonts (free): Inter for interface text; Inter Tight or Manrope for titles.
- Motion: 150–250 ms for interactions, 400–600 ms for the hero. Respect `prefers-reduced-motion`.
- **Not allowed:** purple or blue "AI" gradients, neon, glowing borders, floating blobs, gradient headline text, glass everywhere, oversized pills, 3D tilt cards, particles, constant motion, bounce effects, generic dashboard layouts.
- Footer: TMDB attribution notice and logo.

---

## 9. Frontend component hierarchy

```
<App>
  <QueryProvider> <AuthProvider> <Router>
    <AppShell>
      <NavBar>                    translucent -> solid on scroll
        <Logo/> <NavTabs/> <SearchButton/> <AvatarMenu/>
      <MobileTabBar/>             < 768px only
      <Outlet/>                   (routes below)
      <QuickViewPanel/>           global, opened by any card chevron
      <Toast/>                    "Added to My List" etc.
      <Footer/>                   TMDB attribution

Routes:
  HomePage
    <Hero>
      <HeroBackdrop/>             crossfade + blurred tint from dominant_color
      <HeroInfo/>                 title, meta, match %, reason, actions
      <HeroPager/>                arrows + dots
    <DiscoveryModeControl/>       Familiar <-> Balanced <-> Discover
    <TonightButton/>              opens <TonightPanel/>
    <LazyRail title source> x up to 13   drawn only when near the screen
      <RailArrows/>               glass buttons
      <MovieCard> x N
        <CardArtwork/>            16:9 backdrop, title text or logo over a gradient
        <CardMeta/>
        <CardHoverPanel>          desktop only
          <ActionButtons/> <QuickViewChevron/>
  MoviePage
    <DetailHero/> <ActionBar/> <RatingStars/> <RatingDistribution/>
    <WhyThis/> <FactsGrid/> <CreditsRow/> <KeywordChips/> <Rail "More like this"/>
  DiscoverPage
    <FilterBar/> <SearchInput/> <SurpriseMeButton/> <DiscoveryModeControl/>
    <TonightPanel/>               mood, runtime, language, genres -> results + "what we relaxed"
    <MovieGrid/>
  GenresPage, GenrePage -> <GenreTile/>, <MovieGrid/>
  MyListPage -> <SortMenu/> <MovieGrid/>
  ActivityPage -> <TasteProfile/> <ActivityTabs/> <ActivityTimeline/>
  SearchPage -> <MovieGrid/>
  OnboardingPage -> <StepPickMovies/> <StepLanguages/> <StepGenres/> <StepDislikes/> <StepDone/>
  LoginPage, RegisterPage
  LabPage
    <ModelTable/> <ColdStartChart/> <NewMoviePanel/> <DiversityTradeoffChart/> <WeightsTable/>
    <UserInspector/> (pick a user -> candidate scores per source)
    <ShillingPanel/> <TasteMap/> <NcfRow/> (advanced)
```

Shared hooks: `useFeedback(movieId)` (optimistic updates for like/list/rate), `useLogEvent()`, `useRecs(mode)`.

Design tokens, card behavior and motion: section 8. They live in `tailwind.config.ts` and `styles/tokens.css`.

Small technical traps:
- **Dominant color**: compute it in the pipeline (from the backdrop image, with Pillow) and store it in `movies.dominant_color`. Reading pixels in the browser from TMDB images hits cross-origin canvas errors.
- **Image sizes**: cards are large (roughly 550–750 px wide on desktop), so they use TMDB `w780` backdrops with `w1280` for high-density screens (`srcset`), `w1280` for the hero, `w342` posters for Quick View. Never `original`. All images below the fold use lazy loading.

---

## 10. Database schema (PostgreSQL)

Rule: **MovieLens ratings do not go into Postgres.** 25 to 32 million rows are only needed for training. They live as Parquet files in the pipeline. Postgres stores the catalog, aggregates, and the website's own users and events.

```sql
-- Catalog
movies (
  id              serial primary key,
  tmdb_id         int unique not null,
  ml_movie_id     int unique,              -- null for films with no MovieLens data
  imdb_id         text,
  title           text not null,
  original_title  text,
  overview        text,
  release_date    date,
  year            smallint,
  runtime_min     smallint,
  original_language char(2),
  spoken_languages text[],
  countries       text[],
  certification   text,                    -- e.g. "UA 13+", "PG-13"
  poster_path     text,
  backdrop_path   text,
  dominant_color  char(7),                 -- precomputed hex for the hero tint
  tagline         text,
  studios         text[],
  logo_path       text,                    -- TMDB title logo, if any
  catalog_part    char(1),                 -- 'A' MovieLens, 'B' international, 'C' recent releases, 'D' Hollywood enrichment
  -- aggregates (from MovieLens, scaled to 1-10, refreshed by pipeline)
  ml_rating_count int default 0,
  ml_rating_mean  numeric(4,2),
  rating_hist     int[10],                 -- count per 1..10
  popularity_score real,                   -- Bayesian-average based
  tmdb_vote_count int,                     -- popularity signal for parts B and C
  search_vector   tsvector                 -- title + cast + director, for search
)
genres        (id serial pk, name text unique, slug text unique)
movie_genres  (movie_id fk, genre_id fk, primary key (movie_id, genre_id))
people        (id serial pk, tmdb_person_id int unique, name text, profile_path text)
movie_credits (movie_id fk, person_id fk, role text,   -- 'cast','director','writer'
               character text, credit_order smallint)
keywords      (id serial pk, name text unique)
movie_awards  (movie_id fk, award text, category text, year smallint,
               result text check (result in ('won','nominated')),
               wikidata_id text)   -- from Wikidata
movie_keywords(movie_id fk, keyword_id fk, primary key (movie_id, keyword_id))

-- Users
users (
  id            serial pk,
  email         citext unique,             -- null for guests
  password_hash text,                       -- null for guests
  display_name  text,
  is_guest      boolean default false,
  created_at    timestamptz default now(),
  onboarded_at  timestamptz
)
user_preferences (
  user_id         int pk fk,
  languages       text[],
  liked_genre_ids int[],
  disliked_genre_ids int[],
  discovery_mode  text default 'balanced',   -- familiar | balanced | discover
  updated_at      timestamptz
)
onboarding_picks (user_id fk, movie_id fk, created_at, primary key (user_id, movie_id))

-- Explicit feedback
ratings (
  user_id   int fk, movie_id int fk,
  rating    smallint check (rating between 1 and 10),
  created_at timestamptz, updated_at timestamptz,
  primary key (user_id, movie_id)
)
reactions (                                  -- current like/dislike state
  user_id int fk, movie_id int fk,
  value   smallint check (value in (-1, 1)),
  updated_at timestamptz,
  primary key (user_id, movie_id)
)
user_movie_list (user_id fk, movie_id fk, added_at timestamptz, primary key (user_id, movie_id))
watched (user_id fk, movie_id fk, marked_at timestamptz, primary key (user_id, movie_id))

-- Implicit feedback: append-only event log
interactions (
  id         bigserial pk,
  user_id    int fk,
  movie_id   int fk,
  event_type text not null,  -- detail_view, quick_view, search_click, list_add, list_remove,
                             -- like, dislike, watched, rate, hero_view
  value      real,           -- e.g. the rating, or null
  source     text,           -- which rail/page it came from, e.g. 'rail:hidden_gems'
  position   smallint,       -- rank in that rail
  created_at timestamptz default now()
)
create index on interactions (user_id, created_at desc);

-- What we showed, so the lab can show click-through per rail and per model
recommendation_logs (
  id          bigserial pk,
  request_id  uuid,
  user_id     int fk,
  surface     text,          -- 'hero','top_picks','because_you_liked:123', ...
  movie_id    int fk,
  rank        smallint,
  final_score real,
  match_pct   smallint,
  components  jsonb,         -- {"content":0.71,"item_cf":0.55,"svd":0.80,...}
  reason_code text,
  mode        text,
  page_id     uuid,          -- one home-page load, used for de-duplication checks
  created_at  timestamptz default now()
)
```

Notes:
- `ratings`, `reactions`, `user_movie_list`, `watched` hold **current state** (fast reads for the UI). `interactions` holds **history** (what the engine and Activity page read). Every action writes to both. This avoids recomputing state from the log on every page load.
- Event weights live in a config file (`engine/config/event_weights.yaml`), not the DB. Easier to version and to show in the lab.
- Hover is **not logged**. It is noise and floods the table.
- Mood rules (`moods.yaml`), rail rules (`rails.yaml`) and the threshold table (`thresholds.yaml`) are config files too.

---

## 11. API (FastAPI, all JSON, prefix `/api`)

Auth: JWT in an httpOnly cookie. Guests get a cookie-based guest user on first visit.

| Area | Method + path | Purpose |
|---|---|---|
| Auth | `POST /auth/register` | Create account (or upgrade current guest) |
| | `POST /auth/login`, `POST /auth/logout` | |
| | `POST /auth/guest` | Create guest user + cookie |
| | `GET /me` | Current user, onboarding status, counts |
| Onboarding | `GET /onboarding/candidates` | Grid of ~60 films to pick from (popular + international mix) |
| | `POST /onboarding` | Save picks, languages, liked/disliked genres |
| Preferences | `GET/PUT /me/preferences` | Edit languages, genres, discovery mode |
| Movies | `GET /movies/:id` | Full detail page payload |
| | `GET /movies/:id/similar?offset=&limit=` | More like this: same-type titles from the offline similarity table (keywords, plot, topic, genre, people, language, era, fame) with reasons; see decisions-log 2026-11-10. `GET /admin/similar/:id` (owner only) shows every candidate with its signals |
| | `GET /movies?genre=&lang=&decade=&runtime=&country=&min_rating=&sort=&page=` | Discover filters |
| Search | `GET /search?q=` | Title, cast, director, genre, language (Postgres full-text search) |
| Genres | `GET /genres`, `GET /genres/:slug/movies` | Genre grid and personally ranked genre page |
| Recs | `GET /recs/home?mode=` | Hero + all visible rails, planned together and de-duplicated (section 7.2) |
| | `GET /recs/rail/:key?mode=&cursor=` | "See more" inside one rail |
| | `POST /recs/tonight` `{mood, runtime, languages, genres}` | For Tonight results plus the list of relaxed constraints and a message |
| | `GET /recs/surprise` | One Surprise Me pick |
| | `GET /recs/explain/:movie_id` | Full "Why this?" |
| Feedback | `PUT /ratings/:movie_id` `{rating}`, `DELETE /ratings/:movie_id` | Rate / unrate |
| | `PUT /reactions/:movie_id` `{value: 1 or -1}`, `DELETE ...` | Like / dislike / clear |
| | `PUT /list/:movie_id`, `DELETE /list/:movie_id`, `GET /list?sort=` | My List |
| | `PUT /watched/:movie_id`, `DELETE ...` | Mark watched |
| | `POST /events` `{movie_id, event_type, source, position}` | Lightweight implicit events (views, clicks) |
| Activity | `GET /activity?type=&cursor=` | History timeline |
| | `GET /me/taste-profile` | Top genres, languages, eras, avg rating, counts |
| Lab | `GET /lab/models`, `GET /lab/metrics`, `GET /lab/cold-start`, `GET /lab/new-movies`, `GET /lab/diversity` | Precomputed offline results |
| | `GET /lab/weights` | Current hybrid weights per user stage |
| | `GET /lab/user/:id/candidates` | Per-source scores for a user's recs |
| | `GET /lab/shilling`, `GET /lab/taste-map` | Precomputed advanced results (read only; no live attacks) |

Recommendation item shape:
```json
{
  "movie": {"id": 123, "title": "...", "year": 2013, "poster": "...", "backdrop": "...",
            "genres": ["Crime","Thriller"], "language": "en", "runtime": 153,
            "logo": "...", "community_rating": 8.1, "dominant_color": "#2a3b4c", "overview_short": "..."},
  "score": 0.83,
  "match_pct": 87,
  "reasons": [{"code": "item_cf", "text": "Because you liked Prisoners", "anchor_movie_id": 45, "share": 0.41}],
  "user_state": {"rating": null, "reaction": 0, "in_list": false, "watched": false}
}
```
- `user_state` is included so cards render buttons correctly without extra calls.
- `reasons` holds at most 3 entries; `share` is that source's part of the final score (section 6.11).

---

## 12. Evaluation

### 12.1 Protocol
- Per-user time split (section 4.4). The global-cutoff split is a second check.
- **Evaluated users:** a fixed random sample of about 5,000 test users who have at least one relevant test film (same sample for every model and experiment).
- **Full ranking:** each model ranks every catalog film the user has not rated in training. No "1 relevant + 99 random" sampling (sampled metrics can reorder models; Krichene and Rendle, 2020).
- **Fair tuning:** each model's own settings are tuned on validation first (section 5), then the hybrid is tuned on top. The test set is used once.
- **Uncertainty:** report each metric with a 95% bootstrap confidence interval over users. Small gaps (for example, hybrid vs SVD) are only claimed if the intervals support it.

### 12.2 Which metrics apply to which model
| Model | MAE / RMSE | P@10, R@10, MAP@10, NDCG@10 | Coverage, diversity, novelty, long-tail share |
|---|---|---|---|
| Bias baseline (global mean + user bias + film bias) | yes | n/a | n/a |
| Popularity | n/a | yes | yes |
| Content-based | n/a | yes | yes |
| User CF | yes | yes | yes |
| Item CF | yes | yes | yes |
| Funk SVD | yes | yes | yes |
| Implicit ALS | n/a | yes | yes |
| Hybrid (each Discovery Mode) | n/a | yes | yes |
| NCF (advanced) | n/a | yes | yes |

"n/a" because those models rank films and do not predict a rating.

### 12.3 Metric definitions
- Relevant = test rating ≥ 7/10 (section 4.3).
- **Catalog coverage:** share of the catalog that appears in at least one evaluated user's top 10.
- **Intra-list diversity:** 1 − average content similarity between pairs of films in a top-10 list.
- **Novelty:** average −log2(popularity share) of recommended films.
- **Popularity bias:** long-tail share (percent of recommended films from the less popular 80% of the catalog) and average popularity percentile of recommended films.

### 12.4 Experiments
1. **Model comparison:** the table in 12.2 on the test set.
2. **Cold-start users:** for each evaluated user, keep only k behavioral ratings, k = 0, 2, 5, 10, 20, in two versions: **without onboarding** (their earliest k ratings) and **with onboarding** (simulated onboarding as in section 6.6, plus the next k ratings). Test films are always later ones. Chart: NDCG@10 against k, one line per model, solid with onboarding and dashed without. The gap between the two lines is what onboarding is worth.
3. **New movies:** for the held-out films (section 4.4), hit rate@50 = how often a held-out film the user later rated ≥ 7/10 appears in their top 50. Compare content, CF models and hybrid. Expected: CF models score zero, content and hybrid do not.
4. **Diversity trade-off:** sweep λ from 0.5 to 1.0 in steps of 0.05. Chart: NDCG@10 against intra-list diversity, with Familiar, Balanced and Discover marked.
5. **Calibration check:** predicted Match % against the observed share of relevant films, per user stage.
6. **Global-cutoff check:** the model comparison rerun on the global time split.

All results are written to `artifacts/metrics/*.json`; the lab reads only these files.

---

## 13. Research Lab (`/lab`)

A plain, professional page for the professor. It exposes the engine; it is not an analytics dashboard.

- **Models:** each model, what it does, its role on the site, its tuned settings.
- **Model comparison:** the table from 12.2 with confidence intervals.
- **Cold start:** NDCG@10 against known ratings, one line per model, plus the onboarding point.
- **New movies:** the hit-rate result.
- **Diversity:** NDCG@10 against diversity, with the three modes marked.
- **Hybrid weights:** the tuned weights per user stage.
- **User Inspector:** pick a site user or a sample MovieLens user and see their stage, onboarding count, behavioral interaction count, and for each recommended film the per-source scores, final score, Match % and the reasons shown on the site.
- **Catalog audit:** catalog composition per part, films per language, and measured Hollywood coverage (top 500 and top 1,000 US films), read from `artifacts/metrics/catalog_audit.json`.
- **Advanced panels:** shilling results, taste map, NCF row (when built).
- Charts follow one consistent style; numbers come only from `artifacts/`.

---

## 14. Advanced modules

### 14.1 Shilling attack and defense (lab only, precomputed)
- **Targets:** 5 low-popularity films.
- **Attacks:** average attack and bandwagon attack; attack size 1%, 3% and 5% of users; filler of about 5% of the catalog per fake profile.
- **Measure:** prediction shift on the target films and hit ratio@10 (share of real users who get the target in their top 10), for user CF, item CF and SVD, before and after the attack.
- **Defense:** flag suspicious profiles with simple detection features (rating deviation from the film's mean agreement, similarity to their nearest neighbors, rating variance), remove them, retrain, measure again.
- **Report the defense's cost:** detection precision and recall, and the false-positive rate (real users wrongly removed).
- No live attack controls on the website.

### 14.2 Taste map (lab only)
- PCA of SVD film vectors to 2D, colored by main genre. The current user's folded-in vector is placed with the same projection and labeled "You".
- Not t-SNE: t-SNE cannot place a new user without redrawing the whole map.
- It is a picture of the model, not a recommender.

### 14.2b Taste DNA (v3, 2026-11-10)
- **Traits** (15): plot complexity, fast pacing, slow burn, psychological tension, emotional depth, dark atmosphere, character focus, mystery and suspense, unexpected twists, humour, romance, world-building, realism, violence (dialogue only from viewer tags).
- **Provenance:** TMDB has no such data. Values come from `RULES` in `api/app/services/taste_dna.py`: our own mapping of TMDB keywords and genres to traits (value 1 - exp(-sum of weights)); a title with fewer than 3 keywords is "unknown", never zero. Viewer tags count for a title only once 3 different users tagged it. The page says this.
- **Feedback:** optional tags after rating (`title_feedback_tags`; "what did you enjoy" and "what did not work"); only for titles you rated, liked or marked watched.
- **Profile:** weighted by liked (rated 7+, liked, picks, watched) and disliked titles with a catalog-mean prior worth 4 titles; negatives kept separate; a trait counts as a preference only with 3+ supporting titles and a lean of 0.05 over the catalog mean. Refine My Taste sets a trait to more/less (`user_preferences.taste_overrides`).
- **Use:** the Taste DNA row re-orders the recommender's own top 300 by trait fit; it is NOT part of the hybrid score or Match %. Explanations name only traits the title has (value 0.5+) and the user prefers.
- **Not yet evaluated offline:** no ratings exist with which to test whether the fit improves ranking, so it is not blended into the hybrid.

### 14.2c Discovery Journey (missions, v3, 2026-11-10) — page removed 2026-11-11

The page and its navigation links were removed at Aryav's request (see 8.1); the API and table below remain but nothing in the website calls them.

- Page `/missions` ("Your Discovery Journey"), tabs: Recommended (not started), Active (some progress), Completed, Explore (hidden missions and extra genre ideas).
- Missions: International Explorer (5 countries beyond the US and India), Beyond your language (4 other languages), Through the decades (5 decades), Classic cinema (3 films before 1980), Mini-series weekend (1 series of 8 episodes or fewer), and personal "New to <genre>" missions (the biggest genres with fewer than 3 of your titles).
- Progress is read from real activity (watched, rated, liked) on every request and never stored. A completed mission shows the date of the activity that reached the goal (replayed from activity times).
- Every mission has a "Why this" sentence built only from counts in the user's own history. Recommended is ordered by a simple fit (for example, the more of your films are US/Indian, the higher International Explorer ranks); this is a heuristic, not a model.
- "Not for me" hides a mission (it moves to Explore and can be brought back); a finished mission cannot be hidden. Only dismissals and the date of a personal genre mission are stored (`mission_state`).
- Ideas under each open mission are well-known unseen titles. When Taste DNA has at least 5 liked titles they are re-ordered by trait fit and the page says so; otherwise by popularity.
- The completion card is drawn in the browser and downloaded on click; nothing is shared automatically.

### 14.3 NCF (lab only)
- NeuMF (GMF + MLP) in PyTorch on CPU, trained on positives (rating ≥ 7/10) with 4 sampled negatives per positive.
- Evaluated with exactly the same full-ranking protocol as the other models.
- Not served on the website: it learns one vector per training user and has no cheap fold-in.
- If it loses to SVD or ALS, report it plainly (Rendle et al., 2020 found the same).

---

## 15. Implementation phases

Every phase ends with: run it, test it (unit + scenario tests), fix it, commit and push, and write that phase's **viva notes** page in `docs/viva/` (what was built, the formula in plain English, why it was chosen, and the 5 questions an examiner is most likely to ask).

| Phase | Work | Done when |
|---|---|---|
| 1. Foundation | Git repo, Vite app, FastAPI app, Postgres in Docker, SQLAlchemy + Alembic, `.env`, test runners | The web app calls the API, the API reads the database, tests run |
| 2. Data pipeline | Steps 1–8 and 12 (section 4.5) | Catalog in Postgres; metadata report per language; 20 films spot-checked by hand |
| 3. Baseline models | Popularity, content, user CF, item CF; the evaluation code with unit tests on a tiny hand-made dataset | Metrics for 4 models on validation |
| 4. Matrix factorization | Funk SVD + fold-in, ALS + fold-in | Metrics; fold-in checked against full retraining for a few users |
| 5. Hybrid engine | Candidates, filters, normalization, stage weights, calibration, MMR, explanations, Surprise Me, For Tonight logic | Hybrid metrics; calibration check passes |
| 6. Experiments | Cold start, new movies, diversity sweep, global-cutoff check | All lab JSON files exist |
| 7. Frontend foundation | Shell, navigation, cards, rails, arrows, movie page, auth, guest users, onboarding | Register, onboard, see recommendations |
| 8. Integration + core feedback | Engine served through the API; **rating, like and dislike** | Scenario test "rating changes recommendations" passes |
| 9. Full interaction system | My List, watched, event logging, Activity, Taste Profile, recommendation logs | Every action shows in Activity and in the engine |
| 10. Premium frontend | Hero and transitions, dominant color, hover cards, glass arrows, Quick View, navbar on scroll, Discovery Mode control, rating animation, For Tonight panel, loading and empty states, responsive layouts | Checked at desktop, tablet and phone widths; no clipping; nothing hover-only on touch |
| 11. Research Lab | Section 13 | Every number traceable to an `artifacts/` file |
| 12. Advanced | Shilling, then taste map, then NCF | Each has its lab panel |
| 13. Final validation and demo prep | All scenario tests, report, demo accounts, backup video | Demo rehearsed end to end |

---

## 16. Scenario tests (run after every phase from Phase 8 on)

1. **New user:** onboarding with 5 crime thrillers returns recommendations, most of the top 20 are crime, thriller or mystery, and the user is still **cold** (onboarding_count = 5, b = 0).
2. **Stage counter:** views alone never change the stage; after 3 ratings or likes the stage becomes "warming" and the blend weights change accordingly.
3. **Established user:** after 15+ ratings, CF sources carry most of the weight.
4. **Rating changes the list:** rating three crime thrillers 9+ changes the top 20, and at least 5 of them are crime or thriller.
5. **Dislike:** a disliked film never appears again; a disliked genre disappears from personal rails.
6. **My List:** adding a film raises the scores of similar films (implicit signal works).
7. **Discovery Mode:** Discover gives higher intra-list diversity than Familiar for the same user.
8. **New movie:** a New & Notable film with zero MovieLens ratings can reach a user's rails through content. Since 2026-11-10 any film without collaborative factors is scored by content and popularity alone, mapped onto the MovieLens scale by probability matching (decisions-log), so it also reaches Top Picks when it fits the user's taste.
9. **Item similarity:** "Because You Liked *Prisoners*" contains films a person would accept as similar (checked by hand once, then frozen as a regression list).
10. **User CF:** the prepared demo account has at least 20 usable neighbors and a full "People With Your Taste" rail.
11. **No duplicates:** no film appears twice on the home page.
12. **Explanations:** every reason shown matches a source that gave at least 20% of the score.

---

## 17. Demo plan

Two accounts:
- **Fresh account** (created live) for demos 1–3.
- **Prepared account** with about 40 real ratings for demos 4–8, so user CF has enough data.

| # | Demo | Account | What to say |
|---|---|---|---|
| 1 | Sign up, pick 5 films, languages, genres; recommendations appear | Fresh | Cold start: the user is still "cold" (5 onboarding picks, 0 real actions), so onboarding + content + popularity drive the list |
| 2 | Rate *Prisoners* 9, *Se7en* 10, *Zodiac* 9, reload | Fresh | 3 real actions: the stage switches to "warming" (show it in the User Inspector) and fold-in updates the profile without retraining |
| 3 | Open a recommended film, show "Why you're seeing this" | Fresh | Explanations come from the sources that contributed |
| 4 | "Because You Liked *Prisoners*" | Prepared | Item-based CF, adjusted cosine |
| 5 | "People With Your Taste Loved" | Prepared | User-based CF, Pearson with significance weighting |
| 6 | Switch Familiar to Discover | Prepared | MMR reranking; show the diversity chart in the lab |
| 7 | Hidden Gems and New & Notable | Prepared | Popularity bias and new-movie cold start |
| 8 | Research Lab | either | Model table, cold-start chart, User Inspector |

Backup: a recorded video of the full demo in case the laptop or network fails.

---

## 18. Folder structure

```
cinematch/
├─ README.md                      how to set up and run everything
├─ docker-compose.yml             postgres only
├─ .env.example                   DATABASE_URL, TMDB_API_KEY, JWT_SECRET
├─ scripts/                       PowerShell helpers (Windows has no `make`): db.ps1, api.ps1, web.ps1, test.ps1, data.ps1
│
├─ engine/                        shared Python package (pipeline + API both import it)
│  ├─ pyproject.toml
│  ├─ tests/                      unit tests on tiny hand-made data
│  └─ cinematch_engine/
│     ├─ config/
│     │  ├─ event_weights.yaml
│     │  ├─ modes.yaml            λ and β per Discovery Mode
│     │  ├─ moods.yaml            For Tonight knowledge base
│     │  ├─ rails.yaml            rail definitions and "shown when" rules
│     │  └─ thresholds.yaml       the single threshold table (section 4.3)
│     ├─ data/                    loaders for artifacts, id maps
│     ├─ models/
│     │  ├─ popularity.py
│     │  ├─ content.py
│     │  ├─ item_cf.py
│     │  ├─ user_cf.py
│     │  ├─ svd.py                train + fold_in
│     │  ├─ als_implicit.py       train + fold_in
│     │  └─ ncf.py                advanced, lab only
│     ├─ profile.py               user profile and stage from ratings + events
│     ├─ candidates.py
│     ├─ filters.py
│     ├─ blend.py                 normalization + stage weights
│     ├─ calibrate.py             Match %
│     ├─ rerank.py                MMR, novelty, Discovery Mode
│     ├─ rails.py                 page planning and de-duplication
│     ├─ surprise.py
│     ├─ tonight.py               constraints + relaxation
│     ├─ explain.py
│     ├─ metrics.py               all evaluation metrics
│     └─ security/shilling.py     advanced
│
├─ pipeline/
│  ├─ 01_download_movielens.py
│  ├─ 02_select_catalog.py
│  ├─ 03_fetch_tmdb.py
│  ├─ 04_fetch_awards_wikidata.py
│  ├─ 05_clean.py
│  ├─ 06_ratings_prep.py
│  ├─ 07_split.py
│  ├─ 08_features_content.py
│  ├─ 09_train_models.py
│  ├─ 10_tune_hybrid.py
│  ├─ 11_evaluate.py
│  ├─ 12_load_db.py
│  ├─ 13_shilling.py              advanced
│  ├─ 14_taste_map.py             advanced
│  ├─ 15_ncf.py                   advanced
│  ├─ export_site_feedback.py
│  ├─ curated/language_quotas.yaml
│  └─ run_all.py
│
├─ api/
│  ├─ pyproject.toml
│  ├─ alembic/                    migrations
│  ├─ app/
│  │  ├─ main.py                  loads artifacts on startup
│  │  ├─ db.py
│  │  ├─ auth.py
│  │  ├─ models/                  SQLAlchemy tables
│  │  ├─ schemas/                 Pydantic request/response shapes
│  │  ├─ routers/
│  │  │  ├─ auth.py  movies.py  search.py  genres.py
│  │  │  ├─ recs.py  feedback.py  activity.py  onboarding.py
│  │  │  └─ lab.py
│  │  └─ services/
│  │     ├─ recommender.py        wraps cinematch_engine for requests
│  │     └─ events.py
│  └─ tests/
│     ├─ test_*.py                endpoint tests
│     └─ scenarios/               the scenario tests in section 16
│
├─ web/
│  ├─ package.json  vite.config.ts  tailwind.config.ts  tsconfig.json
│  ├─ index.html
│  └─ src/
│     ├─ main.tsx  App.tsx  routes.tsx
│     ├─ api/                     typed fetch client + TanStack Query hooks
│     ├─ components/
│     │  ├─ layout/               NavBar, MobileTabBar, Footer, AppShell
│     │  ├─ hero/                 Hero, HeroBackdrop, HeroInfo, HeroPager
│     │  ├─ rail/                 LazyRail, RailArrows
│     │  ├─ card/                 MovieCard, CardArtwork, CardHoverPanel, QuickViewPanel
│     │  ├─ feedback/             RatingStars, ActionButtons, RatingDistribution
│     │  ├─ discovery/            DiscoveryModeControl, SurpriseMeButton, TonightPanel
│     │  ├─ explain/              WhyThis
│     │  └─ lab/                  ModelTable, ColdStartChart, NewMoviePanel, DiversityChart,
│     │                           WeightsTable, UserInspector, ShillingPanel, TasteMap
│     ├─ pages/                   Home, Movie, Discover, Genres, Genre, MyList,
│     │                           Activity, Search, Onboarding, Login, Register, Lab
│     ├─ hooks/                   useFeedback, useLogEvent, useScrollSolidNav
│     ├─ styles/                  tokens.css, fonts
│     └─ lib/                     tmdbImage(), formatters
│
├─ notebooks/
│  ├─ 01_eda.ipynb                sparsity, long tail, language mix, metadata completeness
│  ├─ 02_model_comparison.ipynb
│  └─ 03_cold_start.ipynb
│
├─ data/                          gitignored: raw/, processed/
├─ artifacts/                     gitignored: models/, metrics/, lab/
└─ docs/
   ├─ viva/                       one plain-English page per phase
   ├─ report/                     final project report
   ├─ architecture.md
   └─ demo-script.md
```

---

## 19. Before Phase 1

Needed from Aryav:
1. **Deadline:** the date of the demo or viva.
2. **TMDB API key:** free account at themoviedb.org. It goes in a `.env` file on the laptop; never pasted in chat.
3. **GitHub:** a private repository connected to this project.
4. ~~Laptop RAM~~: checked, 15.4 GB.
5. **College rule:** whether AI-written code is allowed for the mini project and whether it must be disclosed.

Laptop tools checked on 2026-10-07: Git, Python 3.12, Node 24, Docker and WSL2 are installed. PostgreSQL runs in Docker.


### 14.2d AI assistant (Gemini Flash, 2026-11-11)

- Floating "Ask FlickRaven" chat (bottom right). `POST /api/assistant/chat`, `GET /api/assistant/status`. Model: Google Gemini Flash (`GEMINI_MODEL`, default `gemini-2.5-flash`; check the current model name and the free-tier terms before relying on it). Key only in the Render environment variable `GEMINI_API_KEY`. Hidden entirely when the key is missing or `ASSISTANT_ENABLED=false`.
- Open topics are allowed (recommendations, a title's story, general film chat). Limits: 30 messages per signed-in person per day, 8 for guests (in process memory: a restart resets them), 1,000 characters per message, 12 messages of history, 700 output tokens.
- Grounding: titles the person names are looked up in our catalog and their synopsis is sent with the question; the model is told to say when it is unsure. Titles it recommends are written [[Title (Year)]] and are linked only if they exist in the catalog; others show as plain text. Plot spoilers are written between || || and shown blurred until tapped.
- Privacy: the model gets the chat, a taste summary (top genres, up to 6 liked titles) and the synopses; never name, email or ids. The privacy page says free-tier prompts may be used by Google. Chats are not stored.
- Stability (2026-11-11): the chat panel is opaque (no blur, and no blurred buttons inside it: nested backdrop filters can render a black screen), it scrolls only its own list, a failure shows the reason with "Try again" (the message is kept), a crash inside the chat hides only the chat (error boundary), and a message is given back when Gemini fails. Connect timeout 5 s, total 25 s. Logs hold the error type or HTTP status only.
- Not built: taste-aware ranking inside the assistant, saving chats, AI-written Taste DNA text.

### 14.2f Movies, Shows and media types (2026-11-11)

- Nav: Home, Discover, Movies, Shows, Perfect Pick, Genres, My List, Activity (phones: six tabs). `/movies` = films only. `/shows` = TV series and anime TV only, built from the series rows (`/recs/series-rails`, `/recs/kind/*`), never the film list filtered. Discover tabs: Movies, Shows, Movies and shows; `?type=show` opens it on Shows.
- API: `type` on `/movies` = movie (default), show (series + anime TV), series, anime, all. Genre pages (`/genres/{slug}/movies?type=all|movie|show`) work for every genre; films are ranked by the hybrid, shows by `kind_rank`, and the two lists are woven by relative position because their scores are not on one scale. Match % is shown for films only.
- Anime genre = Japanese-language animation with title_type movie (films) or anime (TV anime); plain `series` titles are not Anime.

### 14.2g Perfect Pick v2 (2026-11-11)

- Six questions (shown only when relevant): movie, series or either; mood (the six For Tonight moods plus Emotional, Suspenseful, Mysterious, or none); genres (many, optional); languages (English, Hindi, Korean, Japanese, Tamil, Telugu, Malayalam, other, or any); time (films: under 90 / 90-120 / 2-3 h / any; series: one season / under 10 h / 10-20 h / 20-30 h / any; either: under 2 h / 3 h / 10 h / any) plus finished or airing for series; familiar, balanced or unexpected. Back works at every step.
- Order of work: hard limits (kind, time, finished/airing) -> candidates from the film hybrid or the series ranking -> score `0.55 relevance percentile + 0.25 picked-genre fit + 0.20 mood fit` -> novelty by the last answer (floors as before) -> a genre-diversity pass (each next pick loses 0.25 x its genre overlap with those already picked) -> a reason per checked condition. Series time is episodes x episode length (a series with unknown length never counts as "under 10 hours"; "one season" uses the season count). The weights are a design starting point, not tuned on data.
- Fewer than three fit: mood is relaxed first, then genres, then language; the reply names what was relaxed. "Include other languages" drops the language limit.
- Match % is shown for films only. `POST /api/recs/perfect-pick` body: kind, mood, genres, languages, time, status, adventure, other_languages, exclude.

### 14.2h Hindi and Indian rows (2026-11-11)

- New Home collections, offered only to people with a language interest: Hindi Movies Picked for You, Modern Bollywood (2010 onwards), Hindi Thrillers and Crime, Hindi Comedy, Bollywood Rom-Coms (Hindi interest), and Indian Cinema Beyond Bollywood (Tamil, Telugu, Malayalam, Bengali, Kannada, Marathi, Punjabi; interest in any of them). "Retro Hindi Classics" is now "Bollywood Classics" and stays for everyone.
- Interest = languages chosen in the profile, plus the language of anything rated 7+, liked, watched or picked in onboarding. English-only people get no Hindi quota; guests get none of the gated rows. Rows are ordered by the user's own hybrid score (popularity where the engine cannot score a film), and need at least 6 films.
- A persistent explicit-language lift for ranking itself came in #78.

### 14.2i Daily Home, more diversity, anime hits, feel-good and romance (2026-11-11)

- **Home changes every day.** `GET /recs/home` passes a seed (user id + date in India time + mode) to `engine.home`: the hero is drawn from the top 12 picks (the best two always stay), each row from the top 3x of its ranking (the best three stay, order kept), and the order of the themed rows is shuffled. Same person, same day: same page. Series rows, the Series and Anime rails (first page), and the film collections are refreshed the same way (`app/services/daily.py`, `rerank.refresh`). The day changes at midnight IST. Without a seed (tests, evaluation) the plan is unchanged and deterministic.
- **More diversity.** MMR values moved from lambda 0.95/0.75/0.55 to 0.9/0.65/0.5 (familiar/balanced/discover), beta 0/0.05/0.2 to 0.02/0.08/0.25, long-tail share 0/10/20% to 5/15/25%. Hand-tuned: the NDCG@10 cost has NOT been re-measured; run `pipeline/tail_eval.py` and the segment evaluation on the laptop. The first 12 places of the Series and Anime rails hold at most 6 titles of one language.
- **Anime hits.** `kind_rank("anime")` weighs fame (TMDB vote-count percentile) as much as quality: score = 0.5 taste + 0.25 quality + 0.25 fame (without taste: half quality, half fame). The series-rails endpoint adds "Anime everyone is talking about" (most-voted anime with quality 7.3+, the first six stay fixed) first among the themed rows, then "Romantic anime" and "Feel-good anime".
- **Feel-good and Romance everywhere.** Home film rows "Feel-Good Films For You" and "Romance For You" (engine, ranked by the person's hybrid score, no horror/war/crime/thriller in feel-good); series themes "Feel-good series" and "Romantic series" (romance found by keyword or Soap, since TMDB TV has no Romance genre); film collections Feel-Good Films, Romance, Romantic Drama; mood "Romantic" in For Tonight and Perfect Pick (Feel-good already existed).

### 14.2e Taste Evolution (2026-11-11)

- On `/taste-dna`, "How your taste changed": per month (last 6 with activity) the top 3 genres of titles liked or rated 7+, and, with 5+ titles in the latest two months and 5+ before, the genre that rose and the one that fell (change of 10 points or more). Counts only; `GET /api/me/taste-evolution`.

### 14.2j Mood chips on every genre list (2026-11-11)
- Every genre page and Discover has a mood row: **Any mood / Feel-good / Romantic**. It works on top of the chosen genre and the Movies / Shows choice, for films and shows.
- API: `vibe=feelgood|romance` on `/movies` and `/genres/{slug}/movies`.
- Feel-good: a light genre (Comedy, Romance, Family, Animation, Music), none of Horror, Crime, War, Thriller, Mystery, rated 6.5 or more.
- Romantic: the Romance or Soap genre, or a "romance" / "love" keyword (TV has no Romance genre).
- Ranking stays personal; the chip only narrows the list. A mood with no matches in a genre (for example Horror + Romantic) shows an empty list.
