import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PerfectPick from "./PerfectPick";

let requests: Record<string, unknown>[];

beforeEach(() => {
  requests = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    requests.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ items: [], message: null }), { status: 200 });
  });
});

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
      time: "h20", status: "completed", adventure: "adventurous", other_languages: false, exclude: [],
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
});
