/** Where the "Not interested" button is offered: recommendation rows only (Home rows, series and anime rows, collections).
 *  Not More Like This (a list of titles similar to one title), search, My List or genre and Discover grids: those are
 *  not suggestions to this person. Keep this in step with the backend rule in docs/spec.md 14.2p. */
export const NOT_INTERESTED_SOURCES = /^(rail|collection):/;

export function canHideFrom(source?: string): boolean {
  return !!source && NOT_INTERESTED_SOURCES.test(source);
}
