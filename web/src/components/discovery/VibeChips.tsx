export const VIBES: [string, string][] = [["", "Any mood"], ["feelgood", "Feel-good"], ["romance", "Romantic"]];

/** A mood filter shown with every genre list: Feel-good and Romantic work on any genre, for films and shows. */
export default function VibeChips({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Mood">
      {VIBES.map(([v, l]) => (
        <button key={v || "any"} role="tab" aria-selected={value === v} onClick={() => onChange(v)}
          className={`glass-btn rounded-full px-4 py-1.5 text-sm ${value === v ? "on" : ""}`}>{l}</button>
      ))}
    </div>
  );
}
