# Gemini tags follow-up: consensus and 400 non-Hindi films (2026-11-12/13)

> **Blind review of 60 of these 400 films:** open `work/gemini-tag-pilot/review-sheet-400.csv`. For each film, fill
> `mood_ok`, `tone_ok`, `pacing_ok` and `themes_ok` with **r** = right, **w** = wrong or **u** = unsure. "(none)" marked
> right means the tag was rightly left empty.
>
> Then run:
>
>     .\.venv\Scripts\python.exe -m pipeline.score_review --sheet review-sheet-400.csv --mapping mapping-400-HIDDEN-until-review.csv --evaluation evaluation-400.json --name 400
>
> About the sheet:
> - It shows the consensus tags: words kept only when both runs agree, and tone or pacing only when both runs agree.
> - Films: 15 Tamil/Telugu/Malayalam, 9 Korean, 9 Japanese, 15 English and 12 world, seed 31. 16 of them are flagged
>   hard (mixed tone).
> - The language mapping stays on the laptop and is not committed.

This is an offline follow-up to the 60-film pilot (#137, #139, #140). Script: `pipeline/gemini_tag_scale.py`.

It reuses the pilot's tags-only prompt (`tags-only-v1`), the existing vocabulary (not expanded), the model and the call
rules. It does not touch `artifacts/models/ai_similar_films.json` (hash unchanged), the database, Taste DNA, scoring or
deploys.

**Cost: $0.** Aryav confirmed the key is on the free tier. At paid list prices it would have been about $0.19.

**Requests:** 57 of the 80 allowed: 7 for step 1 and 50 for step 2.
- 11 of them were Google HTTP 503 overloads, not quota or billing errors.
- Step 2 stopped itself once (3 failures in a row) and was resumed once, 10 minutes later.
- No run was lost to the laptop sleeping: the call log is saved after every batch.

Tokens: 71.6k input and 65.4k output.

## Consensus rule

- **Mood and themes:** a word is kept if at least 2 runs give it (2 of 3 runs in step 1; both runs in step 2).
- **Tone and pacing:** kept if at least 2 runs give the same value.
- Otherwise the field is empty, which counts as unknown.

## Step 1: the pilot's 60 films, third run, consensus of 3

- Run 3 vs runs 1 and 2:
  - Tone: 92% and 85% exact.
  - Pacing: 87% and 88% exact.
  - Mood: Jaccard 0.71 and 0.74.
  - Themes: Jaccard 0.73 and 0.78.

  That matches run 1 vs run 2 (0.88 / 0.92 / 0.76 / 0.75), so the earlier repeatability was not a fluke.
- **Coverage:** 95% of films keep at least 1 mood and 1 theme after consensus.
- **Fields left empty:** mood 1.7%, tone 1.7%, pacing 0%, themes 3.3%.
- **Against `claude-review-labels.csv`** (#140's review of run 1's tags):

  | Family | Run-1 tags judged right | Consensus keeps them | Judged wrong | Consensus changes them |
  |---|---|---|---|---|
  | Mood | 56 | 84% | 1 | 0 of 1 |
  | Tone | 52 | 96% | 2 | 0 of 2 |
  | Pacing | 48 | 100% | 0 | n/a |
  | Themes | 54 | 78% | 3 | 2 of 3 |

  Consensus keeps most of what the reviewer called right. Tone and pacing are almost untouched. It drops the less
  stable mood and theme words, some of which were right; that is the price of keeping only words that repeat. It
  fixes 2 of the 3 wrong theme tags (an unsupported "ambition", for example). It does not fix the 2 wrong tones,
  because all 3 runs repeat the same mistake. Consensus removes noise, not systematic bias.

## Step 2: 400 non-Hindi films, 2 runs, consensus of 2

- **Sample (seed 23):** 100 Tamil/Telugu/Malayalam, 60 Korean, 60 Japanese, 100 English and 80 world films. It is
  stratified by fame band (top 10% / 50 to 90% / bottom half of TMDB votes), decade and primary genre, and the pilot's
  60 films are excluded. Batches are 20 films per call (the pilot used 10).
- **Repeatability (run 1 vs run 2):**
  - Tone: 90.0% exact.
  - Pacing: 89.7% exact.
  - Mood: Jaccard 0.77 (57% exact set).
  - Themes: Jaccard 0.78 (61% exact set).

  Close to the 60-film pilot (0.88 / 0.92 / 0.76 / 0.75): tone and pacing above 80%, mood and themes just below.
- **Abstention on single runs** is almost zero again (mood 1.5%, tone 0.3%, pacing 0%, themes 6%). Consensus is what
  produces the "unknown" fields.
- **Consensus coverage:** 88.7% of films keep at least 1 mood and 1 theme. Fields left empty: mood 3.5%, tone 10.2%,
  pacing 10.2%, themes 9.2%.
- **Vocabulary gaps:** run 1 names a theme the 23-word list cannot express for 43.8% of films. Examples: societal
  oppression of women, generational curses, imperial court intrigue, samurai honour and sacrifice, end-of-life
  decisions, mental illness and obsession. As in the pilot, this is an upper estimate (gap notes cluster per batch).
  Recurring candidates for a future, versioned vocabulary: women and patriarchy, honour and duty, obsession and mental
  illness, curses and fate, court and palace intrigue.

**By language group:**

| Group | Films | Tone exact | Pacing exact | Mood Jaccard | Themes Jaccard | Consensus keeps mood + theme | Tone empty after consensus |
|---|---|---|---|---|---|---|---|
| Tamil / Telugu / Malayalam | 100 | 95% | 93% | 0.76 | 0.80 | 94% | 5% |
| Korean | 60 | 93% | 83% | 0.71 | 0.86 | 93% | 7% |
| Japanese | 60 | 82% | 90% | 0.79 | 0.75 | 88% | 18% |
| English | 100 | 90% | 89% | 0.78 | 0.78 | 87% | 11% |
| World | 80 | 88% | 91% | 0.78 | 0.74 | 81% | 13% |

No language group is clearly worse. Indian-language films are the most stable. Japanese tone is the least stable, and
world-cinema films most often end with empty themes after consensus.

**Taste DNA (consistency check, NOT ground truth), on consensus tags:**

| Concept | Films where Taste DNA has evidence | Consensus agrees | Consensus claims it where Taste DNA is silent |
|---|---|---|---|
| Dark | 17 | 71% | 30.5% of 383 |
| Slow burn | 1 | 1 of 1 | 16.0% of 399 |
| Fast | 12 | 58% | 17.5% of 388 |
| Humour | 112 | 76% | 10.1% of 288 |

Where Taste DNA's keyword rules say something, Gemini usually agrees. Taste DNA is silent on 72 to 99% of these films,
which is the coverage Gemini would add, if its tags prove accurate.

## Reading

- The same pattern holds at 400 films and across languages:
  - Tone and pacing repeat about 90% of the time.
  - Mood and themes repeat about 0.77 (Jaccard).
  - Consensus turns the unstable words into "unknown" while still leaving about 89 to 95% of films with usable tags.
- **Consensus is the abstention mechanism.** The prompt's "leave it empty if unsure" barely works, but asking twice and
  keeping only agreement does.
- **What this cannot show:** whether the tags are correct at scale. The only correctness evidence is still the 60-film
  stand-in review, which was not human and not blind. Nothing here may feed Taste DNA, the preference model or scoring
  without a real human check of a sample of these 400 and a separate approval.

## Files

- **Step 1:**
  - `tags.json` (run 3 added)
  - `calls.json`
  - `consensus-3runs.json`
- **Step 2:**
  - `scale/sample.json` (contains languages; this sample is not under blind review)
  - `scale/tags.json`
  - `scale/calls.json`
  - `scale/consensus-2runs.json`
- **Evaluation:** `followup-evaluation.json`.
