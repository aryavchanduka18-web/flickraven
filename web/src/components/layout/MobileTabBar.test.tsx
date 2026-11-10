import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import MobileTabBar from "./MobileTabBar";
import { TABS } from "./NavBar";

describe("MobileTabBar", () => {
  it("has one column per tab, so adding a tab never wraps the bar", () => {
    render(<MemoryRouter><MobileTabBar /></MemoryRouter>);
    const grid = screen.getByTestId("tab-grid");
    expect(grid.style.gridTemplateColumns).toContain(`repeat(${TABS.length},`);
    expect(grid.querySelectorAll("a").length).toBe(TABS.length);
  });
});
