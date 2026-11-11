import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { UIProvider } from "../layout/ui";
import ActionButtons from "./ActionButtons";

const state = { rating: null, reaction: 0, in_list: false, watched: false };

function setup(source: string) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    calls.push(`${init?.method ?? "GET"} ${String(url)}`);
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <UIProvider>
        <MemoryRouter>
          <ActionButtons movieId={7} state={state} source={source} />
          <Toaster />
        </MemoryRouter>
      </UIProvider>
    </QueryClientProvider>,
  );
  return calls;
}

// The toast is drawn by the app shell; use the same hook so the test sees what a person sees.
import { AnimatePresence } from "framer-motion";
import { useUI } from "../layout/ui";
function Toaster() {
  const { toast, toastAction } = useUI();
  return (
    <AnimatePresence>
      {toast && <div role="status">{toast}{toastAction && <button onClick={toastAction.run}>{toastAction.label}</button>}</div>}
    </AnimatePresence>
  );
}

afterEach(() => vi.restoreAllMocks());

test("Not interested offers Undo, and Undo calls the undo endpoint", async () => {
  const calls = setup("rail:because");
  fireEvent.click(screen.getByRole("button", { name: "Not interested" }));
  await waitFor(() => expect(calls).toContain("PUT /api/feedback/not-interested/7"));
  fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls).toContain("DELETE /api/feedback/not-interested/7"));
});

test("no Not interested button on More Like This", () => {
  setup("more_like_this");
  expect(screen.queryByRole("button", { name: "Not interested" })).toBeNull();
});

test("marking watched sends the row it came from", async () => {
  const calls: string[] = [];
  const bodies: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    calls.push(`${init?.method ?? "GET"} ${String(url)}`);
    bodies.push(String(init?.body ?? ""));
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}><UIProvider><MemoryRouter>
      <ActionButtons movieId={7} state={state} source="rail:because" showWatched />
    </MemoryRouter></UIProvider></QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Mark watched" }));
  await waitFor(() => expect(calls).toContain("PUT /api/watched/7"));
  expect(bodies[calls.indexOf("PUT /api/watched/7")]).toContain("rail:because");
});
