import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { send } from "../../api/client";
import type { RecItem } from "../../api/types";
import { LANGUAGES } from "../../lib/format";
import MovieGrid from "../card/MovieGrid";

const MOODS = ["Funny", "Scary", "Intense", "Relaxed", "Feel-good", "Romantic", "Mind-bending"];
const RUNTIMES = [
  { v: "", l: "Any length" },
  { v: "short", l: "Under 90 min" },
  { v: "medium", l: "90-120 min" },
  { v: "long", l: "2 hours+" },
];

type Result = { items: RecItem[]; relaxed: string[]; message: string | null };

/** For Tonight: the knowledge-based recommender. Constraints are hard filters, relaxed only if needed. */
export default function TonightPanel({ languages = [] }: { languages?: string[] }) {
  const [mood, setMood] = useState("Feel-good");
  const [runtime, setRuntime] = useState("");
  const [lang, setLang] = useState("");
  const run = useMutation({
    mutationFn: () => send<Result>("POST", "/recs/tonight", { mood, runtime: runtime || null, languages: lang ? [lang] : [], genres: [] }),
  });
  const langOptions = languages.length ? languages : ["en", "hi", "ta", "te", "ml", "ko", "ja", "es", "fr"];
  return (
    <section className="rounded-xl border border-white/10 bg-surface p-5" aria-label="For Tonight">
      <h2 className="font-display text-xl font-bold">For Tonight</h2>
      <p className="mt-1 text-sm text-muted">Tell us the mood. We filter by your answers, then rank what's left for you.</p>
      <div className="mt-4 flex flex-wrap gap-2" role="radiogroup" aria-label="Mood">
        {MOODS.map((m) => (
          <button key={m} role="radio" aria-checked={mood === m} onClick={() => setMood(m)}
            className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${mood === m ? "border-white bg-white text-black" : "border-white/20 hover:border-white/50"}`}>
            {m}
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <select value={runtime} onChange={(e) => setRuntime(e.target.value)} aria-label="Runtime"
          className="rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm">
          {RUNTIMES.map((r) => <option key={r.v} value={r.v}>{r.l}</option>)}
        </select>
        <select value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language"
          className="rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm">
          <option value="">Any language</option>
          {langOptions.map((c) => <option key={c} value={c}>{LANGUAGES[c] ?? c}</option>)}
        </select>
        <button onClick={() => run.mutate()} disabled={run.isPending}
          className="rounded-md bg-white px-5 py-2 text-sm font-semibold text-black hover:bg-white/85 disabled:opacity-60">
          {run.isPending ? "Finding films…" : "Show me films"}
        </button>
      </div>
      {run.data?.message && <p className="mt-4 rounded-md bg-surface-2 px-3 py-2 text-sm text-white/85">{run.data.message}</p>}
      {run.data && (
        <div className="mt-5">
          {run.data.items.length ? <MovieGrid items={run.data.items} source="tonight" /> : <p className="text-sm text-muted">Nothing fits yet. Try another mood.</p>}
        </div>
      )}
      {run.isError && <p className="mt-3 text-sm text-red-300">{(run.error as Error).message}</p>}
    </section>
  );
}