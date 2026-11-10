import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Missions from "./Missions";
import { completedOn } from "../lib/missionCard";

const base = { description: "d", goal: 3, dismissed: false, ranked_by_taste: false, suggestions: [] };
const data = {
  counts: { recommended: 1, active: 1, completed: 1, explore: 0 },
  missions: [
    { ...base, key: "world", title: "International Explorer", why: "9 of your 10 films are from the US or India.", progress: 0, done: false, tab: "recommended", completed_at: null },
    { ...base, key: "classics", title: "Classic cinema", why: "", progress: 2, done: false, tab: "active", completed_at: null },
    { ...base, key: "decades", title: "Through the decades", why: "", progress: 3, done: true, tab: "completed", completed_at: "2026-03-14T10:00:00Z" },
  ],
};

afterEach(() => vi.restoreAllMocks());

describe("Missions", () => {
  it("shows each tab's missions, the reason, and the completion date", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(data), { status: 200 }));
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Missions /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText("International Explorer")).toBeTruthy();
    expect(screen.getByText(/9 of your 10 films are from the US or India/)).toBeTruthy();
    expect(screen.queryByText("Classic cinema")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: /Active/ }));
    expect(await screen.findByText("Classic cinema")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Completed/ }));
    await waitFor(() => expect(screen.getByText(/Completed on/)).toBeTruthy());
    expect(screen.getByRole("button", { name: /Download completion card/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Not for me/ })).toBeNull();      // a finished mission cannot be hidden
  });

  it("formats the completion date", () => {
    expect(completedOn("2026-03-14T10:00:00Z")).toContain("March 2026");
    expect(completedOn(null)).toBeNull();
  });
});
