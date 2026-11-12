import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UIProvider } from "../components/layout/ui";
import Discover from "./Discover";

const urls: string[] = [];
beforeEach(() => {
  urls.length = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const u = String(input);
    urls.push(u);
    if (u.includes("/discover/options")) {
      return new Response(JSON.stringify({ countries: [{ code: "KR", titles: 5 }], providers: [{ id: 8, name: "Netflix", logo: null, titles: 90 }] }), { status: 200 });
    }
    if (u.includes("/genres")) return new Response(JSON.stringify({ genres: [{ slug: "anime", name: "Anime" }, { slug: "drama", name: "Drama" }] }), { status: 200 });
    return new Response(JSON.stringify({ items: [], total: 0, page: 1 }), { status: 200 });
  });
});

function setup(url = "/discover") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}><UIProvider><MemoryRouter initialEntries={[url]}><Discover /></MemoryRouter></UIProvider></QueryClientProvider>,
  );
}
const lastMovies = () => [...urls].reverse().find((u) => u.includes("/movies?")) ?? "";

describe("Discover filters", () => {
  it("sends country, release period, IMDb score and streaming service to the API and shows how many are on", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /^Filters/ }));
    await screen.findByRole("option", { name: "Netflix" });
    fireEvent.change(screen.getByLabelText("Country"), { target: { value: "KR" } });
    fireEvent.change(screen.getByLabelText("Released from"), { target: { value: "2015" } });
    fireEvent.change(screen.getByLabelText("Minimum IMDb score"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Streaming service"), { target: { value: "8" } });
    await waitFor(() => expect(lastMovies()).toContain("provider=8"));
    const q = new URL(lastMovies(), "http://x").searchParams;
    expect(q.get("country")).toBe("KR");
    expect(q.get("year_min")).toBe("2015");
    expect(q.get("min_imdb")).toBe("7");
    expect(screen.getByRole("button", { name: /^Filters · 4/ })).toBeTruthy();
  });

  it("has no Match % filter or Match sort while Match % is hidden (until it is recalibrated)", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /^Filters/ }));
    expect(screen.queryByLabelText("Minimum match")).toBeNull();
    expect(screen.queryByRole("option", { name: "Highest match" })).toBeNull();
    await waitFor(() => expect(lastMovies()).not.toContain("min_match"));
  });

  it("Movies and Shows pages are locked to one kind", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><UIProvider><MemoryRouter><Discover fixed="show" /></MemoryRouter></UIProvider></QueryClientProvider>);
    await waitFor(() => expect(lastMovies()).toContain("type=show"));
    expect(screen.queryByRole("tablist", { name: "Type" })).toBeNull();
  });

  it("Anime is a genre pill", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Anime" }));
    await waitFor(() => expect(lastMovies()).toContain("genre=anime"));
  });

  it("?type=show opens Discover on Shows", async () => {
    setup("/discover?type=show");
    expect(screen.getByRole("tab", { name: "Shows" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(lastMovies()).toContain("type=show"));
  });

});
