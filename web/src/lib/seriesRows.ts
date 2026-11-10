/** How many themed TV rows Home shows. A person who mostly watches films should not see eight TV sections at once:
 *  3 at first, 6 once they have shown interest in 3 series (liked, rated 7+, saved or picked), all after 8. */
export function themedRowLimit(engagedSeries: number): number {
  return engagedSeries < 3 ? 3 : engagedSeries < 8 ? 6 : Number.POSITIVE_INFINITY;
}
