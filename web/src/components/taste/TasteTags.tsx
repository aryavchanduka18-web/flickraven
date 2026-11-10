import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, send } from "../../api/client";

type Opts = { liked: { key: string; label: string }[]; disliked: { key: string; label: string }[] };

/** Optional, after rating: what you enjoyed and what did not work. Shown only once the title has an opinion on it
 *  (a rating, like or watched mark). Saved tags feed Taste DNA (see /taste-dna). */
export default function TasteTags({ movieId, rated }: { movieId: number; rated: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tags", movieId], queryFn: () => api<{ tags: string[]; options: Opts }>(`/feedback/tags/${movieId}`), enabled: rated });
  const [picked, setPicked] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  useEffect(() => { if (q.data) setPicked(q.data.tags); }, [q.data]);
  if (!rated || !q.data) return null;
  const toggle = (k: string) => { setState("idle"); setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k])); };
  const save = async () => {
    setState("saving");
    try {
      await send("PUT", `/feedback/tags/${movieId}`, { tags: picked });
      setState("saved");
      for (const k of ["tags", "taste-dna", "taste-title"]) qc.invalidateQueries({ queryKey: [k] });
    } catch { setState("error"); }
  };
  const chip = (k: string, l: string) => (
    <button key={k} type="button" onClick={() => toggle(k)} aria-pressed={picked.includes(k)}
      className={`rounded-md border px-3 py-1.5 text-sm ${picked.includes(k) ? "border-white bg-white text-black" : "border-white/20 text-white/85 hover:border-white/60"}`}>{l}</button>
  );
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)} className="text-sm text-white/70 underline underline-offset-4 hover:text-white">
        {q.data.tags.length ? `Your tags: ${q.data.tags.length} (edit)` : "Tell us what you liked (optional)"}
      </button>
    );
  return (
    <div className="max-w-2xl rounded-lg border border-white/10 bg-black/50 p-4">
      <p className="text-sm font-semibold">What did you enjoy about this title?</p>
      <div className="mt-2 flex flex-wrap gap-2">{q.data.options.liked.map((o) => chip(o.key, o.label))}</div>
      <p className="mt-4 text-sm font-semibold">What did not work for you?</p>
      <div className="mt-2 flex flex-wrap gap-2">{q.data.options.disliked.map((o) => chip(o.key, o.label))}</div>
      <div className="mt-4 flex items-center gap-3">
        <button type="button" onClick={save} disabled={state === "saving"} className="rounded-md bg-white px-4 py-1.5 text-sm font-semibold text-black disabled:opacity-50">
          {state === "saving" ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm text-muted hover:text-white">Close</button>
        {state === "saved" && <span role="status" className="text-sm text-white/80">Saved. It shapes your Taste DNA.</span>}
        {state === "error" && <span role="alert" className="text-sm text-accent-hover">Could not save. Try again.</span>}
      </div>
    </div>
  );
}
