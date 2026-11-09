/** IMDb's rating, labelled as IMDb's. Renders nothing for films IMDb has no rating for. */
export default function ImdbScore({ rating, votes, className = "" }: { rating?: number | null; votes?: number | null; className?: string }) {
  if (rating == null) return null;
  return (
    <span className={`inline-flex items-center gap-1 ${className}`} title={votes != null ? `IMDb rating from ${votes.toLocaleString()} votes` : "IMDb rating"}>
      <span className="rounded-sm bg-[#f5c518] px-1 text-[0.7em] font-extrabold leading-tight text-black">IMDb</span>
      <span>{rating.toFixed(1)}</span>
      {votes != null && <span className="text-muted">({compact(votes)})</span>}
    </span>
  );
}

function compact(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}K` : String(n);
}
