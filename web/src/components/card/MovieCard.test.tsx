import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { RecItem } from "../../api/types";
import { UIProvider } from "../layout/ui";
import MovieCard from "./MovieCard";

const item: RecItem = {
  movie: { id: 7, title: "Test Film", year: 2017, poster: null, backdrop: null, logo: null, genres: ["Action"],
    language: "en", runtime: 120, community_rating: 7.5, dominant_color: null, overview_short: "A short plot." },
  score: 0.8, match_pct: 85, reasons: [{ code: "x", text: "Because of a test", share: 1 }],
  user_state: { rating: null, reaction: 0, in_list: false, watched: false },
};

beforeEach(() => {
  vi.useFakeTimers();
  // A device with a real mouse, so the hover card is used.
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }));
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ directors: [], cast: [] }), { status: 200 }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <UIProvider>
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<div data-testid="rail" style={{ overflowX: "auto" }}><MovieCard item={item} source="test" position={0} /></div>} />
            <Route path="/movie/:id" element={<p>title page</p>} />
          </Routes>
        </MemoryRouter>
      </UIProvider>
    </QueryClientProvider>,
  );
  const card = screen.getByRole("button", { name: "Test Film (2017)" }).parentElement!;
  fireEvent.mouseEnter(card);
  // Opens after the hover-intent delay, once the details are loaded (or after the longest wait).
  await act(async () => {
    await vi.advanceTimersByTimeAsync(700);
  });
  return { view, card };
}

test("the hover details render outside the rail, so the rail cannot clip them", async () => {
  await setup();
  const details = screen.getByTestId("hover-details");
  expect(screen.getByTestId("rail")).not.toContainElement(details);
  expect(document.body).toContainElement(details);
});

test("the mouse wheel over the card or its details scrolls only the details", async () => {
  const { card } = await setup();
  const details = screen.getByTestId("hover-details");
  const body = screen.getByLabelText("Test Film details");
  for (const target of [details, card]) {
    const wheel = new WheelEvent("wheel", { deltaY: 40, bubbles: true, cancelable: true });
    target.dispatchEvent(wheel);
    expect(wheel.defaultPrevented).toBe(true);        // the page and the rail do not move
  }
  expect(body.scrollTop).toBe(80);
});

test("the details open once, at their final size: the film details are loaded before the panel shows", async () => {
  await setup();
  expect(globalThis.fetch).toHaveBeenCalledWith("/api/movies/7", expect.anything());
  expect(screen.getByTestId("hover-details")).toBeInTheDocument();
  expect(screen.queryByText("Loading", { exact: false })).not.toBeInTheDocument();
});


test("a click anywhere on the hover details opens the title's page (they cover the cards below in a grid)", async () => {
  await setup();
  fireEvent.click(screen.getByText("A short plot."));
  expect(screen.getByText("title page")).toBeInTheDocument();
});

test("the hover details show the title as a link to its page, and their own buttons do not navigate", async () => {
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "Quick view Test Film" }));
  expect(screen.queryByText("title page")).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Test Film" }));
  expect(screen.getByText("title page")).toBeInTheDocument();
});
