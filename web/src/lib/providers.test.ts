import { describe, expect, it } from "vitest";
import { providerSearchUrl } from "./providers";

describe("providerSearchUrl", () => {
  it("opens the service's own search for known services", () => {
    expect(providerSearchUrl("Netflix", "Set It Up")).toBe("https://www.netflix.com/search?q=Set%20It%20Up");
    expect(providerSearchUrl("Amazon Prime Video", "Tamasha")).toContain("primevideo.com/search");
    expect(providerSearchUrl("Disney Plus Hotstar", "Dangal")).toContain("hotstar.com");
  });
  it("falls back to a web search for the title and service, never a made-up address", () => {
    const u = providerSearchUrl("Some Small Service", "A & B");
    expect(u.startsWith("https://www.google.com/search?q=")).toBe(true);
    expect(decodeURIComponent(u)).toContain("A & B watch on Some Small Service");
  });
});
