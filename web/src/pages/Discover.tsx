import VibeChips from "../components/discovery/VibeChips";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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

const PERSONAL = ["recommended", "match", "hidden", "novel"];

type Filters = {
  type: string; genre: string; lang: string; country: string; year_min: string; year_max: string; runtime: string;
  min_imdb: string; min_match: string; provider: string; sort: string; vibe: string;
};
const EMPTY: Filters = { type: "movie", genre: "", lang: "", country: "", year_min: "", year_max: "", runtime: "", min_imdb: "", min_match: "", provider: "", sort: "recommended", vibe: "" };
type Options = { countries: { code: string; titles: number }[]; providers: { id: number; name: string; logo: string | null; titles: number }[] };

const countryName = (code: string) => {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
};
const YEARS = Array.from({ length: new Date().getFullYear() - 1920 + 1 }, (_, i) => new Date().getFullYear() - i);

/** `fixed` locks the page to one kind: /movies is films only, /shows' browse link is TV series and anime TV only. */
export default function Discover({ fixed }: { fixed?: "movie" | "show" } = {}) {
  const [params] = useSearchParams();
  const urlType = params.get("type");
  const [f, setF] = useState<Filters>({ ...EMPTY, type: fixed ?? (urlType === "show" || urlType === "all" ? urlType : "movie"), genre: params.get("genre") ?? "", vibe: ["feelgood", "romance"].includes(params.get("vibe") ?? "") ? params.get("vibe")! : "" });
  const [open, setOpen] = useState(false);
  const [total, setTotal] = useState<number | null>(null);
  const genres = useQuery({ queryKey: ["genres"], queryFn: () => api<{ genres: { slug: string; name: string }[] }>("/genres") });
  const options = useQuery({ queryKey: ["discover-options"], queryFn: () => api<Options>("/discover/options"), staleTime: 3600_000 });
  // A Match % exists only for films, and only with a personal sort.
  const matchOk = (f.type === "movie" || f.type === "all") && PERSONAL.includes(f.sort);
  const qs = new URLSearchParams(Object.entries(f).filter(([k, v]) => v && (k !== "min_match" || matchOk)) as [string, string][]);
  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  // Series and anime have no ratings, so only these sorts apply to them (hidden gems and most novel need ratings).
  const sorts = f.type === "movie" || f.type === "all" ? SORTS : SORTS.filter(([v]) => !["hidden", "novel"].includes(v));
  const pickType = (type: string) => setF({ ...f, type, min_match: type === "show" ? "" : f.min_match,
    sort: ["hidden", "novel"].includes(f.sort) && type !== "movie" && type !== "all" ? "recommended" : f.sort });
  const pickGenre = (genre: string) => setF({ ...f, genre, sort: genre === "anime" && PERSONAL.includes(f.sort) ? "popular" : f.sort });
  const active = (["lang", "country", "year_min", "year_max", "runtime", "min_imdb", "min_match", "provider"] as const).filter((k) => f[k] && (k !== "min_match" || matchOk)).length;
  const sel = "glass-btn rounded-xl px-3 py-2.5 text-sm [&>option]:bg-surface [&>option]:text-white";
  const label = "flex flex-col gap-1.5 text-xs font-medium uppercase tracking-wide text-white/55";
  return (
    <div className="mx-auto max-w-[1800px] px-4 pt-20 md:px-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-display text-3xl font-extrabold md:text-4xl">{fixed === "movie" ? "Movies" : fixed === "show" ? "All shows" : "Discover"}</h1>
        <div className="flex items-center gap-3">
          {f.type !== "movie" && <Link to="/series-fit" className="glass-btn rounded-2xl px-4 py-2.5 text-sm font-semibold">Find a series that fits your time</Link>}
          <SurpriseMeButton />
        </div>
      </div>
      <div className="mt-6"><TonightPanel /></div>
      {!fixed && <div className="mt-8 flex flex-wrap gap-2" role="tablist" aria-label="Type">
        {[["movie", "Movies"], ["show", "Shows"], ["all", "Movies and shows"]].map(([v, l]) => (
          <button key={v} role="tab" aria-selected={f.type === v} onClick={() => pickType(v)}
            className={`glass-btn rounded-full px-5 py-2 text-sm font-semibold ${f.type === v ? "on" : ""}`}>{l}</button>
        ))}
      </div>}
      {fixed && <div className="mt-6" />}
      {/* Genres as one scrolling row of pills; Anime is its own genre next to Animation. */}
      <div className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 py-1 md:-mx-10 md:px-10" aria-label="Genres">
        <button onClick={() => pickGenre("")} aria-pressed={!f.genre} className={`glass-btn shrink-0 rounded-full px-4 py-1.5 text-sm ${!f.genre ? "on" : ""}`}>All genres</button>
        {genres.data?.genres.map((g) => (
          <button key={g.slug} onClick={() => pickGenre(g.slug)} aria-pressed={f.genre === g.slug}
            className={`glass-btn shrink-0 rounded-full px-4 py-1.5 text-sm ${f.genre === g.slug ? "on" : ""}`}>{g.name}</button>
        ))}
      </div>
      <div className="mt-3"><VibeChips value={f.vibe} onChange={(vibe) => setF({ ...f, vibe })} /></div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className={`glass-btn rounded-full px-5 py-2 text-sm font-semibold ${open ? "on" : ""}`}>
          Filters{active ? ` · ${active}` : ""}
        </button>
        {active > 0 && (
          <button onClick={() => setF({ ...EMPTY, type: f.type, genre: f.genre, sort: f.sort, vibe: f.vibe })} className="text-sm text-white/65 underline underline-offset-2 hover:text-white">Clear filters</button>
        )}
        <label className="ml-auto flex items-center gap-2 text-sm text-white/65">
          Sort
          <select className={sel} value={f.sort} onChange={set("sort")} aria-label="Sort">
            {sorts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>
      {open && (
        <div className="glass mt-3 grid gap-4 rounded-3xl p-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Filters">
          <label className={label}>Language
            <select className={sel} value={f.lang} onChange={set("lang")} aria-label="Language">
              <option value="">All languages</option>
              {Object.entries(LANGUAGES).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
          </label>
          <label className={label}>Country
            <select className={sel} value={f.country} onChange={set("country")} aria-label="Country">
              <option value="">All countries</option>
              {options.data?.countries.map((c) => <option key={c.code} value={c.code}>{countryName(c.code)}</option>)}
            </select>
          </label>
          <label className={label}>Released from
            <select className={sel} value={f.year_min} onChange={set("year_min")} aria-label="Released from">
              <option value="">Any year</option>
              {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label className={label}>Released until
            <select className={sel} value={f.year_max} onChange={set("year_max")} aria-label="Released until">
              <option value="">Any year</option>
              {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label className={label}>Length
            <select className={sel} value={f.runtime} onChange={set("runtime")} aria-label="Runtime">
              <option value="">Any length</option><option value="short">Under 90 min</option><option value="medium">90-120 min</option><option value="long">2 hours+</option>
            </select>
          </label>
          <label className={label}>IMDb score
            <select className={sel} value={f.min_imdb} onChange={set("min_imdb")} aria-label="Minimum IMDb score">
              <option value="">Any score</option>{[6, 6.5, 7, 7.5, 8, 8.5].map((r) => <option key={r} value={r}>{r}+</option>)}
            </select>
          </label>
          <label className={label}>Match %
            <select className={sel} value={matchOk ? f.min_match : ""} onChange={set("min_match")} disabled={!matchOk} aria-label="Minimum match">
              <option value="">Any match</option>{[60, 70, 80, 90].map((r) => <option key={r} value={r}>{r}%+</option>)}
            </select>
            {!matchOk && <span className="normal-case tracking-normal text-white/40">Films with a personal sort only.</span>}
          </label>
          <label className={label}>Streaming on
            <select className={sel} value={f.provider} onChange={set("provider")} aria-label="Streaming service">
              <option value="">Any service</option>
              {options.data?.providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <span className="normal-case tracking-normal text-white/40">Subscription or free, as TMDB lists it for India.</span>
          </label>
        </div>
      )}
      <p className="mt-4 text-sm text-muted">
        {total != null ? `${total.toLocaleString()} ${f.type === "movie" ? "films" : f.type === "show" ? "shows" : "titles"}` : "Loading…"} · {SORTS.find(([v]) => v === f.sort)?.[2]}
      </p>
      <div className="mt-6">
        <PagedGrid queryKey={["discover", qs.toString()]} path={(p) => `/movies?${qs}${qs.toString() ? "&" : ""}page=${p}`}
          source="discover" poster personal={PERSONAL.includes(f.sort)} onTotal={setTotal} />
      </div>
    </div>
  );
}
