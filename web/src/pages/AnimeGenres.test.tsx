import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UIProvider } from "../components/layout/ui";
import { Genre } from "./Genres";

const urls: string[] = [];
beforeEach(() => {
  urls.length = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const u = String(input);
    urls.push(u);
    if (u.includes("/genres/anime/tags")) {
      return new Response(JSON.stringify({ tags: [
        { key: "action", label: "Action", group: "genre", titles: 600 }, { key: "fantasy", label: "Fantasy", group: "genre", titles: 700 },
        { key: "isekai", label: "Isekai", group: "theme", titles: 150 }, { key: "ecchi", label: "Ecchi", group: "mature", titles: 230 },
        { key: "harem", label: "Harem", group: "theme", titles: 160 }] }), { status: 200 });
    }
    if (u.endsWith("/genres")) return new Response(JSON.stringify({ genres: [{ slug: "anime", name: "Anime" }] }), { status: 200 });
    return new Response(JSON.stringify({ items: [], total: 0, page: 1 }), { status: 200 });
  });
});

describe("Anime genre filters", () => {
  it("sends several genres together, themes and avoided tags, next to mood and type", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><UIProvider><MemoryRouter initialEntries={["/genres/anime"]}>
      <Routes><Route path="/genres/:slug" element={<Genre />} /></Routes></MemoryRouter></UIProvider></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Action" }));
    fireEvent.click(screen.getByRole("button", { name: "Fantasy" }));
    fireEvent.click(screen.getByRole("button", { name: /^More filters/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Isekai" }));
    const avoid = screen.getByRole("group", { name: "Avoid" });
    fireEvent.click(Array.from(avoid.querySelectorAll("button")).find((b) => b.textContent === "Ecchi")!);
    fireEvent.click(screen.getByRole("tab", { name: "Romantic" }));
    await waitFor(() => {
      const last = [...urls].reverse().find((u) => u.includes("/genres/anime/movies"))!;
      const q = new URL(last, "http://x").searchParams;
      expect(q.get("anime_tags")).toBe("action,fantasy,isekai");
      expect(q.get("anime_avoid")).toBe("ecchi");
      expect(q.get("vibe")).toBe("romance");
    });
  });
  it("shows no anime filters on other genre pages", async () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><UIProvider><MemoryRouter initialEntries={["/genres/drama"]}>
      <Routes><Route path="/genres/:slug" element={<Genre />} /></Routes></MemoryRouter></UIProvider></QueryClientProvider>);
    await waitFor(() => expect(urls.some((u) => u.includes("/genres/drama/movies"))).toBe(true));
    expect(screen.queryByRole("group", { name: "Genres" })).toBeNull();
    expect(urls.some((u) => u.includes("/genres/anime/tags"))).toBe(false);
  });
});
