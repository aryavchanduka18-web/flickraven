import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import PagedGrid from "../components/card/PagedGrid";
import SurpriseMeButton from "../components/discovery/SurpriseMeButton";
import TonightPanel from "../components/discovery/TonightPanel";
import { LANGUAGES } from "../lib/format";

// [value, label, what it does]; the first four are ranked by the recommender (GET /movies, personal_order).
const SORTS: [string, string, string][] = [
  ["recommended", "Recommended for you", "your match, re-ranked with your Tune settings"],
  ["match", "Highest match", "pure predicted match"],
  ["hidden", "Hidden gems", "high match, less well known"],
  ["novel", "Most novel", "genres you have not liked yet come first"],
  ["popular", "Most popular", "most voted on TMDB"],
  ["rating", "Highest rated", "community rating"],
  ["newest", "Newest", "latest releases first"],
];

export default function Discover() {
  const [f, setF] = useState({ type: "movie", genre: "", lang: "", decade: "", runtime: "", min_rating: "", sort: "recommended" });
  const [total, setTotal] = useState<number | null>(null);
  const genres = useQuery({ queryKey: ["genres"], queryFn: () => api<{ genres: { slug: string; name: string }[] }>("/genres") });
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  // Series and anime have no ratings, so only these sorts apply to them (hidden gems and most novel need ratings).
  const sorts = f.type === "movie" || f.type === "all" ? SORTS : SORTS.filter(([v]) => !["hidden", "novel"].includes(v));
  const pickType = (type: string) => setF({ ...f, type, sort: ["hidden", "novel"].includes(f.sort) && type !== "movie" && type !== "all" ? "recommended" : f.sort });
  const sel = "rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm";
  return (
    <div className="mx-auto max-w-[1800px] px-4 pt-24 md:px-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-display text-3xl font-extrabold">Discover</h1>
        <div className="flex items-center gap-3">
          <Link to="/series-fit" className="rounded-full border border-white/20 px-4 py-2 text-sm hover:bg-white/10">Find a series that fits your time</Link>
          <SurpriseMeButton />
        </div>
      </div>
      <div className="mt-6"><TonightPanel /></div>
      <div className="mt-8 flex gap-2" role="tablist" aria-label="Type">
        {[["movie", "Movies"], ["series", "Series"], ["anime", "Anime"], ["all", "All"]].map(([v, l]) => (
          <button key={v} role="tab" aria-selected={f.type === v} onClick={() => pickType(v)}
            className={`rounded-full px-4 py-1.5 text-sm ${f.type === v ? "bg-white font-medium text-black" : "border border-white/20 text-white/85 hover:bg-white/10"}`}>{l}</button>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-3" aria-label="Filters">
        <select className={sel} value={f.genre} onChange={set("genre")} aria-label="Genre">
          <option value="">All genres</option>
          {genres.data?.genres.map((g) => <option key={g.slug} value={g.slug}>{g.name}</option>)}
        </select>
        <select className={sel} value={f.lang} onChange={set("lang")} aria-label="Language">
          <option value="">All languages</option>
          {Object.entries(LANGUAGES).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select>
        <select className={sel} value={f.decade} onChange={set("decade")} aria-label="Decade">
          <option value="">Any decade</option>
          {[2020, 2010, 2000, 1990, 1980, 1970, 1960, 1950].map((d) => <option key={d} value={d}>{d}s</option>)}
        </select>
        <select className={sel} value={f.runtime} onChange={set("runtime")} aria-label="Runtime">
          <option value="">Any length</option><option value="short">Under 90 min</option><option value="medium">90-120 min</option><option value="long">2 hours+</option>
        </select>
        <select className={sel} value={f.min_rating} onChange={set("min_rating")} aria-label="Minimum rating">
          <option value="">Any rating</option>{[6, 7, 7.5, 8].map((r) => <option key={r} value={r}>{r}+</option>)}
        </select>
        <select className={sel} value={f.sort} onChange={set("sort")} aria-label="Sort">
          {sorts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      <p className="mt-4 text-sm text-muted">
        {total != null ? `${total.toLocaleString()} ${f.type === "movie" ? "films" : "titles"}` : "Loading…"} · {SORTS.find(([v]) => v === f.sort)?.[2]}
      </p>
      <div className="mt-6">
        <PagedGrid queryKey={["discover", qs.toString()]} path={(p) => `/movies?${qs}${qs.toString() ? "&" : ""}page=${p}`}
          source="discover" poster personal={["recommended", "match", "hidden", "novel"].includes(f.sort)} onTotal={setTotal} />
      </div>
    </div>
  );
}