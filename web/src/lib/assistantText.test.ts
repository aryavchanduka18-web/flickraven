import { describe, expect, it } from "vitest";
import { parseReply, titleKey } from "./assistantText";

describe("parseReply", () => {
  it("separates spoilers and title marks, and leaves markup as plain text", () => {
    const p = parseReply("Try [[Heat (1995)]]. ||He dies.|| <img src=x onerror=alert(1)>");
    expect(p.map((x) => x.kind)).toEqual(["text", "title", "text", "spoiler", "text"]);
    expect(p[1].text).toBe("Heat (1995)");
    expect(p[3].text).toBe("He dies.");
    expect(p[4].text).toContain("<img");           // still just text; React will not turn it into an element
  });
  it("matches a mark to a title without its year", () => {
    expect(titleKey("Heat (1995)")).toBe("heat");
    expect(titleKey("Se7en")).toBe("se7en");
  });
});
