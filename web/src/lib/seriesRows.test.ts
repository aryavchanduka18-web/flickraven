import { describe, expect, it } from "vitest";
import { themedRowLimit } from "./seriesRows";

describe("themedRowLimit", () => {
  it("grows with the person's series activity", () => {
    expect(themedRowLimit(0)).toBe(3);
    expect(themedRowLimit(3)).toBe(6);
    expect(themedRowLimit(8)).toBe(Infinity);
  });
});
