import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { PageMessage } from "../components/Loading";

export type Share = { n: number; positive: number; positive_pct: number | null; low: number; high: number; avg_rating: number | null };
export type Report = {
  shown: number; opened: number; watched: number; rated: number; needed: number; ready: boolean; positive_threshold: number; log_days: number;
  positive_pct?: number; low?: number; high?: number; avg_rating?: number; avg_predicted_match?: number | null; rated_without_match?: number;
  buckets?: (Share & { label: string; enough: boolean })[]; statements?: string[]; ranking_note?: string;
  best_genres?: { genre: string; n: number; positive_pct: number }[]; missed_genres?: { genre: string; n: number; low_pct: number }[];
  surfaces?: (Share & { surface: string })[]; trend?: { earlier: Share; later: Share } | null;
  top_reasons?: { reason: string; n: number }[]; feedback?: { key: string; label: string; n: number }[];
};
const SURFACE: Record<string, string> = { hero: "Top banner", top_picks: "Top Picks", tonight: "For Tonight", surprise_me: "Surprise Me", taste_dna: "Taste DNA row", other: "Other rows" };

/** How Well Does Flickeraven Know You? Outcomes of recommendations you rated, with counts and honest limits. */
export default function Performance() {
  const q = useQuery({ queryKey: ["report"], queryFn: () => api<Report>("/me/report") });
  if (q.isLoading) return <div className="mx-auto h-96 max-w-[1100px] animate-pulse px-4 pt-24" />;
  if (q.isError || !q.data) return <PageMessage title="Your report could not be loaded">Something went wrong. <button className="underline" onClick={() => q.refetch()}>Try again</button></PageMessage>;
  const d = q.data;
  const stat = (v: string, l: string) => <div className="rounded-lg border border-white/10 bg-surface p-4"><p className="font-display text-3xl font-extrabold">{v}</p><p className="mt-1 text-xs text-muted">{l}</p></div>;
  return (
    <div className="mx-auto max-w-[1100px] px-4 pb-24 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">How Well Does Flickeraven Know You?</h1>
      <p className="mt-1 text-sm text-muted">A look at how our recommendations performed for you, from the last {d.log_days} days.</p>
      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        {stat(String(d.shown), "titles recommended to you (distinct, last " + d.log_days + " days)")}{stat(`${d.opened} of ${d.shown}`, "you opened")}{stat(`${d.watched} of ${d.shown}`, "you marked watched")}{stat(`${d.rated} of ${d.shown}`, "you rated after we showed them (evaluated)")}
      </div>
      {!d.ready ? (
        <div className="mt-8 rounded-xl border border-white/10 bg-surface p-6">
          <h2 className="font-display text-lg font-bold">Not enough ratings yet</h2>
          <p className="mt-2 text-sm text-white/80">
            Rate {d.needed - d.rated} more title{d.needed - d.rated === 1 ? "" : "s"} we recommended ({d.rated} of {d.needed} so far) to see percentages. With fewer, any
            percentage would say little about us. Only titles we showed you and you then rated count; ones you ignored are never counted as dislikes.
          </p>
          <Link to="/" className="mt-4 inline-block rounded-md bg-accent px-4 py-2 text-sm font-semibold hover:bg-accent-hover">See your recommendations</Link>
        </div>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3">
            {stat(`${d.positive_pct}%`, `positive outcome rate: rated ${d.positive_threshold} or more, out of ${d.rated} evaluated (plausibly ${d.low}-${d.high}%)`)}
            {stat(`${d.avg_rating}`, `average actual rating you gave (${d.rated} ratings)`)}
            {stat(d.avg_predicted_match != null ? `${d.avg_predicted_match}%` : "n/a", `average predicted Match % when shown${d.rated_without_match ? ` (${d.rated! - d.rated_without_match} with a Match %)` : ""}`)}
          </div>
          <section className="mt-8 rounded-xl border border-white/10 bg-surface p-5" aria-label="Match percentage versus outcome">
            <h2 className="font-display text-lg font-bold">Match % versus what you rated</h2>
            <p className="mt-1 text-xs text-muted">Share of rated recommendations you scored {d.positive_threshold} or more, by the Match % we showed. Ranges with fewer than 5 ratings are greyed out.</p>
            <ul className="mt-4 space-y-3">
              {d.buckets!.map((b) => (
                <li key={b.label} className="grid grid-cols-[7rem_1fr_9rem] items-center gap-3 text-sm">
                  <span>{b.label}</span>
                  <div className="h-3 rounded-full bg-white/10" role="img" aria-label={b.n ? `${b.positive_pct}% of ${b.n}` : "no ratings"}>
                    {b.n > 0 && <div className={`h-3 rounded-full ${b.enough ? "bg-accent" : "bg-white/30"}`} style={{ width: `${b.positive_pct}%` }} />}
                  </div>
                  <span className="text-xs text-muted">{b.n ? `${b.positive_pct}% of ${b.n}${b.enough ? "" : " (too few)"}` : "no ratings yet"}</span>
                </li>
              ))}
            </ul>
            {d.statements!.map((s) => <p key={s} className="mt-3 text-sm text-white/90">{s}</p>)}
            <p className="mt-3 text-sm text-white/80">{d.ranking_note}</p>
          </section>
          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <section className="rounded-xl border border-white/10 bg-surface p-5">
              <h2 className="font-display text-base font-bold">Genres</h2>
              <List title="Work for you" rows={d.best_genres?.map((g) => `${g.genre}: ${g.positive_pct}% rated ${d.positive_threshold}+ (of ${g.n})`)} empty="No genre has 3 ratings and a clear lead yet." />
              <List title="Where we miss" rows={d.missed_genres?.map((g) => `${g.genre}: ${g.low_pct}% rated 5 or less (of ${g.n})`)} empty="No genre stands out as a miss." />
            </section>
            <section className="rounded-xl border border-white/10 bg-surface p-5">
              <h2 className="font-display text-base font-bold">What you tell us</h2>
              <List title="Why you hide our picks" rows={d.top_reasons?.map((r) => `${r.reason} (${r.n})`)} empty="You have not given reasons for hidden recommendations." />
              <List title="How well picks matched" rows={d.feedback?.map((f) => `${f.label} (${f.n})`)} empty="You have not answered “How well did this match?” yet. It appears on a film page after you rate a recommendation." />
            </section>
          </div>
          {d.trend && (
            <section className="mt-6 rounded-xl border border-white/10 bg-surface p-5">
              <h2 className="font-display text-base font-bold">Over time</h2>
              <p className="mt-2 text-sm">
                Earlier half: {d.trend.earlier.positive_pct}% rated {d.positive_threshold}+ (of {d.trend.earlier.n}). Later half: {d.trend.later.positive_pct}% (of {d.trend.later.n}).
                {" "}{Math.abs(d.trend.later.positive_pct! - d.trend.earlier.positive_pct!) < 10 ? "The difference is too small to call a trend." : d.trend.later.positive_pct! > d.trend.earlier.positive_pct! ? "Recent picks did better." : "Recent picks did worse."}
              </p>
            </section>
          )}
          {!!d.surfaces?.length && (
            <section className="mt-6 rounded-xl border border-white/10 bg-surface p-5">
              <h2 className="font-display text-base font-bold">By where we showed it</h2>
              <ul className="mt-2 space-y-1 text-sm">{d.surfaces.map((s) => <li key={s.surface}>{SURFACE[s.surface] ?? s.surface}: {s.positive_pct}% rated {d.positive_threshold}+ (of {s.n})</li>)}</ul>
            </section>
          )}
        </>
      )}
      <section className="mt-10 text-xs leading-relaxed text-muted">
        <h2 className="mb-1 text-sm font-semibold text-white/80">How this is calculated</h2>
        <p>
          A recommendation counts when it was shown to you, and its result is the first rating you gave it after that. The Match % used is the one shown the first time.
          Titles you had already rated before we showed them, and ratings imported from Letterboxd or IMDb, are not counted. Titles you did not rate are not counted as
          dislikes. “Rated {d.positive_threshold} or more” is a positive outcome. Percentages appear only from {d.needed} rated recommendations, with the count beside them and a
          95% range in the headline figure. This shows whether higher Match % tends to get better ratings from you; it does not prove the Match % is an exact probability.
          It is a read-out only: nothing here retrains the recommender.
        </p>
      </section>
    </div>
  );
}

function List({ title, rows, empty }: { title: string; rows?: string[]; empty: string }) {
  return (
    <div className="mt-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {rows?.length ? <ul className="mt-1 space-y-1 text-sm">{rows.map((r) => <li key={r}>{r}</li>)}</ul> : <p className="mt-1 text-sm text-muted">{empty}</p>}
    </div>
  );
}
