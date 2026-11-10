import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import { CardArtwork } from "../components/card/MovieCard";
import { Link } from "react-router-dom";

type Plan = { hours: number; days: number; text: string };
type Res = { items: (RecItem & { plan: Plan })[]; total: number };

const BUDGET: [string, string][] = [["", "Any amount"], ["3", "Up to 3 hours"], ["5", "Up to 5 hours"], ["10", "Up to 10 hours"], ["20", "Up to 20 hours"], ["long", "20+ hours"]];
const STATUS: [string, string][] = [["", "Finished or airing"], ["ended", "Finished only"], ["airing", "Still airing"]];
const LENGTH: [string, string][] = [["", "Any episode length"], ["short", "Under 30 min"], ["medium", "30-45 min"], ["long", "45-60 min"], ["xl", "Over 60 min"]];

/** Series Commitment Matcher: series that fit the time you have, with how long they take to finish. */
export default function SeriesFit() {
  const [f, setF] = useState({ budget: "10", status: "", episode_length: "", per_day: "2" });
  const qs = new URLSearchParams(f).toString();
  const res = useQuery({ queryKey: ["series-fit", qs], queryFn: () => api<Res>(`/recs/series-fit?${qs}`) });
  const sel = "rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm";
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="mx-auto max-w-[1800px] px-4 pb-20 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Find a series that fits your time</h1>
      <p className="mt-1 text-sm text-muted">Total time is episodes x typical episode length. Best matches for you first.</p>
      <div className="mt-6 flex flex-wrap gap-3">
        <select className={sel} value={f.budget} onChange={set("budget")} aria-label="Time you have">{BUDGET.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className={sel} value={f.per_day} onChange={set("per_day")} aria-label="Episodes a day">{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n} episode{n > 1 ? "s" : ""} a day</option>)}</select>
        <select className={sel} value={f.status} onChange={set("status")} aria-label="Status">{STATUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className={sel} value={f.episode_length} onChange={set("episode_length")} aria-label="Episode length">{LENGTH.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      </div>
      <p className="mt-4 text-sm text-muted">{res.data ? `${res.data.total.toLocaleString()} series fit` : "Loading…"}</p>
      <div className="mt-4 grid grid-cols-1 gap-x-4 gap-y-8 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {res.data?.items.map((it) => (
          <Link key={it.movie.id} to={`/movie/${it.movie.id}`} className="block">
            <CardArtwork item={it} />
            <p className="mt-2 text-sm font-medium">{it.movie.title}{it.movie.year ? <span className="text-muted"> · {it.movie.year}</span> : null}</p>
            <p className="text-xs text-muted">{it.plan.text}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
