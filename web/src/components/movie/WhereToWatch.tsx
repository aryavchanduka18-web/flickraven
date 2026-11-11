import { providerSearchUrl } from "../../lib/providers";
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
export default function WhereToWatch({ watch, title = "" }: { watch: Watch | null | undefined; title?: string }) {
  // Nothing is listed (or the data has not been loaded yet): show nothing, never a claim about availability.
  if (!watch) return null;
  const where = COUNTRY[watch.region] ?? watch.region;
  return (
    <section id="where-to-watch" className="scroll-mt-24">
      <h2 className="font-display text-xl font-bold">Where to watch <span className="text-sm font-normal text-muted">in {where}</span></h2>
      {watch.region !== "IN" && <p className="mt-1 text-xs text-muted">Not listed on any service in India, so this shows {where}.</p>}
      <div className="mt-3 space-y-3">
        {KINDS.filter(([k]) => watch.providers[k]?.length).map(([k, label]) => (
          // Label in a fixed left column, pills in their own wrapping column, so a second line of pills
          // lines up under the first pill instead of sliding back under the label. On phones the label sits above.
          <div key={k} className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-3">
            <span className="text-sm leading-5 text-white/70 sm:w-28 sm:shrink-0 sm:pt-2">{label}</span>
            <div className="flex min-w-0 flex-1 flex-wrap gap-2 sm:gap-3">
            {watch.providers[k]!.map((p) => (
              <a key={p.name} href={title ? providerSearchUrl(p.name, title) : watch.link ?? undefined} target="_blank" rel="noopener noreferrer"
                 title={`${label} on ${p.name}: opens ${p.name}'s search for this title`}
                 className="glass-btn rounded-xl px-3 py-1.5 text-sm font-medium">
                {p.logo && <img src={tmdbImage(p.logo, "w92")} alt="" className="h-6 w-6 rounded-md" />}
                {p.name}
              </a>
            ))}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Each button opens that service's search for the title (TMDB does not give direct links).{watch.link && (<> <a href={watch.link} target="_blank" rel="noopener noreferrer" className="underline">See every option on JustWatch</a>.</>)}
      </p>
      <p className="mt-1 text-xs text-muted">
        Availability from <a href="https://www.justwatch.com" target="_blank" rel="noopener noreferrer" className="underline">JustWatch</a> via TMDB,
        updated {new Date(watch.updated).toLocaleDateString(undefined, { month: "long", year: "numeric" })}. Check the service before you pay.
      </p>
    </section>
  );
}
