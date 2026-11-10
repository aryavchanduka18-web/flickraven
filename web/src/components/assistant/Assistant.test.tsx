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
