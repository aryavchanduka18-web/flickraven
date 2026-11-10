import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Reason } from "../../api/types";
import { useUI } from "../layout/ui";
import ConfidenceCard, { SOURCE_NAME, type Confidence } from "./ConfidenceCard";

type Explain = {
  movie_id: number; stage: string; behavioral_count: number; onboarding_count: number; logged_interactions: number; match_pct: number | null;
  shares: Record<string, number>; reasons: Reason[]; weights: Record<string, number>; confidence: Confidence;
};

const SOURCE = SOURCE_NAME;

/** "Why?": everything the engine can say about one recommendation, from /recs/explain. */
export default function WhyPanel() {
  const { whyId, openWhy } = useUI();
  const q = useQuery({ queryKey: ["explain", whyId], queryFn: () => api<Explain>(`/recs/explain/${whyId}`), enabled: whyId != null });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && openWhy(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openWhy]);
  const shares = Object.entries(q.data?.shares ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <AnimatePresence>
      {whyId != null && (
        <motion.div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 backdrop-blur-sm md:items-center md:p-6"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => openWhy(null)}>
          <motion.div role="dialog" aria-modal="true" aria-label="Why you are seeing this"
            className="max-h-[88vh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-t-2xl bg-bg p-5 ring-1 ring-white/10 md:rounded-2xl md:p-7"
            initial={{ y: 30 }} animate={{ y: 0 }} exit={{ y: 30 }} transition={{ duration: 0.2 }} onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-xl font-bold">Why you&apos;re seeing this</h2>
              <button onClick={() => openWhy(null)} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-full bg-white/10">✕</button>
            </div>
            {!q.data ? <div className="h-64 animate-pulse rounded-lg bg-surface-2" /> : (
              <div className="space-y-6 text-sm">
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  {q.data.match_pct != null && <span className="font-display text-3xl font-extrabold text-accent">{q.data.match_pct}% match</span>}
                  <div className="text-muted">
                    <div>Profile stage: <span className="capitalize text-white/85">{q.data.stage}</span></div>
                    <div>Qualifying distinct titles: {q.data.behavioral_count} (ratings, likes, dislikes, list adds, watched)</div>
                    <div>Logged interactions: {q.data.logged_interactions} (repeat views do not add titles)</div>
                    <div>Onboarding picks: {q.data.onboarding_count} (not counted toward the stage)</div>
                  </div>
                </div>
                {q.data.reasons.length > 0 && (
                  <ul className="space-y-1.5">
                    {q.data.reasons.map((r) => (
                      <li key={r.code + r.text} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                        {r.anchor_movie_id ? <Link to={`/movie/${r.anchor_movie_id}`} onClick={() => openWhy(null)} className="underline decoration-white/30 underline-offset-2">{r.text}</Link> : r.text}
                      </li>
                    ))}
                  </ul>
                )}
                <section>
                  <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">Share of the blend</h3>
                  <div className="space-y-2">
                    {shares.map(([s, v]) => (
                      <div key={s} className="grid grid-cols-[minmax(0,13rem)_1fr_3rem] items-center gap-3">
                        <span className="truncate text-white/85">{SOURCE[s] ?? s}</span>
                        <div className="h-1.5 rounded-full bg-white/10"><div className="h-1.5 rounded-full bg-white/80" style={{ width: `${v * 100}%` }} /></div>
                        <span className="text-right tabular-nums text-white/70">{Math.round(v * 100)}%</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-muted">Each share is how much that method counts in the final blend at your stage, not how highly it ranks this title. Methods with zero weight at your stage are left out.</p>
                </section>
                <ConfidenceCard c={q.data.confidence} />
                <Link to={`/movie/${q.data.movie_id}`} onClick={() => openWhy(null)} className="inline-block text-sm font-medium underline underline-offset-4">Open the film page</Link>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
