import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useCollections, useHome, useKindRail, useMe, useSetMode } from "../api/hooks";
import type { Mode } from "../api/types";
import DiscoveryModeControl from "../components/discovery/DiscoveryModeControl";
import TonightPanel from "../components/discovery/TonightPanel";
import TunePanel from "../components/discovery/TunePanel";
import Hero from "../components/hero/Hero";
import { PageMessage, RailSkeleton } from "../components/Loading";
import Rail from "../components/rail/Rail";

const PERSONAL = new Set(["top_picks", "based_on_ratings", "people_like_you", "different"]);

export default function Home() {
  const me = useMe();
  const [mode, setMode] = useState<Mode | undefined>(undefined);
  const home = useHome(mode);
  const saveMode = useSetMode();
  const [tonight, setTonight] = useState(false);
  const [tune, setTune] = useState(false);
  const collections = useCollections();
  const series = useKindRail("series");
  const anime = useKindRail("anime");
  const showAnime = !!me.data?.show_anime;

  if (me.data && !me.data.onboarded) return <Navigate to="/onboarding" replace />;
  if (home.isError) return <PageMessage title="Recommendations are not ready">{(home.error as Error).message}</PageMessage>;
  const active: Mode = mode ?? home.data?.mode ?? me.data?.discovery_mode ?? "balanced";
  return (
    <div>
      {home.data ? <Hero items={home.data.hero} /> : <div className="h-[78vh] animate-pulse bg-surface" />}
      <div className="relative z-10 -mt-8 space-y-2">
        <div className="flex flex-wrap items-center gap-4 px-4 pb-4 md:px-10">
          <DiscoveryModeControl
            value={active}
            onChange={(m) => {
              setMode(m);
              saveMode.mutate(m);
            }}
          />
          <button onClick={() => setTune((t) => !t)} aria-expanded={tune}
            className="rounded-full border border-white/20 px-4 py-2 text-sm hover:border-white/50">
            Tune
          </button>
          <Link to="/discover" className="text-sm text-muted hover:text-white">Browse everything →</Link>
        </div>
        {tune && (
          <div className="px-4 pb-6 md:px-10">
            <TunePanel onClose={() => setTune(false)} />
          </div>
        )}
        <div className="px-4 pb-4 md:px-10">
          {tonight ? <TonightPanel /> : (
            <button onClick={() => setTonight(true)}
              className="group flex w-full items-center justify-between gap-4 rounded-2xl border border-white/10 bg-gradient-to-r from-accent/25 via-surface to-surface px-5 py-5 text-left transition-colors hover:border-white/30 md:px-7">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">For Tonight</p>
                <p className="mt-1 font-display text-xl font-bold md:text-2xl">Not sure what to watch? Tell us your mood.</p>
                <p className="mt-1 text-sm text-muted">Mood, time and language in, the best matches out, with the reasons.</p>
              </div>
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white text-black transition-transform group-hover:translate-x-1">→</span>
            </button>
          )}
        </div>
        {home.isLoading && [0, 1, 2].map((i) => <RailSkeleton key={i} />)}
        <div className="space-y-6">
          {home.data?.rails.map((r) => (
            <Rail key={r.key} title={r.title} subtitle={r.subtitle ?? undefined} items={r.items} source={`rail:${r.key.split(":")[0]}`}
              personal={PERSONAL.has(r.key) || r.items.some((i) => i.match_pct != null)} />
          ))}
          {home.data && series.data && series.data.items.length > 0 && (
            <Rail title="Series for you" subtitle="From what you like and what is popular. Series have no ratings here, so there is no match score."
              items={series.data.items} source="rail:series" personal={false} />
          )}
          {home.data && showAnime && anime.data && anime.data.items.length > 0 && (
            <Rail title="Anime for you" subtitle="From what you like and what is popular."
              items={anime.data.items} source="rail:anime" personal={false} />
          )}
          {home.data && collections.data?.collections.map((c) => (
            <Rail key={c.key} title={c.title} subtitle={`${c.count.toLocaleString()} films`} items={c.items}
              source={`collection:${c.key}`} personal={c.items.some((i) => i.match_pct != null)} />
          ))}
        </div>
      </div>
    </div>
  );
}