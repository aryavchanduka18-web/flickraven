import { act, render } from "@testing-library/react";
import { useRef } from "react";
import { CARD_VISIBLE, flush, newPage, record, useDwell } from "./impressions";

type Entry = { isIntersecting: boolean; intersectionRatio: number };
let observers: { cb: (e: Entry[]) => void }[] = [];
const sent: { page_id: string; items: Record<string, unknown>[] }[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  observers = [];
  sent.length = 0;
  class FakeIO {
    cb: (e: Entry[]) => void;
    constructor(cb: (e: Entry[]) => void) {
      this.cb = cb;
      observers.push(this);
    }
    observe() {}
    disconnect() {}
  }
  vi.stubGlobal("IntersectionObserver", FakeIO);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_u, init) => {
    sent.push(JSON.parse(String(init?.body)));
    return new Response("{}", { status: 200 });
  });
  newPage();
  sent.length = 0;
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Card({ id }: { id: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useDwell(ref, () => record({ surface: "rail:because", kind: "card", movie_id: id }), { threshold: CARD_VISIBLE });
  return <div ref={ref} />;
}

const show = (ratio: number) => act(() => observers[0].cb([{ isIntersecting: ratio > 0, intersectionRatio: ratio }]));
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const stored = () => sent.flatMap((s) => s.items);

test("a card seen for a full second counts once", async () => {
  render(<Card id={1} />);
  show(0.9);
  await wait(1100);
  show(0);
  show(0.9);
  await wait(1100);
  flush();
  expect(stored()).toHaveLength(1);
  expect(stored()[0]).toMatchObject({ surface: "rail:because", kind: "card", movie_id: 1 });
});

test("less than a second does not count", async () => {
  render(<Card id={2} />);
  show(0.9);
  await wait(600);
  show(0);                 // scrolled away
  await wait(2000);
  flush();
  expect(stored()).toHaveLength(0);
});

test("a card only partly visible does not count", async () => {
  render(<Card id={3} />);
  show(0.4);               // below 60%
  await wait(3000);
  flush();
  expect(stored()).toHaveLength(0);
});

test("a hidden tab does not count", async () => {
  Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
  render(<Card id={4} />);
  show(0.9);
  await wait(3000);
  flush();
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  expect(stored()).toHaveLength(0);
});

test("lists that are not recommendations are never recorded", () => {
  record({ surface: "search", kind: "card", movie_id: 1 });
  record({ surface: "my_list", kind: "row" });
  flush();
  expect(stored()).toHaveLength(0);
});

test("a new page load counts the same card again, under a new page id", () => {
  record({ surface: "rail:top_picks", kind: "row" });
  record({ surface: "rail:top_picks", kind: "row" });
  flush();
  newPage();
  record({ surface: "rail:top_picks", kind: "row" });
  flush();
  expect(sent).toHaveLength(2);
  expect(sent[0].items).toHaveLength(1);
  expect(sent[0].page_id).not.toBe(sent[1].page_id);
});
