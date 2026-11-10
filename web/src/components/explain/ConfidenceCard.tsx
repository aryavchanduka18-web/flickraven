import { useState } from "react";
import { Link } from "react-router-dom";

export type Confidence = {
  agreement: number | null;
  label: "High" | "Moderate" | "Low" | null;
  sentence: string;
  stage: string;
  groups: { key: string; label: string; score: number | null }[];
  technical: { source: string; model: string; percentile: number; weight: number; counted: boolean }[];
};

const TONE: Record<string, string> = { High: "bg-emerald-400", Moderate: "bg-amber-300", Low: "bg-white/60" };
export const SOURCE_NAME: Record<string, string> = {
  svd: "SVD rating prediction", item_cf: "Item-Based Collaborative Filtering", user_cf: "User-Based Collaborative Filtering",
  content: "Content-Based Filtering", als: "Implicit ALS (Behavioural)", popularity: "Popularity",
};
const TECH_NAME = SOURCE_NAME;
const GROUP_OF: Record<string, string> = {
  svd: "Collaborative", item_cf: "Collaborative", user_cf: "Collaborative", content: "Content", als: "Behavioral",
  popularity: "Popularity",
};

/** Model Agreement: how much the methods agree on this title for you. The Match % is shown once, outside this card. */
export default function ConfidenceCard({ c }: { c?: Confidence }) {
  const [open, setOpen] = useState(false);
  if (!c) return null;
  const filled = c.agreement == null ? 0 : Math.round(c.agreement / 10);
  return (
    <section className="rounded-xl border border-white/10 bg-surface p-5" aria-label="Model agreement">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Model Agreement</h3>

      <div className="mt-3 flex items-center gap-3 text-xs text-muted">
        <span>
          {c.agreement == null ? "Model agreement not available yet" : `${c.agreement}% model agreement`}
          {c.label && ` · ${c.label.toLowerCase()}`}
        </span>
        {/* Ten fixed segments, no knob or track: a reading, not a control. */}
        <span className="grid w-24 grid-cols-10 gap-0.5" role="img" aria-label={c.agreement == null ? "Agreement not available yet" : `${c.agreement} percent agreement`}>
          {Array.from({ length: 10 }, (_, i) => (
            <span key={i} className={`h-1 rounded-sm ${i < filled ? TONE[c.label ?? "Low"] : "bg-white/10"}`} />
          ))}
        </span>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-white/85">{c.sentence}</p>
      <p className="mt-1 text-xs text-muted">
        Model agreement shows whether the different methods rank this title alike. It is not the chance that the match is right, and it has not been checked against real outcomes. It is separate from your Match %.
      </p>

      <dl className="mt-4 space-y-2.5">
        {c.groups.filter((g) => g.key !== "hybrid").map((g) => (
          <div key={g.key} className="grid grid-cols-[7.5rem_1fr_3rem] items-center gap-3 text-sm">
            <dt className={g.key === "hybrid" ? "font-semibold" : "text-white/80"}>{g.label}</dt>
            <dd className="h-1 overflow-hidden rounded-full bg-white/10" aria-hidden>
              {g.score != null && <div className={`h-full rounded-full ${g.key === "hybrid" ? "bg-accent" : "bg-white/70"}`} style={{ width: `${g.score}%` }} />}
            </dd>
            <dd className="text-right tabular-nums text-white/85">{g.score == null ? <span className="text-xs text-muted">no data</span> : g.score}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-muted">Model scores: where this film ranks for you among everything that model can judge (100 = its top pick). "No data" means that method cannot judge this title, which is not the same as a low rank.</p>

      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="mt-4 text-xs font-medium text-white/70 underline decoration-white/30 underline-offset-4 hover:text-white">
        {open ? "Hide technical details" : "Technical details"}
      </button>
      {open && (
        <div className="mt-3 space-y-3 border-t border-white/10 pt-3 text-xs text-white/75">
          <table className="w-full text-left">
            <thead className="text-muted">
              <tr><th className="pb-1 font-normal">Shown as</th><th className="pb-1 font-normal">Model</th><th className="pb-1 text-right font-normal">Rank</th><th className="pb-1 text-right font-normal">Weight</th></tr>
            </thead>
            <tbody>
              {c.technical.map((t) => (
                <tr key={t.source} className={t.counted ? "" : "text-muted"} title={t.model}>
                  <td className="py-0.5">{GROUP_OF[t.source] ?? t.source}</td>
                  <td>{TECH_NAME[t.source] ?? t.source}</td>
                  <td className="text-right tabular-nums">{t.percentile}</td>
                  <td className="text-right tabular-nums">{t.weight}</td>
                </tr>
              ))}
              <tr><td className="py-0.5">Hybrid</td><td colSpan={3}>Stage-weighted blend of the ranks above, calibrated to Match %</td></tr>
            </tbody>
          </table>
          <ul className="list-disc space-y-1 pl-4">
            {c.technical.map((t) => <li key={t.source}><span className="text-white">{TECH_NAME[t.source]}</span>: {t.model}</li>)}
            <li>Weights are tuned for your stage ({c.stage}). Agreement = 100 × (1 − 2 × the spread of the weighted models' ranks).</li>
            <li>Neural CF (NCF) is evaluated in the <Link to="/lab" className="underline">Research Lab</Link>; it is not part of the live blend.</li>
          </ul>
        </div>
      )}
    </section>
  );
}
