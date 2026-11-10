import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

type Report = {
  rated: number; needed: number; ready: boolean;
  positive_pct?: number; avg_rating?: number; avg_predicted_match?: number | null;
  best_genres?: string[]; missed_genres?: string[]; top_reasons?: string[];
};

/** How FlickRaven's recommendations turned out for you: predicted vs what you actually rated. */
export default function RecReport() {
  const { data } = useQuery({ queryKey: ["report"], queryFn: () => api<Report>("/me/report") });
  if (!data) return null;
  return (
    <section className="mt-6 rounded-2xl border border-white/10 bg-surface p-5">
      <h2 className="font-display text-xl font-bold">Your recommendation report</h2>
      {!data.ready ? (
        <p className="mt-2 text-sm text-muted">
          Rate {data.needed - data.rated} more recommended title{data.needed - data.rated === 1 ? "" : "s"} to see how well our picks
          fit you ({data.rated} of {data.needed} so far). Only titles we recommended and you then rated count.
        </p>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat value={`${data.positive_pct}%`} label="rated 7 or higher" />
            <Stat value={`${data.avg_rating}`} label="your average rating" />
            <Stat value={data.avg_predicted_match != null ? `${data.avg_predicted_match}%` : "n/a"} label="our average Match %" />
            <Stat value={`${data.rated}`} label="recommendations you rated" />
          </div>
          <ul className="mt-4 space-y-1 text-sm text-white/85">
            {!!data.best_genres?.length && <li>What works for you: {data.best_genres.join(", ")}.</li>}
            {!!data.missed_genres?.length && <li>Where we miss: {data.missed_genres.join(", ")}.</li>}
            {!!data.top_reasons?.length && <li>Your most common reasons for hiding our picks: {data.top_reasons.join(", ")}.</li>}
          </ul>
          <p className="mt-3 text-xs text-muted">From the last 60 days. Recommendations you never rated are not counted as misses.</p>
        </>
      )}
    </section>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="font-display text-3xl font-extrabold">{value}</p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  );
}
