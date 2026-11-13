import { describe, expect, it } from "vitest";
import { animeRowSlot, themedRowLimit } from "./seriesRows";

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
