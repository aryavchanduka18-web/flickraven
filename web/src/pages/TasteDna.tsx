import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, send } from "../api/client";
import type { RecItem } from "../api/types";
import { PageMessage } from "../components/Loading";
import Rail from "../components/rail/Rail";
import Radar from "../components/taste/Radar";
import { useMe } from "../api/hooks";
import { tasteCardPng } from "../lib/tasteCard";

type Trait = { key: string; label: string; you: number; catalog: number; avoid: number; evidence: number; evidence_against: number;
  override: "more" | "less" | null; source: string; catalog_coverage: number };
type Dna = { ready: boolean; titles_used: number; titles_tagged: number; traits: Trait[]; radar: string[]; preferred: string[]; avoided: string[];
  rising: string[]; top_genres: string[]; top_languages: string[]; top_countries: string[]; pacing: string | null; complexity: string | null;
  personality: string | null };

/** Your Taste DNA: storytelling traits learned from what you rated, liked and tagged, next to the catalog average. */
export default function TasteDna() {
  const qc = useQueryClient();
  const me = useMe();
  const q = useQuery({ queryKey: ["taste-dna"], queryFn: () => api<Dna>("/me/taste-dna") });
  const picks = useQuery({ queryKey: ["taste-dna-picks"], queryFn: () => api<{ items: RecItem[]; ready: boolean }>("/recs/taste-dna"), enabled: !!q.data?.ready });
  const [refine, setRefine] = useState(false);
  const [shareMsg, setShareMsg] = useState<string | null>(null);
  if (q.isLoading) return <div className="mx-auto h-96 max-w-[1400px] animate-pulse px-4 pt-20 md:px-10" />;
  if (q.isError || !q.data)
    return <PageMessage title="Your Taste DNA could not be loaded">Something went wrong. <button className="underline" onClick={() => q.refetch()}>Try again</button></PageMessage>;
  const d = q.data, by = Object.fromEntries(d.traits.map((t) => [t.key, t])) as Record<string, Trait>;
  const label = (k: string) => by[k]?.label.toLowerCase() ?? k;
  const share = async () => {
    try {
      const blob = await tasteCardPng({ name: me.data?.display_name ?? "", traits: d.traits, personality: d.personality, genres: d.top_genres });
      const file = new File([blob], "my-taste-dna.png", { type: "image/png" });
      if (navigator.canShare?.({ files: [file] })) { await navigator.share({ files: [file], title: "My Taste DNA on FlickRaven" }); setShareMsg("Shared."); return; }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "my-taste-dna.png"; a.click(); URL.revokeObjectURL(url);
      setShareMsg("Downloaded. Nothing is shared until you post it yourself.");
    } catch { setShareMsg("Could not create the card. Try again."); }
  };
  const setOverride = async (key: string, v: "more" | "less" | null) => {
    await send("PUT", "/me/taste-dna/overrides", { overrides: { [key]: v } });
    for (const k of ["taste-dna", "taste-dna-picks"]) qc.invalidateQueries({ queryKey: [k] });
  };
  return (
    <div className="mx-auto max-w-[1400px] px-4 pb-24 pt-20 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Your Taste DNA</h1>
      <p className="mt-1 text-sm text-muted">Discover what makes your movie taste unique.</p>
      {!d.ready ? (
        <div className="mt-8 max-w-xl rounded-xl border border-white/10 bg-surface p-6">
          <h2 className="font-display text-lg font-bold">Not enough to go on yet</h2>
          <p className="mt-2 text-sm text-white/80">
            Taste DNA reads the stories behind the titles you rate, like and mark watched. You have {d.titles_used} so far; it starts at 3.
            After rating, you can also tag what you enjoyed.
          </p>
          <Link to="/discover" className="mt-4 inline-block rounded-md bg-accent px-4 py-2 text-sm font-semibold hover:bg-accent-hover">Find something to rate</Link>
        </div>
      ) : (
        <>
          <div className="mt-8 grid gap-8 lg:grid-cols-[1.2fr_1fr]">
            <section aria-label="Taste radar" className="rounded-xl border border-white/10 bg-surface p-5">
              <Radar points={d.radar.map((k) => ({ key: k, label: by[k].label, you: by[k].you, catalog: by[k].catalog }))} />
              <p className="mt-2 text-center text-xs text-muted"><span className="text-accent-hover">Red</span>: you. <span>Dashed</span>: the average title in the catalog.</p>
            </section>
            <div className="space-y-6">
              <section className="rounded-xl border border-white/10 bg-surface p-5" aria-label="Your Cinematic Personality">
                <h2 className="font-display text-lg font-bold">Your Cinematic Personality</h2>
                <p className="mt-2 text-sm leading-relaxed text-white/85">
                  {d.personality ?? `We need at least 5 titles you enjoyed to describe you honestly. You have ${d.titles_used}.`}
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  <button onClick={() => setRefine((r) => !r)} className="rounded-md bg-accent px-4 py-2 text-sm font-semibold hover:bg-accent-hover">Refine My Taste</button>
                  <button onClick={share} className="rounded-md border border-white/25 px-4 py-2 text-sm hover:bg-white/10">Download my Taste DNA card</button>
                </div>
                {shareMsg && <p role="status" className="mt-2 text-xs text-muted">{shareMsg}</p>}
              </section>
              <section className="rounded-xl border border-white/10 bg-surface p-5">
                <h2 className="font-display text-lg font-bold">Top preferences</h2>
                {d.preferred.length ? (
                  <ul className="mt-3 space-y-3">
                    {d.preferred.slice(0, 5).map((k) => (
                      <li key={k}>
                        <div className="flex justify-between text-sm"><span>{by[k].label}</span><span className="text-muted">{by[k].you}</span></div>
                        <div className="mt-1 h-2 rounded-full bg-white/10"><div className="h-2 rounded-full bg-accent" style={{ width: `${by[k].you}%` }} /></div>
                        <p className="mt-0.5 text-[11px] text-muted">From {by[k].override === "more" ? "your setting" : `${by[k].evidence} of your titles`}; the catalog average is {by[k].catalog}.</p>
                      </li>
                    ))}
                  </ul>
                ) : <p className="mt-2 text-sm text-muted">No trait stands out from the catalog average yet. Rate a few more titles, or tag what you enjoyed.</p>}
              </section>
            </div>
          </div>

          <div className="mt-8 grid gap-6 md:grid-cols-3">
            <Card title="Storytelling">
              <Line k="Pacing" v={d.pacing} /><Line k="Plot complexity" v={d.complexity} />
              {!!d.avoided.length && <Line k="You tend to avoid" v={d.avoided.map(label).join(", ")} />}
              {!!d.rising.length && <Line k={`Rising in the last 30 days`} v={d.rising.map(label).join(", ")} />}
            </Card>
            <Card title="Where your favourites come from">
              <Line k="Genres" v={d.top_genres.join(", ")} /><Line k="Languages" v={d.top_languages.join(", ")} /><Line k="Countries" v={d.top_countries.join(", ")} />
            </Card>
            <Card title="How this is built">
              <p className="text-xs leading-relaxed text-muted">
                Traits come from our own keyword rules over TMDB keywords and genres (TMDB has no pacing or tone data), and from the tags
                you and other viewers add after rating. They are an estimate, not verified facts. Based on {d.titles_used} of your titles and {d.titles_tagged} tagged.
                Titles with too few keywords have no trait values rather than a guess.
              </p>
            </Card>
          </div>

          {refine && (
            <section className="mt-8 rounded-xl border border-white/10 bg-surface p-5" aria-label="Refine My Taste">
              <h2 className="font-display text-lg font-bold">Refine My Taste</h2>
              <p className="mt-1 text-sm text-muted">Correct what we got wrong. “More” and “Less” override what your activity says; “Auto” goes back to it.</p>
              <ul className="mt-4 grid gap-x-8 gap-y-3 md:grid-cols-2">
                {d.traits.filter((t) => t.key !== "dialogue" || t.evidence > 0).map((t) => (
                  <li key={t.key} className="flex items-center justify-between gap-3 text-sm">
                    <span>{t.label}</span>
                    <span className="flex overflow-hidden rounded-md border border-white/20" role="group" aria-label={t.label}>
                      {([["less", "Less"], [null, "Auto"], ["more", "More"]] as const).map(([v, l]) => (
                        <button key={l} aria-pressed={t.override === v} onClick={() => setOverride(t.key, v)}
                          className={`px-3 py-1 ${t.override === v ? "bg-white text-black" : "hover:bg-white/10"}`}>{l}</button>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="-mx-4 mt-12 md:-mx-10">
            {picks.data?.items.length ? <Rail title="Picked for your Taste DNA" subtitle="From your recommendations, ordered by how well their storytelling fits you. Separate from your Match %." items={picks.data.items} source="taste_dna" />
              : picks.isFetched && <p className="px-4 text-sm text-muted md:px-10">No title in your recommendations clearly fits your traits yet.</p>}
          </div>
        </>
      )}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-xl border border-white/10 bg-surface p-5"><h2 className="font-display text-base font-bold">{title}</h2><div className="mt-2 space-y-1.5">{children}</div></section>;
}
function Line({ k, v }: { k: string; v?: string | null }) {
  return v ? <p className="text-sm"><span className="text-muted">{k}: </span>{v}</p> : null;
}
