import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, send } from "../api/client";
import type { RecItem } from "../api/types";
import Rail from "../components/rail/Rail";
import { completedOn, missionCardPng } from "../lib/missionCard";

type Tab = "recommended" | "active" | "completed" | "explore";
type Mission = { key: string; title: string; description: string; why: string; goal: number; progress: number; done: boolean;
  dismissed: boolean; tab: Tab; completed_at: string | null; ranked_by_taste: boolean; suggestions: RecItem[] };
type Res = { missions: Mission[]; counts: Record<Tab, number> };

const TABS: { key: Tab; label: string; empty: string }[] = [
  { key: "recommended", label: "Recommended", empty: "Nothing new to suggest right now. Check Active, or look in Explore." },
  { key: "active", label: "Active", empty: "No mission in progress. A mission becomes active once you mark, rate or like a title that counts towards it." },
  { key: "completed", label: "Completed", empty: "No completed missions yet. They appear here, with the date, when you reach the goal." },
  { key: "explore", label: "Explore", empty: "No other ideas right now. Missions you hide appear here so you can bring them back." },
];

/** Your Discovery Journey: personal challenges that widen what you watch. Progress is counted only from titles you
 *  mark watched, rate or like; each mission says why it was picked, from your own history. */
export default function Missions() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("recommended");
  const [msg, setMsg] = useState("");
  const q = useQuery({ queryKey: ["missions"], queryFn: () => api<Res>("/me/missions") });
  const toggle = useMutation({
    mutationFn: (m: Mission) => send(m.dismissed ? "DELETE" : "PUT", `/me/missions/${encodeURIComponent(m.key)}/dismiss`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["missions"] }),
  });
  const card = async (m: Mission) => {
    try {
      const blob = await missionCardPng({ title: m.title, description: m.description, goal: m.goal, date: completedOn(m.completed_at) });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${m.key.replace(/[^a-z0-9]+/gi, "-")}-mission.png`; a.click(); URL.revokeObjectURL(url);
      setMsg("Downloaded. Nothing is shared until you post it yourself.");
    } catch { setMsg("Could not create the card. Try again."); }
  };
  const shown = q.data?.missions.filter((m) => m.tab === tab) ?? [];
  const cur = TABS.find((t) => t.key === tab)!;
  return (
    <div className="mx-auto max-w-[1800px] px-4 pb-20 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Your Discovery Journey</h1>
      <p className="mt-1 text-sm text-muted">Small challenges to widen what you watch. Progress counts only titles you mark watched, rate or like.</p>
      <div role="tablist" aria-label="Mission groups" className="mt-6 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={`rounded-full border px-4 py-1.5 text-sm ${tab === t.key ? "border-accent bg-accent text-white" : "border-white/15 text-white/80 hover:border-white/40"}`}>
            {t.label}{q.data ? ` (${q.data.counts[t.key]})` : ""}
          </button>
        ))}
      </div>
      {msg && <p className="mt-3 text-xs text-muted" role="status">{msg}</p>}
      {q.isError && <p className="mt-6 text-sm text-muted">Could not load your missions. Try again in a moment.</p>}
      {q.data && shown.length === 0 && <p className="mt-8 text-sm text-muted">{cur.empty}</p>}
      <div className="mt-8 space-y-10" role="tabpanel">
        {shown.map((m) => (
          <section key={m.key}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-xl font-bold">{m.title}</h2>
              <span className="text-sm text-muted">{m.progress} / {m.goal}</span>
            </div>
            {m.done && <p className="text-sm font-medium text-accent">Completed{m.completed_at ? ` on ${completedOn(m.completed_at)}` : ""}</p>}
            <p className="text-sm text-muted">{m.description}</p>
            {m.why && <p className="mt-1 text-sm text-white/80"><span className="text-muted">Why this: </span>{m.why}</p>}
            <div className="mt-2 h-2 w-full max-w-md overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={m.goal} aria-valuenow={m.progress} aria-label={`${m.title} progress`}>
              <div className="h-full rounded-full bg-accent" style={{ width: `${(100 * m.progress) / m.goal}%` }} />
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              {m.done && <button onClick={() => card(m)} className="rounded-md border border-white/20 px-3 py-1.5 hover:border-white/50">Download completion card</button>}
              {!m.done && <button onClick={() => toggle.mutate(m)} disabled={toggle.isPending} className="rounded-md border border-white/20 px-3 py-1.5 hover:border-white/50 disabled:opacity-50">
                {m.dismissed ? "Bring this mission back" : "Not for me"}</button>}
            </div>
            {m.suggestions.length > 0 && (
              <div className="-mx-4 mt-3 md:-mx-10">
                <Rail title={m.ranked_by_taste ? "Ideas to get you there, ordered by your Taste DNA" : "Ideas to get you there"} items={m.suggestions} source={`mission:${m.key}`} personal={false} />
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
