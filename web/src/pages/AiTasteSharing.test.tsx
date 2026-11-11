import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UIProvider } from "../components/layout/ui";
import { AiTasteSharing } from "./Account";

const LINE = "enjoys Crime and Thriller; mostly in Korean; mostly TV series";
let puts: unknown[] = [];
beforeEach(() => {
  puts = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      puts.push(body);
      return new Response(JSON.stringify({ enabled: body.enabled, summary: LINE, min_liked: 3 }), { status: 200 });
    }
    return new Response(JSON.stringify({ enabled: false, summary: LINE, min_liked: 3 }), { status: 200 });
  });
});

describe("AI taste sharing", () => {
  it("is off by default, shows the exact line, and turns on with one tap", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><UIProvider><MemoryRouter><AiTasteSharing /></MemoryRouter></UIProvider></QueryClientProvider>);
    const box = await screen.findByRole("checkbox");
    expect((box as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText(LINE)).toBeTruthy();
    fireEvent.click(box);
    await waitFor(() => expect(puts).toEqual([{ enabled: true }]));
    await waitFor(() => expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true));
  });
});
