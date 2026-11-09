// TMDB image URLs at the size they are displayed (spec section 9). Never "original".
const BASE = "https://image.tmdb.org/t/p";

export type ImageSize = "w92" | "w300" | "w342" | "w500" | "w780" | "w1280";

export function tmdbImage(path: string | null | undefined, size: ImageSize): string | undefined {
  return path ? `${BASE}/${size}${path}` : undefined;
}

export function backdropSrcSet(path: string | null | undefined): string | undefined {
  return path ? `${tmdbImage(path, "w780")} 780w, ${tmdbImage(path, "w1280")} 1280w` : undefined;
}