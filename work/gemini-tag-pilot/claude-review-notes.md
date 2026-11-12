# Gemini tag pilot: Claude review (NOT a human review)

Added after the pilot (PR #137) because Aryav asked Claude to fill the review sheet instead of doing it himself.
The blank, blind `review-sheet.csv` is unchanged, so a human check can still be done.

## Caveats
- The same kind of model wrote the tags and judged them, so results are probably too optimistic.
- Claude judged from its own film knowledge plus the plot text. "u" (unsure) was used for obscure titles and 2025 releases.
- This pass saw only the blind sheet (no language or group). A second pass on the laptop saw the languages, so it is not blind.
- Per-language scoring is NOT in this file. It needs the hidden mapping, which stays on the laptop.

## Result (60 films; r = right, w = wrong, u = unsure)

| Field | Right | Wrong | Unsure | Right of decided | Right of all 60 |
|---|---|---|---|---|---|
| Mood | 56 | 1 | 3 | 98% | 93% |
| Tone | 52 | 2 | 6 | 96% | 87% |
| Pacing | 48 | 0 | 12 | 100% | 80% |
| Themes | 54 | 3 | 3 | 95% | 90% |

## Mistakes found
- Mood: Fullmetal Alchemist (2017) was left empty.
- Tone: Marcel the Shell with Shoes On is "light" but bittersweet. No Other Choice is a dark comedy, not "serious".
- Themes: Bombay misses the riots. The Clowns misses circus and performance. Yamadonga "ambition" is off.

## Reading
Mood and themes are mostly accurate but unstable between runs (Jaccard 0.76 and 0.75), so they would need consensus tagging or a tighter vocabulary. Tone and pacing look usable. The 80% gate was meant for a human reviewer; treat this as a weaker signal.

Labels per film: `claude-review-labels.csv` (same folder).
