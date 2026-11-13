import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Radar from "./Radar";

describe("Radar", () => {
  it("describes every trait with its value for screen readers", () => {
    const pts = [{ key: "a", label: "Plot complexity", you: 80, catalog: 20 }, { key: "b", label: "Humour", you: 10, catalog: 30 }, { key: "c", label: "Dark atmosphere", you: 50, catalog: 10 }];
    render(<Radar points={pts} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("Plot complexity 80 out of 100");
    expect(screen.getAllByText("Humour").length).toBe(1);
  });

  it("splits long side labels onto two lines so they are not cut off", () => {
    const pts = ["Plot complexity", "Psychological tension", "Dark atmosphere", "Character focus"].map((l, i) => ({ key: String(i), label: l, you: 50, catalog: 50 }));
    const { container } = render(<Radar points={pts} />);
    const texts = Array.from(container.querySelectorAll("text"));
    expect(texts[0].querySelectorAll("tspan").length).toBe(0);            // top label stays on one line
    expect(Array.from(texts[1].querySelectorAll("tspan")).map((t) => t.textContent)).toEqual(["Psychological", "tension"]);
  });
});
