import { canHideFrom } from "./notInterested";

test("Not interested is offered on recommendation rows only", () => {
  for (const s of ["rail:top_picks", "rail:series_because", "rail:anime", "collection:rom-com"]) expect(canHideFrom(s)).toBe(true);
  for (const s of ["more_like_this", "more_like_this_all", "search", "my_list", "movie_page", "quick_view", "genre:Drama", "hero", "", undefined])
    expect(canHideFrom(s)).toBe(false);
});
