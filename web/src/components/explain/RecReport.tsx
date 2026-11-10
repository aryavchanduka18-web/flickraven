import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Report } from "../../pages/Performance";

/** Compact version for the Activity page; the full report is at /performance. */
export default function RecReport() {
  const { data } = useQuery({ queryKey: ["report"], queryFn: () => api<Report>("/me/report") });
  if (!data) return null;
  return (
    <section className="mt-6 rounded-2xl border border-white/10 bg-surface p-5">
      <h2 className="font-display text-xl font-bold">Your recommendation report</h2>
      <p className="mt-2 text-sm text-white/85">
        {data.ready
          ? `${data.positive_pct}% of the ${data.rated} recommendations you rated got ${data.positive_threshold} or more; your average was ${data.avg_rating}.`
          : `${data.rated} of ${data.needed} recommended titles rated. Percentages appear at ${data.needed}, so they mean something.`}
      </p>
      <Link to="/performance" className="mt-2 inline-block text-sm underline underline-offset-4">How well does FlickRaven know you?</Link>
    </section>
  );
}
