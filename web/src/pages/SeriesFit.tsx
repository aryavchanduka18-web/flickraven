import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import { CardArtwork } from "../components/card/MovieCard";
import ImdbScore from "../components/movie/ImdbScore";
import { PageMessage } from "../components/Loading";
import { languageName, runtime } from "../lib/format";

type Plan = { hours: number; days: number | null; finish: string | null; text: string };
type Facts = { seasons: number | null; episodes: number; runtime: number; status: string | null; hours: number };
type Item = RecItem & { plan: Plan; series: Facts };
type Res = { items: Item[]; total: number; unknown_length: number; more_with_next_budget: { budget: string; extra: number } | null;
  options: { languages: string[]; genres: string[] } };

const BUDGET: [string, string][] = [["3", "Up to 3 hours"], ["5", "Up to 5 hours"], ["10", "Up to 10 hours"], ["20", "Up to 20 hours"], ["long", "More than 20 hours"], ["", "Any"]];
const PER_DAY: [string, string][] = [["1", "One episode a day"], ["2", "Two episodes a day"], ["3", "Three episodes a day"], ["0", "Flexible"]];
const TYPE: [string, string][] = [["", "No preference"], ["mini", "Mini-series (10 episodes or fewer)"], ["short", "Short (11-30 episodes)"], ["medium", "Medium (31-80 episodes)"], ["long", "Long-running (81+ episodes)"]];
const STATUS: [string, string][] = [["", "Either"], ["ended", "Completed"], ["airing", "Currently airing"]];
const LENGTH: [string, string][] = [["", "Any episode length"], ["short", "30 min or less"], ["medium", "31-45 min"], ["long", "46-60 min"], ["xl", "Over 60 min"]];
const SORT: [string, string][] = [["best", "Best for you"], ["shortest", "Shortest first"], ["longest", "Longest first"], ["rated", "Highest rated"], ["completed", "Completed first"]];
const STATUS_LABEL: Record<string, string> = { Ended: "Completed", Canceled: "Ended early", "Returning Series": "Still airing" };

/** Find a Series That Fits Your Time. Total time = episodes x TMDB's typical episode length; series missing either
 *  number are left out and counted, never guessed. "Best for you" is your own series ranking: series have no Match %. */
export default function SeriesFit() {
  const [f, setF] = useState({ budget: "10", per_day: "2", series_type: "", status: "", episode_length: "", genre: "", language: "", sort: "best" });
  const qs = new URLSearchParams(f).toString();
  const res = useQuery({ queryKey: ["series-fit", qs], queryFn: () => api<Res>(`/recs/series-fit?${qs}`), placeholderData: (p) => p });
  const set = (k: keyof typeof f, v: string) => setF((o) => ({ ...o, [k]: v }));
  const sel = "w-full rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm";
  const Field = ({ label, children }: { label: string; children: React.ReactNode }) => <label className="block text-sm"><span className="mb-1 block text-muted">{label}</span>{children}</label>;
  const Select = ({ k, opts, label }: { k: keyof typeof f; opts: [string, string][]; label: string }) => (
    <Field label={label}><select className={sel} value={f[k]} onChange={(e) => set(k, e.target.value)}>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
  );
  const d = res.data;
  return (
    <div className="mx-auto max-w-[1800px] px-4 pb-24 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Find a Series That Fits Your Time</h1>
      <p className="mt-1 text-sm text-muted">Tell us how much time you have and we will shortlist series you can actually finish.</p>
      <div className="mt-6 grid gap-8 lg:grid-cols-[320px_1fr]">
        <aside className="space-y-4 rounded-xl border border-white/10 bg-surface p-5 lg:self-start">
          <fieldset>
            <legend className="mb-2 text-sm text-muted">How much time do you have?</legend>
            <div className="flex flex-wrap gap-2">
              {BUDGET.map(([v, l]) => (
                <button key={l} type="button" aria-pressed={f.budget === v} onClick={() => set("budget", v)}
                  className={`rounded-md border px-3 py-1.5 text-sm ${f.budget === v ? "border-accent bg-accent" : "border-white/20 hover:border-white/50"}`}>{l}</button>
              ))}
            </div>
          </fieldset>
          <Select k="per_day" opts={PER_DAY} label="How often do you watch?" />
          <Select k="series_type" opts={TYPE} label="What type of series?" />
          <Select k="status" opts={STATUS} label="Series status" />
          <Select k="episode_length" opts={LENGTH} label="Episode duration" />
          <Select k="genre" opts={[["", "Any genre"], ...(d?.options.genres ?? []).map((g): [string, string] => [g, g])]} label="Genre" />
          <Select k="language" opts={[["", "Any language"], ...(d?.options.languages ?? []).map((l): [string, string] => [l, languageName(l)])]} label="Language" />
        </aside>
        <section aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-xl font-bold">Your Series Shortlist</h2>
            <label className="flex items-center gap-2 text-sm text-muted">Sort
              <select className="rounded-md border border-white/15 bg-surface-2 px-3 py-1.5 text-sm text-white" value={f.sort} onChange={(e) => set("sort", e.target.value)}>
                {SORT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          </div>
          {res.isError && <PageMessage title="The shortlist could not be loaded">Something went wrong. <button className="underline" onClick={() => res.refetch()}>Try again</button></PageMessage>}
          {d && (
            <>
              <p className="mt-2 text-sm text-muted">
                {d.total.toLocaleString()} series fit.
                {d.unknown_length > 0 && ` ${d.unknown_length.toLocaleString()} series are left out because TMDB has no episode count or episode length for them.`}
                {f.sort === "best" && " “Best for you” follows your own series ranking; series have no Match %, because there are no ratings for them."}
              </p>
              {d.more_with_next_budget && d.more_with_next_budget.extra > 0 && (
                <button type="button" onClick={() => set("budget", d.more_with_next_budget!.budget)} className="mt-2 text-sm underline underline-offset-4">
                  Stretch your time: {d.more_with_next_budget.extra.toLocaleString()} more fit
                </button>
              )}
              {!d.items.length ? (
                <div className="mt-8 rounded-xl border border-white/10 bg-surface p-6 text-sm text-white/80">
                  No series match all of these. Try a longer time budget, or set the type, genre or language to “any”.
                </div>
              ) : (
                <div className="mt-5 grid grid-cols-1 gap-x-4 gap-y-8 sm:grid-cols-2 xl:grid-cols-3">
                  {d.items.map((it) => (
                    <Link key={it.movie.id} to={`/movie/${it.movie.id}`} className="block">
                      <CardArtwork item={it} />
                      <p className="mt-2 text-sm font-medium">{it.movie.title}{it.movie.year ? <span className="text-muted"> · {it.movie.year}</span> : null}</p>
                      <p className="text-xs text-white/80">
                        {it.series.seasons ? `${it.series.seasons} season${it.series.seasons === 1 ? "" : "s"} · ` : ""}{it.series.episodes} episodes · about {it.series.hours} hours
                      </p>
                      <p className="text-xs text-muted">{runtime(it.series.runtime)} per episode · {STATUS_LABEL[it.series.status ?? ""] ?? "Status unknown"}</p>
                      <p className="text-xs text-muted">{it.plan.finish ? `Finish in ${it.plan.finish}` : "No schedule: you set the pace"}</p>
                      {it.movie.imdb_rating != null && <div className="mt-1"><ImdbScore rating={it.movie.imdb_rating} votes={it.movie.imdb_votes ?? null} /></div>}
                    </Link>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
