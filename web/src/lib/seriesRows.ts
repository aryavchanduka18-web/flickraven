/** How many themed TV rows Home shows. A person who mostly watches films should not see eight TV sections at once:
 *  3 at first, 6 once they have shown interest in 3 series or anime (liked, rated 7+, saved or picked), all after 8. */
export function themedRowLimit(engagedSeries: number): number {
  return engagedSeries < 3 ? 3 : engagedSeries < 8 ? 6 : Number.POSITIVE_INFINITY;
}

/** Where Home puts the "Anime for you" row: right after Top Picks (slot 0) for someone who has shown interest in 3 or
 *  more anime, after the second film row (slot 1) for everyone else. */
export function animeRowSlot(engagedAnime: number): 0 | 1 {
  return engagedAnime >= 3 ? 0 : 1;
}

/** Where Home puts the "Series for you" row: right after Top Picks (slot 0) for someone who has shown interest in 3 or
 *  more series, after the second film row (slot 1) for everyone else. */
export function seriesRowSlot(engagedSeries: number): 0 | 1 {
  return engagedSeries >= 3 ? 0 : 1;
}

/** The "Anime Films" shelf sits right under the "Anime for you" row for an anime fan (3 or more anime liked), and stays
 *  with the other film collections at the bottom for everyone else. */
export function animeFilmsUnderAnimeRow(engagedAnime: number): boolean {
  return engagedAnime >= 3;
}
