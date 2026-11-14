# Phase 14: Accounts, hosting, franchises, people pages, confidence and the v2 look (viva notes)

The site is live at https://cinematch-16hy.onrender.com (Render: one Docker web service and one
managed PostgreSQL 17 database). Everything below runs on the real catalog and the real models.

## Questions Aryav asked (answers to give in the viva)

**Is the big banner on Home (the hero) based on My List, or on the recommender?**
The recommender. The hero is the top 5 of the hybrid recommender's Top Picks for this user
(`OnlineEngine.home`: `hero = picks[:5]`). My List, ratings, likes, dislikes and views are not shown
there directly; they are *signals* that change the user's profile, and so change the picks.

**Why does the navigation sit at the bottom on a phone and at the top on a laptop?**
By design. Under 768 px wide the site shows a phone-style tab bar at the bottom (now a floating pill),
within thumb reach; on wider screens the same tabs sit in the top bar.

## Accounts
- Passwords: bcrypt hashes; rules checked on the server (8+ characters, a letter and a number, not a
  common password, not containing the email name) and shown live on the sign-up form.
- Sign-in lockout: 5 wrong passwords for one email (or 20 from one address) in 15 minutes lock sign-in
  for 15 minutes (HTTP 429 with Retry-After). Counters live in memory (one web process).
- Session cookie: httpOnly, SameSite=Lax, Secure on the hosted site. Each token carries the moment it
  was issued; changing the password stamps `users.password_changed_at` and every older token stops
  working (other devices are signed out), the current device gets a new one.
- Account page: rename, change password, sign out, delete account (all data cascades; password needed,
  guests need none). No email service, so no email verification or password reset (future work).

## Hosting
- One container: the built website plus FastAPI, which serves it with an SPA fallback. On start it runs
  `alembic upgrade head`, unpacks the model bundle and listens on `$PORT`.
- The repository is public and the models are built from MovieLens ratings, which may not be
  redistributed, so the models are never committed. `scripts/deploy_data.py` puts them into the
  private database (in 2 MB parts that survive dropped connections, checksum verified) and the server
  unpacks them.
- Memory: the first measurement peaked at 504 MB in a 512 MB container. User CF kept five derived
  copies of the 3-million-rating training matrix; they now share two sparsity structures. Scores stayed
  bit-identical for every user and source; the peak fell to 378 MB.

## Franchises
- Each film stores its TMDB collection. 470 missing parts of franchises already in the catalog were
  added (released, 200+ votes, 60+ minutes, passing the metadata gate) as part D, outside the
  evaluation universe. The catalog grew from 14,292 to 14,762 films.
- **The evaluation did not change**: `pipeline/eval_fingerprint.py` hashes the ratings, splits, features,
  every fitted model and every result (46 files): all identical. The 14,292 existing content rows are
  identical too (label columns are ordered by the stage that added them).
- Film page: "More from John Wick" (every part in release order), "More from Marvel" (also DC, Pixar,
  Studio Ghibli, DreamWorks), and for films without a franchise "More from <director>" and
  "Franchise films like this".

## More Like This is similarity only
It used to take half its list from item-CF co-ratings, which surfaced Hollywood hits under *Sholay*.
Now it is content similarity alone, the same for every user: content cosine + 0.3 genre overlap
(Jaccard) + 0.2 same original language + 0.1 release-year closeness (exp(-gap/12)). Sholay now lists
Hindi films (Amar Akbar Anthony, Khakee, Karan Arjun). Scenario test 13 guards it.

## Cast and crew pages
`/person/:id`: photo, roles, number of FlickRaven films, known-for titles, then "Recommended for you"
(their unrated films the recommender scores highest) and the filmography with All / Acting /
Directing / Writing tabs. Match % appears only where the engine scores the film.

## Recommendation confidence (model agreement)
- For the film, each source's score is turned into a percentile among all films that source can score
  for this user (100 = its top pick). Groups in user words: Collaborative (SVD, item CF, user CF),
  Content (TF-IDF plus labels), Behavioral (ALS on implicit feedback), Popularity. Hybrid = Match %.
- **Agreement = 100 x (1 - 2 x standard deviation of the weighted sources' percentiles)**: 100 when they
  rank it the same, near 0 when one says top and another says bottom. High >= 75, Moderate >= 50, Low
  below. With fewer than two sources the card says so and shows no number.
- Why this is honest: a 93% match is not equally reliable when the models disagree; the card shows it
  instead of hiding it. Technical details map the user words to the models; NCF is Lab-only.

## The v2 features
- **Tune** (four sliders, saved per account): adventurous lowers the MMR lambda (more diverse lists),
  hidden gems raises the novelty weight, international boosts films outside English and the Indian
  languages (or the reverse), length prefers longer or shorter films. All four at the middle give
  exactly the untuned lists, so the offline evaluation is unaffected.
- **Your Current Phase**: films close to what the user liked, rated 7+, saved or watched in the last 21
  days: 0.6 x percentile of content similarity to those films + 0.4 x percentile of the usual hybrid
  score. The subtitle names the real top genre of those films.
- **Dislike reasons**: genre -> that genre is avoided; too long -> Length slider down; language -> the
  language balance shifts; already seen -> marked watched; too similar -> more diverse lists.
- **Discover sorts**: Recommended (with Tune), Highest match, Hidden gems (match x (1 - fame
  percentile)), Most novel (genres you have not liked first), plus popular, rated, newest.
- **Why? panel**, agreement labels on cards, hover card whose details scroll on their own, cast photos,
  collection rows (Rom-Com with Leap Year and 17 others), For Tonight banner, phone pill bar.

## Bugs found by using the live site
- Opening a film the user had liked or rated 8+ crashed its own explanation (the film was used as its
  own reason), which the site showed as "Film not found". Fixed; scenario test 14 guards it.
- Genre and Discover pages showed only the first 40 films (Thriller has 3,379). They now page through
  every film.
- A disliked film stayed on Home until a reload, and the hover card showed the old like/dislike state.
  Every cached list is now patched the moment you act (optimistic update), and the hover card reads the
  same fresh state as the film page.

## Final fixes (Oct 10)
- **Films you acted on are never recommended back.** The engine's `excluded()` set is every film you
  rated, liked, disliked, watched or picked in onboarding (plus disliked genres). Top Picks, the hero,
  every Home row, Discover's personal sorts, For Tonight and Surprise Me all leave them out. Two leaks
  were found and closed: "Continue Exploring" (recently opened films) brought back liked or watched
  films, and the themed collection rows hid only disliked or watched films, not rated ones. Scenario
  tests 16 and 18 check every Home row and collection after each action.
- **More Like This still shows them.** It is similarity alone (same for every user), so a film you rated
  can appear under a similar film. That is intended: it answers "what is like this film", not "what
  should I watch next".
- **One Match % per film.** Home used to compute Match % from the candidate-pool score (each source's
  percentile among its own top 50), while the film page, Why? and lists used the catalog-wide score
  (percentile among every film). The same film could read 87% on Home and 91% on its page. Every page now
  uses the catalog-wide score; the pool score still decides what is picked and in what order. Honest
  caveat if asked: the calibrator was fitted on pool scores, so on this scale Match % reads a few points
  high; it is a guide, and ranking is unaffected. Scenario 17 checks Home = film page = Why?.
- **Match % is the headline, agreement is secondary.** Cards, the hero and the film page show the Match %
  big and bold; model agreement is small text ("17% model agreement · low"). They answer different
  questions: Match % = how likely you are to rate it 7+; agreement = how much the separate models agree
  on that. A high match with low agreement means one strong signal (for example your watch history)
  carries it while the others are less sure.
- **Final live check** (guest account on the Render site): crime and thriller picks gave 10 of 10 top
  picks in crime, thriller or mystery, no Horror (the disliked genre), no duplicates, Match % and reasons
  on every pick; after a dislike, like, 9/10 rating and watched mark, none of the four came back.
- **Declined:** a filmography rule that would have added 2,357 films (for example 20 more Shah Rukh Khan
  films) was built and tested but not merged, at Aryav's choice; the catalog stays at 14,762 films.
