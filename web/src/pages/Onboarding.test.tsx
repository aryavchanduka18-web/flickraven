import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Onboarding from "./Onboarding";

let savedBody: Record<string, unknown> | null;

vi.mock("../components/card/MovieCard", () => ({
  CardArtwork: ({ item }: { item: { movie: { title: string } } }) => <span>{item.movie.title}</span>,
}));

beforeEach(() => {
  savedBody = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/onboarding/candidates")) {
      const movies = Array.from({ length: 5 }, (_, index) => ({
        movie: { id: index + 1, title: `Title ${index + 1}`, year: 2020, language: "en" },
      }));
      return new Response(JSON.stringify({
        movies,
        series: [],
        languages: [{ code: "en", films: 1000 }, { code: "hi", films: 200 }],
        genres: [],
      }), { status: 200 });
    }
    if (url.endsWith("/onboarding")) {
      savedBody = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    return new Response("Not found", { status: 404 });
  });
});

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><Onboarding /></MemoryRouter></QueryClientProvider>);
}

describe("Onboarding language preferences", () => {
  it("saves only languages the person explicitly selects", async () => {
    setup();
    for (let id = 1; id <= 5; id++) {
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(`Title ${id}`) }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    const english = screen.getByRole("button", { name: /English/ });
    const hindi = screen.getByRole("button", { name: /Hindi/ });
    expect(english.getAttribute("aria-pressed")).toBe("false");
    expect(hindi.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(hindi);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Show my recommendations" }));

    await waitFor(() => expect(savedBody).toMatchObject({ languages: ["hi"] }));
  });
});
