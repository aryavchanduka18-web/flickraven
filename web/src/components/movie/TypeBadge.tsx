/** Marks a series or anime (films get no badge). */
export default function TypeBadge({ type, className = "" }: { type?: string | null; className?: string }) {
  if (!type || type === "movie") return null;
  return (
    <span className={`rounded-sm border border-white/40 px-1.5 text-[0.7em] font-semibold uppercase leading-tight tracking-wide text-white/90 ${className}`}>
      {type === "anime" ? "Anime" : "Series"}
    </span>
  );
}
