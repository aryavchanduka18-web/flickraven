import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { send } from "../../api/client";
import { useUI } from "../layout/ui";

const REASONS: [string, string][] = [
  ["genre", "Wrong genre for me"], ["slow", "Too slow"], ["predictable", "Too predictable"], ["long", "Too long"],
  ["unexpected", "Not what I expected"], ["language", "Not my language"], ["seen", "Already seen it"],
  ["similar", "Too similar to others"], ["none", "Just not for me"],
];

/** After a dislike: pick one or more reasons, then Save. Each answer changes something real
 *  (see POST /feedback/dislike-reason). */
export default function DislikeReasonSheet() {
  const { dislikeId, askDislikeReason, notify } = useUI();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<string[]>([]);
  const close = () => {
    setPicked([]);
    askDislikeReason(null);
  };
  const save = async () => {
    if (dislikeId == null || !picked.length) return;
    const id = dislikeId;
    const reasons = picked;
    close();
    const res = await send<{ message: string }>("POST", "/feedback/dislike-reason", { movie_id: id, reasons }).catch(() => null);
    notify(res?.message ?? "Thanks, noted.");
    for (const k of ["home", "taste", "movie", "explain", "discover", "collections", "series-rails"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const toggle = (k: string) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));
  return (
    <AnimatePresence>
      {dislikeId != null && (
        <motion.div role="dialog" aria-label="Why not for you?" initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
          exit={{ y: 40, opacity: 0 }} transition={{ duration: 0.18 }}
          className="fixed inset-x-3 bottom-24 z-50 mx-auto max-w-md rounded-2xl bg-surface p-4 shadow-2xl ring-1 ring-white/10 md:bottom-8">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold">Hidden. What was not for you? <span className="font-normal text-muted">Pick any</span></p>
            <button onClick={close} className="text-xs text-muted hover:text-white">Skip</button>
          </div>
          <div className="flex flex-wrap gap-2">
            {REASONS.map(([k, l]) => (
              <button key={k} onClick={() => toggle(k)} aria-pressed={picked.includes(k)}
                className={`rounded-full border px-3 py-1.5 text-sm ${picked.includes(k) ? "border-white bg-white text-black" : "border-white/20 hover:border-white/60"}`}>
                {l}
              </button>
            ))}
          </div>
          <button onClick={save} disabled={!picked.length}
            className="mt-3 w-full rounded-md bg-white py-2 text-sm font-semibold text-black disabled:opacity-40">
            Save{picked.length > 1 ? ` ${picked.length} reasons` : ""}
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
