import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PerfectPick from "./PerfectPick";

let requestBody: Record<string, unknown> | null;

beforeEach(() => {
  requestBody = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    requestBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ items: [], message: null }), { status: 200 });
  });
});

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><PerfectPick /></MemoryRouter></QueryClientProvider>);
}

describe("Perfect Pick", () => {
  it("sends all three latest answers when the final answer starts recommendations", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /Funny/ }));
    fireEvent.click(screen.getByRole("button", { name: /Under 90 minutes/ }));
    fireEvent.click(screen.getByRole("button", { name: /Familiar/ }));

    await waitFor(() => expect(requestBody).toEqual({
      mood: "Funny",
      time: "short",
      adventure: "familiar",
      other_languages: false,
      exclude: [],
    }));
  });
});
