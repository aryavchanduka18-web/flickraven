import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

/** One sentence from your Taste DNA, shown only when your stored activity supports it. */
export default function TasteReason({ movieId }: { movieId: number }) {
  const q = useQuery({ queryKey: ["taste-title", movieId], queryFn: () => api<{ reason: string | null; clash?: string[] }>(`/movies/${movieId}/taste-dna`) });
  if (!q.data?.reason && !q.data?.clash?.length) return null;
  return (
    <div className="rounded-lg border border-white/10 bg-surface px-4 py-3 text-sm text-white/85">
      {q.data.reason && <p>{q.data.reason}</p>}
      {!!q.data.clash?.length && <p className="text-white/70">Heads up: it leans on {q.data.clash.join(", ").toLowerCase()}, which you tend to avoid.</p>}
      <Link to="/taste-dna" className="mt-1 inline-block text-xs text-muted underline underline-offset-4 hover:text-white">See your Taste DNA</Link>
    </div>
  );
}
