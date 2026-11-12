# Gemini tag pilot: automatic evaluation (2026-11-12/13)

Bounded pilot approved by Aryav on 2026-11-12. The task was to tag 60 films, tags only, twice, with the same prompt.
Script: `pipeline/gemini_tag_pilot.py`. Everything is under `work/gemini-tag-pilot/`.

Not touched:
- `artifacts/models/ai_similar_films.json` (hash checked before and after every run, unchanged).
- Any file the site builds or deploys, the database, Taste DNA and scoring.

This report covers the automatic checks only. Human correctness comes from the blind review sheet: Aryav fills it in,
then `python -m pipeline.score_review` scores it.

## Setup

- **Sample.** 60 films, seed 11, stratified:
  - 12 Hindi controls (they already have tags from the older combined prompt).
  - 10 other Indian films: Tamil, Telugu and Malayalam.
  - 8 Korean, 6 Japanese, 14 English and 10 world-cinema films.

  Inside each group the sample spreads over fame bands (top 10% / 50 to 90% / bottom half of TMDB votes), decades and
  primary genre.
  - 16 films are flagged hard. 10 were picked on purpose (dark comedies, slow thrillers, mixed tone); 6 more match the
    broad "comedy plus crime/thriller/horror/war/drama" rule.
  - The "world" group includes one Kannada film.
- **What was sent:** title, year, up to 4 genres and the first 350 characters of the TMDB plot. No user data.
- **Prompt:** `tags-only-v1`, using the vocabulary from `ai_similar_films` (hash `fb082399be`), not expanded:
  - mood: 0 to 3 tags
  - tone: one tag, or null
  - pacing: one tag, or null
  - themes: 0 to 3 tags
  - gap: an optional short phrase saying what the theme list misses

  The prompt says plainly that an empty field is better than a guess.
- **Model:** `gemini-3.5-flash-lite` answered every successful call. No fallback was needed.
- **Calls:** 12 batches of 10 (2 runs × 6). All 12 were answered in the end.
  - The first pass hit Google HTTP 503 ("overloaded") on 14 of 20 requests, so the approved rerun of the 6 missing
    batches was needed.
  - That rerun used 8 to 11 of the 12 extra requests allowed. The exact number is unknown because a session restart
    killed one rerun after a logged success and before its call log was saved. The script now saves after every batch.
- **Tokens and cost:** 11,474 input and 9,412 output. That is **$0.027 at paid-tier list prices**, and $0 if the key
  is on the free tier.
  - The tier was assumed free (same key as the earlier Hindi run).
  - But Google's response reports `serviceTier: standard`, so the key may be on the paid tier. Check in Google AI
    Studio.

## Results

**Repeatability: run 1 vs run 2, same prompt, all 60 films.**

| Family | Exact match | Mean Jaccard | Pilot gate (≥ 80%) |
|---|---|---|---|
| Tone | 88.3% | | passes the repeatability half |
| Pacing | 91.7% | | passes the repeatability half |
| Mood (set) | 51.7% exact set | 0.758 | **below** |
| Themes (set) | 58.3% exact set | 0.751 | **below** |

For mood and themes the two runs mostly overlap but rarely agree exactly. Usually one of the 3 words changes.

**Abstention (empty or null) almost never happens:** mood 1.7%, tone 0 to 1.7%, pacing 0%, themes 3 to 7%.
- Gemini answers even when the prompt invites it not to.
- That includes 2025 and 2026 releases and very obscure films, where its knowledge is likely thin.
- Whether those confident answers are right is exactly what the human review must show.

**Vocabulary gaps:** run 1 named a missing theme for 22 of 60 films (37%). Examples: "religious riots and communal
conflict", "time loop and desperate rescue", "nuclear anxiety and atomic destruction", "short-term memory loss
comedy", "breakup consultancy business", "obsession with cursed media". Two cautions:
- Gaps cluster by batch: films P11 to P20 all have one. That suggests the model fills the optional field per batch,
  not per film.
- The 37% is therefore an upper estimate.

Real recurring gaps worth a future vocabulary review: communal or religious conflict, time loops and other sci-fi
devices, obsession, nuclear and apocalyptic themes. Per the brief, the vocabulary was not expanded.

**Invalid words:** 1 word in total was outside the fixed lists and was dropped. No film went unanswered.

**Taste DNA consistency (run 1).** This is a consistency check, NOT ground truth: Taste DNA's keyword rules are not
authoritative labels.

| Concept | Films where Taste DNA has evidence | Pilot agrees | Pilot claims it where Taste DNA is silent |
|---|---|---|---|
| Dark (mood dark, gritty or eerie) | 5 | 5 (100%) | 32.7% of 55 |
| Slow burn (pacing) | 1 | 1 | 16.9% of 59 |
| Fast (pacing) | 1 | 1 | 11.9% of 59 |
| Humour (mood funny or satirical, or tone light or satirical) | 24 | 17 (71%) | 16.7% of 36 |

Where Taste DNA says something, Gemini mostly agrees. Taste DNA is silent on most films, because TMDB keywords rarely
carry pacing or atmosphere, and Gemini fills those gaps. Whether its fills are right needs the human review.

**Historical Hindi controls** (run 1 vs the older combined prompt, 12 films). This is a different prompt, so it is a
historical comparison, not repeatability:
- tone 83% agree
- pacing 83% agree
- mood Jaccard 0.47 (8% exact)
- themes Jaccard 0.63 (33% exact)

Tone and pacing are fairly stable across prompts. Mood words shift a lot.

**By language group (repeatability, run 1 vs run 2).** About 6 to 14 films per group, so these are directional only.

| Group | Films | Tone exact | Pacing exact | Mood Jaccard | Themes Jaccard | Gap rate | Themes left empty |
|---|---|---|---|---|---|---|---|
| Hindi controls | 12 | 83% | 92% | 0.83 | 0.86 | 42% | 0% |
| Other Indian | 10 | 80% | 90% | 0.76 | 0.75 | 30% | 0% |
| Korean | 8 | 100% | 88% | 0.90 | 0.88 | 25% | 0% |
| Japanese | 6 | 100% | 100% | 0.64 | 0.67 | 50% | 17% |
| English | 14 | 86% | 93% | **0.58** | 0.71 | 36% | 14% |
| World | 10 | 90% | 90% | 0.88 | 0.62 | 40% | 10% |

No group stands out as clearly worse. English mood is the least stable (0.58), probably because the English sample
holds the most hard and mixed-tone films.

**Hard cases (16 films):** tone 69% exact (vs 88% overall), pacing 94%, mood Jaccard 0.78, themes Jaccard 0.70. Tone is
the family that suffers on mixed-tone films, as expected.

## Verdict so far (before the human review)

- **Tone and pacing** are repeatable enough to go on to the human review. They pass the repeatability half of the gate.
- **Mood and themes** miss the 80% repeatability bar (Jaccard about 0.75). Even if the human review finds them
  accurate, they would need either consensus tagging (several runs, keeping the words that repeat) or a smaller,
  clearer vocabulary before they could be trusted.
- **Abstention does not work as hoped.** The model almost never leaves a field empty. If trust matters more than
  coverage, the next version needs an explicit confidence field, or consensus across runs as the abstention signal
  (a word that does not repeat is treated as unknown).
- **60 titles is a pilot gate, not proof** that the tags are reliable across languages.

## Next step

Aryav's blind review (about 20 minutes) of `review-sheet.csv`. Fill `mood_ok`, `tone_ok`, `pacing_ok` and `themes_ok`
with right, wrong or unsure (r, w or u also work). For a "(none)" tag, "right" means it was rightly left empty. Then:

    .\.venv\Scripts\python.exe -m pipeline.score_review

The language mapping (`mapping-HIDDEN-until-review.csv`) and `sample.json` stay on the laptop and are not committed,
so the review stays blind.

Out of scope, and not done: full-catalogue tagging, production artifacts, DB changes, Taste DNA or scoring changes,
deploys.
