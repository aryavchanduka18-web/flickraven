import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PerfectPick from "./PerfectPick";

let requests: Record<string, unknown>[];
let urls: string[];
let reply: unknown;

const card = (id: number, title: string, misses: string[] = []) => ({
  movie: { id, title, year: 2021, poster: null, title_type: "series", imdb_rating: null, imdb_votes: null },
  score: 0.5, match_pct: null, reasons: [{ code: "pp_time", source: "perfect_pick", text: "About 16 hours in total", share: 0, anchor_movie_id: null }],
  user_state: {}, misses,
});

beforeEach(() => {
  requests = [];
  urls = [];
  reply = { items: [], message: null };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    urls.push(String(input));
    requests.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify(reply), { status: 200 });
  });
});

function answerAll() {
  fireEvent.click(screen.getByRole("button", { name: /A TV series/ }));
  fireEvent.click(screen.getByRole("button", { name: /Romantic/ }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: "Korean" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: /10 to 20 hours/ }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: /^Familiar/ }));
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><PerfectPick /></MemoryRouter></QueryClientProvider>);
}

describe("Perfect Pick", () => {
  it("asks six questions and sends every latest answer in the first request", async () => {
    setup();
    expect(screen.getByText(/Question 1 of 6/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /A TV series/ }));
    fireEvent.click(screen.getByRole("button", { name: /Mysterious/ }));
    fireEvent.click(screen.getByRole("button", { name: "Thriller" }));
    fireEvent.click(screen.getByRole("button", { name: "Crime" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Korean" }));
    fireEvent.click(screen.getByRole("button", { name: "Hindi" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/Question 5 of 6/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /10 to 20 hours/ }));
    fireEvent.click(screen.getByRole("button", { name: "Finished series" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: /Unexpected, but my taste/ }));

    await waitFor(() => expect(requests.length).toBe(1));
    expect(requests[0]).toEqual({
      kind: "series", mood: "Mysterious", genres: ["Thriller", "Crime"], languages: ["ko", "hi"],
      time: "h20", status: "completed", adventure: "adventurous", other_languages: false, exclude: [], more: false,
    });
  });

  it("shows time choices for the chosen kind and lets you go back", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /A movie/ }));
    fireEvent.click(screen.getByRole("button", { name: /No mood in mind/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("button", { name: /Under 90 minutes/ })).toBeTruthy();
    expect(screen.queryByText(/finished or still airing/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText(/Question 4 of 6/)).toBeTruthy();
  });

  it("keeps exact matches apart from labelled broader alternatives", async () => {
    reply = { items: [card(1, "Exact Show")], alternatives: [card(2, "Near Show", ["mood"]), card(3, "Far Show", ["mood", "genres"])],
      message: "Only 1 title meets every answer.", relaxed: ["mood", "genres"], offer: null };
    setup();
    answerAll();
    expect(await screen.findByText("One title fits every answer")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Broader alternatives" })).toBeTruthy();
    expect(screen.getByText("Misses your mood")).toBeTruthy();
    expect(screen.getByText("Misses your mood and your genres")).toBeTruthy();
    expect(screen.getByText("Exact Show").closest("article")?.textContent).not.toMatch(/Misses/);
  });

  it("asks before widening languages and only widens on a click", async () => {
    reply = { items: [], alternatives: [], message: "Nothing in Korean fits your type and length.", offer: "other_languages" };
    setup();
    answerAll();
    const btn = await screen.findByRole("button", { name: "Include other languages" });
    expect(requests[0].other_languages).toBe(false);
    fireEvent.click(btn);
    await waitFor(() => expect(requests.length).toBe(2));
    expect(requests[1].other_languages).toBe(true);
  });

  it("Show more adds the next three below the first ones, then says when there is nothing left", async () => {
    reply = { items: [card(1, "A"), card(2, "B"), card(3, "C")], alternatives: [], message: null, remaining: { exact: 2, alternatives: 0 } };
    setup();
    answerAll();
    expect(await screen.findByText("2 more titles meet every answer")).toBeTruthy();
    reply = { items: [card(4, "D"), card(5, "E")], alternatives: [], message: "That is the last of the titles that meet every answer.",
      remaining: { exact: 0, alternatives: 0 } };
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(requests.length).toBe(2));
    expect(requests[1].more).toBe(true);
    expect(requests[1].exclude).toEqual([1, 2, 3]);
    expect(await screen.findByText("Your 5 picks")).toBeTruthy();
    for (const t of ["A", "B", "C", "D", "E"]) expect(screen.getByText(t)).toBeTruthy();
    expect(screen.getByText(/That is everything for these answers/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("offers Anime as a genre", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /A TV series/ }));
    fireEvent.click(screen.getByRole("button", { name: /Intense/ }));
    expect(screen.getByRole("button", { name: "Anime" })).toBeTruthy();
  });

  it("stores a rejection with the answers that produced it and the chosen reason", async () => {
    reply = { items: [card(1, "A"), card(2, "B"), card(3, "C")], alternatives: [], message: null };
    setup();
    answerAll();
    await screen.findByText("A");
    const article = screen.getByText("A").closest("article") as HTMLElement;
    fireEvent.click(article.querySelectorAll("button")[0]); // Not this one
    expect(article.textContent).toMatch(/Why\? Optional/);
    fireEvent.click(screen.getAllByRole("button", { name: "Wrong mood" })[0]);
    await waitFor(() => expect(urls.some((u) => u.endsWith("/feedback/perfect-pick-reject"))).toBe(true));
    const i = urls.findIndex((u) => u.endsWith("/feedback/perfect-pick-reject"));
    expect(requests[i]).toEqual({
      kind: "perfect_pick_reject", movie_ids: [1], reasons: ["mood"], alt: false,
      request: { kind: "series", mood: "Romantic", genres: [], languages: ["ko"], time: "h20", status: "any", adventure: "familiar", other_languages: false },
    });
    expect(article.textContent).toMatch(/Noted/);
    // a rejected title cannot be rejected twice, and nothing else on the page was rejected
    expect(article.textContent).not.toMatch(/Not this one/);
    expect(urls.filter((u) => u.endsWith("/feedback/perfect-pick-reject")).length).toBe(1);
  });

  it("Skip stores the rejection without a reason, and Not these is stored as context only", async () => {
    reply = { items: [card(1, "A"), card(2, "B"), card(3, "C")], alternatives: [], message: null };
    setup();
    answerAll();
    await screen.findByText("A");
    const article = screen.getByText("A").closest("article") as HTMLElement;
    fireEvent.click(article.querySelectorAll("button")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Not these" })[0]);
    await waitFor(() => expect(urls.filter((u) => u.endsWith("/recs/perfect-pick")).length).toBe(2));
    const sent = requests.filter((_, k) => urls[k].endsWith("/feedback/perfect-pick-reject"));
    expect(sent.map((r) => [r.kind, r.reasons, r.movie_ids])).toEqual([
      ["perfect_pick_reject", [], [1]],
      ["perfect_pick_reroll", [], [2, 3]], // the one already turned down is not repeated
    ]);
  });
});
