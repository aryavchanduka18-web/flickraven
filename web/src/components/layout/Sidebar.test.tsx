import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Sidebar from "./Sidebar";
import { TABS } from "./NavBar";
import { UIProvider } from "./ui";

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
});

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <UIProvider>
        <MemoryRouter><Sidebar moving={false} /></MemoryRouter>
      </UIProvider>
    </QueryClientProvider>,
  );
}

describe("Sidebar", () => {
  it("has the five main pages and no Missions tab", () => {
    setup();
    const nav = screen.getByRole("navigation");
    for (const t of TABS) expect(nav.querySelector(`a[href="${t.to}"]`)).not.toBeNull();
    expect(TABS.map((t) => t.label)).toEqual(["Home", "Discover", "Genres", "My List", "Activity"]);
    expect(screen.queryByText("Missions")).toBeNull();
  });

  it("hides and shows with the tall button, and remembers the choice", () => {
    setup();
    const panel = screen.getByTestId("sidebar");
    expect(panel.hasAttribute("inert")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Hide sidebar" }));
    expect(panel.hasAttribute("inert")).toBe(true);
    expect(localStorage.getItem("fr-sb")).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "Show sidebar", hidden: true }));
    expect(panel.hasAttribute("inert")).toBe(false);
    expect(localStorage.getItem("fr-sb")).toBe("1");
  });

  it("starts hidden when it was hidden last time", () => {
    localStorage.setItem("fr-sb", "0");
    setup();
    expect(screen.getByTestId("sidebar").hasAttribute("inert")).toBe(true);
  });
});
