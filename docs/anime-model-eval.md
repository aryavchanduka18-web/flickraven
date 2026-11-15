# Anime model: offline evaluation (2026-11-15)

**Status: offline evidence only. Not merged, not uploaded, not deployed.** The model is trained on the 2023 MyAnimeList
lists, so it needs Aryav's explicit go before merge (his rule for the 2023 data). Production stays on today's ranking
until then.

## What changes

- Anime series lists (`kind_rank("anime")`: hero and Top Picks anime lane, "Anime for you", Anime page, `/recs/kind/anime`),
  the anime-film lane of the mixed Home, and the Anime page films row.
- A new model learned from real anime lists, one model for anime series AND anime films together
  (`pipeline/anime_model.py`). Only anime it knows are re-ordered, and only inside the places they already hold in
  today's list ("slot-preserving"). Anime it does not know (mostly very new titles) do not move.
- The setting is picked by how many distinct catalog anime the person likes that the model knows (current ratings of
  7+, likes, onboarding picks; one rating per title, seasons are one title; watched and My List are not taste):

| Liked anime the model knows | Setting |
|---|---|
| 0 | today's order, unchanged |
| 1 to 7 | "short": half EASE (lambda 30,000), half cosine neighbours, by percentile in the list |
| 8 to 24 | "mid": EASE, lambda 30,000 |
| 25+ | "long": EASE, lambda 300 |

- People who like no known anime (and everyone when the file is missing, broken, partial or `ANIME_MODEL_DISABLED=true`)
  get exactly today's order. Film lists are untouched.

## Data

- 2023: MyAnimeList user scores (Kaggle "Anime Dataset 2023"), converted to `user_id, anime_id, rating` with usernames
  dropped and ids permuted (`data/raw/anime2023/rating.csv`, 24.3M scores, 270k users). Static snapshot: no
  timestamps, so this is not a time-based test.
- 2017: Kaggle "Anime Recommendations Database" (`data/raw/anime/rating.csv`), used as the second check.
- Matching: one id map (`data/processed/anime_model_map.csv`, MyAnimeList id to TMDB id via the anime-lists project,
  seasons, OVAs and specials merged into their series). Titles with ratings: 2023 1,235 of 1,482 series and 462 of 629
  films; 2017 771 and 351.

## Method (`pipeline/anime_rank_eval.py`)

- Users: list users with 10+ liked (7+) matched anime. 500 validation users (to choose settings) and 1,200 test users
  (the numbers below), disjoint. Every model is fitted WITHOUT these users.
- Per user, 20% of the liked titles are hidden (the targets). Profiles: "full" (the rest of the list), "light15" (15
  random liked titles) and "light5" (5). The rest of the list is excluded as already seen, so all scenarios rank the
  same unseen titles.
- "today" is the served engine over the local database. "served" runs the engine's own `anime_order` (the code in this
  PR) with the models fitted on training users only.
- NDCG@10, paired per user (same users, same hidden titles for both rankings), 95% interval = 1.96 standard errors.
- Both rankings order exactly the same list. The gain is ranking, not extra candidates.

## Results: the served rule, 2023 lists, test users

| List | Profile | Users | Today | Served | Diff [95% CI] |
|---|---|---|---|---|---|
| Series | full | 1,191 | 0.137 | 0.394 | +0.258 [0.244, 0.271] |
| Series | light15 | 1,191 | 0.149 | 0.313 | +0.164 [0.151, 0.176] |
| Series | light5 | 1,191 | 0.138 | 0.259 | +0.122 [0.110, 0.133] |
| Films | full | 839 | 0.170 | 0.519 | +0.349 [0.326, 0.372] |
| Films | light15 | 839 | 0.116 | 0.375 | +0.259 [0.237, 0.281] |
| Films | light5 | 839 | 0.060 | 0.262 | +0.202 [0.183, 0.221] |

By tier (full profiles; light15 is all "mid", light5 all "short"):

| List | Tier | Users | Today | Served | Diff [95% CI] |
|---|---|---|---|---|---|
| Series | long | 778 | 0.143 | 0.445 | +0.302 [0.288, 0.316] |
| Series | mid | 413 | 0.124 | 0.298 | +0.174 [0.148, 0.199] |
| Films | long | 661 | 0.174 | 0.514 | +0.340 [0.315, 0.365] |
| Films | mid | 178 | 0.157 | 0.538 | +0.382 [0.325, 0.438] |

Validation users agree within about 0.01 everywhere except films/mid (0.471, 178 users).

The rule keeps most of the best single setting per profile size (series 0.394 vs 0.418, 0.313 vs 0.320, 0.259 vs
0.263; films 0.519 vs 0.543, 0.375 vs 0.383, 0.262 vs 0.273). Known weak spot: series users with 8 to 24 liked anime in
full lists. A back-of-envelope from the totals suggests the "long" setting might do about 0.02 better for them, while
light15 (also 8 to 24) prefers "mid" by about 0.01. Not tuned further, to avoid fitting the test.

## Stricter relevance: 8+ = a hit

Only the hidden targets change (they must be rated 8+). Training, sampled users and short profiles are the same.
No sampled user lacked an 8+ rating overall. Per list, users with no 8+ title of that kind drop out: series 1,187 of
1,191 kept, films 772 of 839.

Same users in both runs (7+ vs 8+), served minus today:

| List | Profile | Common users | 7+ diff [95% CI] | 8+ diff [95% CI] |
|---|---|---|---|---|
| Series | full | 1,180 | +0.259 [0.245, 0.272] | +0.261 [0.247, 0.275] |
| Series | light15 | 1,180 | +0.164 [0.152, 0.176] | +0.158 [0.145, 0.170] |
| Series | light5 | 1,180 | +0.123 [0.111, 0.134] | +0.117 [0.105, 0.128] |
| Films | full | 671 | +0.351 [0.326, 0.376] | +0.361 [0.336, 0.387] |
| Films | light15 | 671 | +0.260 [0.236, 0.284] | +0.268 [0.242, 0.294] |
| Films | light5 | 671 | +0.192 [0.172, 0.212] | +0.192 [0.170, 0.214] |

The gain holds at 8+: it moves by at most 0.006 on the same users, and every interval overlaps.

## Second dataset (2017 lists), same pattern

Best settings per profile, NDCG@10 test: series today 0.147 / 0.170 / 0.152 (full / 15 / 5), best model 0.426 / 0.330 /
0.275; films today 0.181 / 0.128 / 0.060, best 0.538 / 0.363 / 0.176. Content similarity alone scores 0.07 on series,
worse than plain popularity (about 0.19). It carried 30% to 70% of today's anime score, which is the main reason
today's ranking is weak.

## Common catalogue

PENDING

## Real FlickRaven users per tier (live database, read-only count, 2026-11-15)

42 users: 37 have no liked anime the model knows (no change), 4 have 1 to 7 ("short"), 0 have 8 to 24, 1 has 25+. So
today the model reaches 5 people. Small risk, small benefit until more anime fans join; the "short" tier is where new
anime fans start.

## Speed and memory

PENDING (memory: about 4 MB resident for the three models).

## Limits

- MyAnimeList users are not FlickRaven users. Offline NDCG must not be read as expected clicks or engagement.
- Titles the lists do not know keep today's places, untested.
- Licence: the lists come from MyAnimeList via Kaggle uploads; Aryav accepted that risk, credited on the Terms page.
