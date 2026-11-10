import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, send } from "../../api/client";

/** Only for titles FlickRaven recommended and you then rated: how well did it match your taste? Optional. */
export default function RecOutcomeFeedback({ movieId }: { movieId: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["rec-outcome", movieId], queryFn: () => api<{ eligible: boolean; answer: string | null; options: { key: string; label: string }[] }>(`/feedback/rec-outcome/${movieId}`) });
  const [err, setErr] = useState(false);
  if (!q.data?.eligible) return null;
  const pick = async (answer: string) => {
    setErr(false);
    try {
      await send("PUT", `/feedback/rec-outcome/${movieId}`, { answer });
      qc.invalidateQueries({ queryKey: ["rec-outcome", movieId] });
      qc.invalidateQueries({ queryKey: ["report"] });
    } catch { setErr(true); }
  };
  return (
    <div className="max-w-2xl rounded-lg border border-white/10 bg-black/50 p-4">
      <p className="text-sm font-semibold">How well did this recommendation match your taste?</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {q.data.options.map((o) => (
          <button key={o.key} type="button" aria-pressed={q.data!.answer === o.key} onClick={() => pick(o.key)}
            className={`rounded-md border px-3 py-1.5 text-sm ${q.data!.answer === o.key ? "border-white bg-white text-black" : "border-white/20 text-white/85 hover:border-white/60"}`}>{o.label}</button>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">Optional. It shows up in your recommendation report; it does not change the models.</p>
      {err && <p role="alert" className="mt-1 text-xs text-accent-hover">Could not save. Try again.</p>}
    </div>
  );
}
