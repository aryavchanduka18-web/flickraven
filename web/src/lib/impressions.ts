/** Impressions: which recommendation rows and cards were genuinely visible.
 *
 *  A row counts when at least half of it is on screen, a card when at least 60% of it is, for one second without a
 *  break while the tab is in front. Each counts once per page load. This records what was SEEN, never what was
 *  rejected: a missing action means nothing, and no learning step reads it as a "no". No pointer, scroll-speed or
 *  screen tracking. Sent in small batches; failures are dropped. See docs/spec.md 14.2q. */
import { useEffect, useRef, type RefObject } from "react";

export const DWELL_MS = 1000;
export const ROW_VISIBLE = 0.5;
export const CARD_VISIBLE = 0.6;
const FLUSH_MS = 5000;
const MAX_QUEUE = 200;
/** Sources that are recommendations to this person; other lists (search, My List, genre grids) are not tracked. */
const TRACKED = /^(rail|collection|hero)(:|$)/;

export type Impression = { surface: string; kind: "row" | "card"; movie_id?: number; position?: number; visible_ms?: number };

const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });

let pageId = newId();
let queue: Impression[] = [];
let seen = new Set<string>();
let timer: number | undefined;

export function isTracked(surface: string): boolean {
  return TRACKED.test(surface);
}

/** A new page load (route change): everything may count again, under a new id. */
export function newPage(): void {
  flush();
  pageId = newId();
  seen = new Set();
}

export function record(i: Impression): void {
  if (!isTracked(i.surface)) return;
  const key = `${i.kind}|${i.surface}|${i.movie_id ?? ""}`;
  if (seen.has(key) || queue.length >= MAX_QUEUE) return;
  seen.add(key);
  queue.push(i);
  if (timer === undefined) timer = window.setTimeout(flush, FLUSH_MS);
}

export function flush(): void {
  window.clearTimeout(timer);
  timer = undefined;
  if (!queue.length) return;
  const items = queue.splice(0, 100);
  try {
    // keepalive lets the request finish while the page closes. A failure just loses a few impressions.
    void fetch("/api/impressions", {
      method: "POST", credentials: "include", keepalive: true,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ page_id: pageId, items }),
    }).catch(() => undefined);
  } catch {
    /* ignore */
  }
  if (queue.length) timer = window.setTimeout(flush, FLUSH_MS);
}

let listening = false;
export function startImpressionFlush(): void {
  if (listening || typeof document === "undefined") return;
  listening = true;
  document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && flush());
  window.addEventListener("pagehide", flush);
}

/** Calls `onSeen` once the element has been at least `threshold` visible for `ms` without a break, with the tab in
 *  front. Starts again when `key` changes (a carousel slide). Does nothing where IntersectionObserver is missing. */
export function useDwell(ref: RefObject<Element | null>, onSeen: () => void,
  opts: { threshold: number; ms?: number; key?: unknown }): void {
  const cb = useRef(onSeen);
  cb.current = onSeen;
  const { threshold, ms = DWELL_MS, key } = opts;
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    let on = false;
    let done = false;
    let t: number | undefined;
    const stop = () => {
      window.clearTimeout(t);
      t = undefined;
    };
    const start = () => {
      if (done || t !== undefined || !on || document.visibilityState !== "visible") return;
      t = window.setTimeout(() => {
        done = true;
        t = undefined;
        cb.current();
      }, ms);
    };
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) on = e.isIntersecting && e.intersectionRatio >= threshold;
      if (on) start();
      else stop();
    }, { threshold: [0, threshold] });
    io.observe(el);
    const vis = () => (document.visibilityState === "visible" ? start() : stop());
    document.addEventListener("visibilitychange", vis);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", vis);
      stop();
    };
  }, [ref, threshold, ms, key]);
}
