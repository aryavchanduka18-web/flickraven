import { tmdbImage } from "../../lib/tmdb";

export type Watch = {
  region: string;
  link: string | null;
  updated: string;
  providers: Partial<Record<"flatrate" | "free" | "ads" | "rent" | "buy", { name: string; logo: string | null }[]>>;
};

const KINDS = [["flatrate", "Stream"], ["free", "Free"], ["ads", "Free with ads"], ["rent", "Rent"], ["buy", "Buy"]] as const;
const COUNTRY: Record<string, string> = { IN: "India", US: "the US" };

/** Services TMDB lists for this film (data by JustWatch). Only links out; the section is hidden when TMDB lists none. */
export default function WhereToWatch({ watch }: { watch: Watch | null | undefined; title?: string }) {
  // Nothing is listed (or the data has not been loaded yet): show nothing, never a claim about availability.
  if (!watch) return null;
  const where = COUNTRY[watch.region] ?? watch.region;
  return (
    <section>
      <h2 className="font-display text-xl font-bold">Where to watch <span className="text-sm font-normal text-muted">in {where}</span></h2>
      {watch.region !== "IN" && <p className="mt-1 text-xs text-muted">Not listed on any service in India, so this shows {where}.</p>}
      <div className="mt-3 space-y-3">
        {KINDS.filter(([k]) => watch.providers[k]?.length).map(([k, label]) => (
          <div key={k} className="flex flex-wrap items-center gap-3">
            <span className="w-24 text-sm text-white/70">{label}</span>
            {watch.providers[k]!.map((p) => (
              <a key={p.name} href={watch.link ?? undefined} target="_blank" rel="noopener noreferrer" title={`${label} on ${p.name}`}
                 className="flex items-center gap-2 rounded-md border border-white/10 bg-surface px-2 py-1 text-sm hover:border-white/40">
                {p.logo && <img src={tmdbImage(p.logo, "w92")} alt="" className="h-6 w-6 rounded" />}
                {p.name}
              </a>
            ))}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Availability from <a href="https://www.justwatch.com" target="_blank" rel="noopener noreferrer" className="underline">JustWatch</a> via TMDB,
        updated {new Date(watch.updated).toLocaleDateString(undefined, { month: "long", year: "numeric" })}. Check the service before you pay.
      </p>
    </section>
  );
}
