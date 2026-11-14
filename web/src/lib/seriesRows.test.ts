import { describe, expect, it } from "vitest";
import { animeFilmsUnderAnimeRow, animeRowSlot, seriesRowSlot, themedRowLimit } from "./seriesRows";

describe("themedRowLimit", () => {
  it("grows with the person's series activity", () => {
    expect(themedRowLimit(0)).toBe(3);
    expect(themedRowLimit(3)).toBe(6);
    expect(themedRowLimit(8)).toBe(Infinity);
  });
});

describe("animeRowSlot", () => {
  it("moves the anime row up for people who like anime", () => {
    expect(animeRowSlot(0)).toBe(1);
    expect(animeRowSlot(2)).toBe(1);
    expect(animeRowSlot(3)).toBe(0);
    expect(animeRowSlot(50)).toBe(0);
  });
});

describe("seriesRowSlot", () => {
  it("moves the series row up for people who like series", () => {
    expect(seriesRowSlot(2)).toBe(1);
    expect(seriesRowSlot(3)).toBe(0);
  });
});

describe("animeFilmsUnderAnimeRow", () => {
  it("lifts the Anime Films shelf for anime fans only", () => {
    expect(animeFilmsUnderAnimeRow(2)).toBe(false);
    expect(animeFilmsUnderAnimeRow(3)).toBe(true);
  });
});
