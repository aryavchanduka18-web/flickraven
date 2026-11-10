import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import { Link, Navigate } from "react-router-dom";
import { useCollections, useHome, useKindRail, useMe, useSeriesRails, useSetMode } from "../api/hooks";
import type { Mode } from "../api/types";
import DiscoveryModeControl from "../components/discovery/DiscoveryModeControl";
import TonightPanel from "../components/discovery/TonightPanel";
import TunePanel from "../components/discovery/TunePanel";
import Hero from "../components/hero/Hero";
import { PageMessage, RailSkeleton } from "../components/Loading";
import Rail from "../components/rail/Rail";
import { themedRowLimit } from "../lib/seriesRows";

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
  // The personal picks need the recommender, which can take a while right after the server wakes up. Popular films
  // come straight from the database, so they show at once while the picks are being prepared.
  const quick = useQuery({
    queryKey: ["home-quick"],
    queryFn: () => api<{ items: RecItem[] }>("/movies?sort=popular&page=1"),
    enabled: !home.data,
    staleTime: 5 * 60_000,
  });
  const anime = useKindRail("anime");
  const showAnimeRow = !!anime.data && anime.data.items.length > 0;
  const themed = useSeriesRails();

  if (me.data && !me.data.onboarded) return <Navigate to="/onboarding" replace />;
  if (home.isError) return <PageMessage title="Recommendations are not ready">{(home.error as Error).message}</PageMessage>;
  const active: Mode = mode ?? home.data?.mode ?? me.data?.discovery_mode ?? "balanced";
  return (
    <div>
      {home.data ? <Hero items={home.data.hero} /> : (
        <div className="flex h-[42vh] min-h-[280px] items-end bg-gradient-to-b from-surface to-bg px-4 pb-10 md:px-10">
          <div>
            <p className="font-display text-3xl font-extrabold">Getting your picks ready…</p>
            <p className="mt-2 max-w-xl text-sm text-muted">The site was asleep and is waking up. This can take up to half a minute the first time; popular films are below while you wait.</p>
          </div>
        </div>
      )}
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
        {home.isLoading && quick.data && quick.data.items.length > 0 && (
          <Rail title="Popular right now" subtitle="Your personal picks are loading." items={quick.data.items.slice(0, 20)} source="rail:quick" personal={false} />
        )}
        {home.isLoading && !quick.data && [0, 1, 2].map((i) => <RailSkeleton key={i} />)}
        <div className="space-y-6">
          {home.data?.rails.map((r, i) => (
            <Fragment key={r.key}>
              <Rail title={r.title} subtitle={r.subtitle ?? undefined} items={r.items} source={`rail:${r.key.split(":")[0]}`}
                personal={PERSONAL.has(r.key) || r.items.some((x) => x.match_pct != null)} />
              {/* Series and anime come right after the first two film rails, so they are seen without long scrolling. */}
              {i === 1 && series.data && series.data.items.length > 0 && (
                <Rail title="Series for you" subtitle="From what you like and what is popular. Series have no ratings here, so there is no match score."
                  items={series.data.items} source="rail:series" personal={false} />
              )}
              {i === 1 && themed.data?.rails.filter((x) => x.key === "because").map((x) => (
                <Rail key={x.key} title={x.title} subtitle={x.subtitle} items={x.items} source="rail:series_because" personal={false} />
              ))}
              {i === 1 && themed.data?.rails.filter((x) => x.key !== "mix" && x.key !== "because").slice(0, themedRowLimit(themed.data.engaged_series ?? 0)).map((x) => (
                <Rail key={x.key} title={x.title} subtitle={x.subtitle} items={x.items} source={`rail:series_${x.key}`} personal={false} />
              ))}
              {i === 3 && themed.data?.rails.filter((x) => x.key === "mix").map((x) => (
                <Rail key={x.key} title={x.title} subtitle={x.subtitle} items={x.items} source="rail:series_mix" personal={false} />
              ))}
              {i === 1 && showAnimeRow && (
                <Rail title="Anime for you" subtitle="From what you like and what is popular."
                  items={anime.data!.items} source="rail:anime" personal={false} />
              )}
            </Fragment>
          ))}
          {home.data && collections.data?.collections.map((c) => (
            <Rail key={c.key} title={c.title} subtitle={`${c.count.toLocaleString()} films`} items={c.items}
              source={`collection:${c.key}`} personal={c.items.some((i) => i.match_pct != null)} />
          ))}
        </div>
      </div>
    </div>
  );
}