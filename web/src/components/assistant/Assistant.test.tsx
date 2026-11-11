import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Assistant from "./Assistant";

let chatCalls = 0;
let failChat = true;
beforeEach(() => {
  chatCalls = 0;
  failChat = true;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const u = String(input);
    if (u.includes("/assistant/status")) return new Response(JSON.stringify({ enabled: true, remaining: 20, cap: 20 }), { status: 200 });
    chatCalls += 1;
    if (failChat) return new Response(JSON.stringify({ detail: "The assistant is busy right now. Try again in a moment." }), { status: 502 });
    return new Response(JSON.stringify({ reply: "Try [[Heat (1995)]].", items: [], remaining: 19 }), { status: 200 });
  });
});

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><Assistant /></MemoryRouter></QueryClientProvider>);
}

describe("Assistant", () => {
  it("typing sends nothing; Send sends once; a failure shows Try again and Retry then works", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Ask FlickRaven" }));
    const box = screen.getByLabelText("Message");
    fireEvent.change(box, { target: { value: "x".repeat(300) } });
    expect(chatCalls).toBe(0);
    fireEvent.change(box, { target: { value: "something like Heat" } });
    fireEvent.submit(box.closest("form")!);
    fireEvent.submit(box.closest("form")!);
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.getByRole("alert").textContent).toContain("busy right now");
    expect(chatCalls).toBe(1);
    failChat = false;
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("Heat (1995)")).toBeTruthy());
    expect(chatCalls).toBe(2);
    // the panel can be closed and the rest of the page is untouched
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

const card = (id: number, title: string, inList = false) => ({
  movie: { id, title, year: 2000 + id, poster: null, backdrop: null, logo: null, genres: [], language: "en", runtime: 100,
    community_rating: null, dominant_color: null, overview_short: null },
  score: null, match_pct: null, reasons: [], user_state: { rating: null, reaction: 0, in_list: inList, watched: false },
});

describe("Assistant: add to My List", () => {
  let puts: string[];
  let chatBodies: { messages: { role: string; text: string }[] }[];
  let failPut: boolean;
  beforeEach(() => {
    puts = [];
    chatBodies = [];
    failPut = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const u = String(input);
      if (u.includes("/assistant/status")) return new Response(JSON.stringify({ enabled: true, remaining: 20, cap: 20 }), { status: 200 });
      if (u.includes("/list/")) {
        puts.push(`${init?.method} ${u} ${init?.body}`);
        await new Promise((r) => setTimeout(r, 5));
        return failPut ? new Response(JSON.stringify({ detail: "nope" }), { status: 500 }) : new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      chatBodies.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ reply: "Try [[Heat (2001)]] or [[Ronin (2002)]]. Want something darker?",
        items: [{ ...card(1, "Heat"), reasons: [{ code: "taste_dna", text: "Fits your Taste DNA: dark, atmospheric tone.", source: "taste_dna", share: 0, anchor_movie_id: null }] },
          card(2, "Ronin"), card(3, "Saved Film", true)], remaining: 19 }), { status: 200 });
    });
  });

  async function askOnce() {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Ask FlickRaven" }));
    const box = screen.getByLabelText("Message");
    fireEvent.change(box, { target: { value: "a heist film" } });
    fireEvent.submit(box.closest("form")!);
    await screen.findByRole("button", { name: "Add Heat to My List" });
    return box;
  }

  it("a card shows the Taste DNA line our server attached, and only that", async () => {
    await askOnce();
    expect(screen.getByText("Fits your Taste DNA: dark, atmospheric tone.")).toBeTruthy();
    expect(screen.getAllByText(/Fits your Taste DNA/)).toHaveLength(1);
  });

  it("each card offers + My List; a double click adds once and the card then says In your list", async () => {
    await askOnce();
    expect(screen.getByText(/Want me to add one to your list/)).toBeTruthy();
    expect(screen.getByText("✓ In your list")).toBeTruthy();                       // already saved: no button
    const add = screen.getByRole("button", { name: "Add Heat to My List" });
    fireEvent.click(add);
    fireEvent.click(add);
    await waitFor(() => expect(screen.getAllByText("✓ In your list")).toHaveLength(2));
    expect(puts).toEqual(['PUT /api/list/1 {"source":"assistant"}']);
  });

  it("typing 'add the second one' adds that card without asking Gemini, and the exchange is never sent to the chat", async () => {
    const box = await askOnce();
    fireEvent.change(box, { target: { value: "add the second one" } });
    fireEvent.submit(box.closest("form")!);
    await screen.findByText("Added Ronin to your list.");
    expect(puts).toEqual(['PUT /api/list/2 {"source":"assistant"}']);
    expect(chatBodies).toHaveLength(1);
    // a bare "yes" here answers the reply's own question ("Want something darker?"), so it goes to the assistant,
    // and the local add exchange is left out of what is sent
    fireEvent.change(box, { target: { value: "yes" } });
    fireEvent.submit(box.closest("form")!);
    await waitFor(() => expect(chatBodies).toHaveLength(2));
    expect(chatBodies[1].messages.map((m) => m.text)).toEqual(["a heist film", expect.stringContaining("Heat"), "yes"]);
    expect(puts).toHaveLength(1);
  });

  it("a failed add says so and can be retried", async () => {
    await askOnce();
    failPut = true;
    fireEvent.click(screen.getByRole("button", { name: "Add Heat to My List" }));
    await screen.findByText("Retry add");
    failPut = false;
    fireEvent.click(screen.getByRole("button", { name: "Add Heat to My List" }));
    await waitFor(() => expect(screen.getAllByText("✓ In your list")).toHaveLength(2));
    expect(puts).toHaveLength(2);
  });
});
