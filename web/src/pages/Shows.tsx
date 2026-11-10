import { Link } from "react-router-dom";
import { useKindRail, useSeriesRails } from "../api/hooks";
import Rail from "../components/rail/Rail";
import { RailSkeleton } from "../components/Loading";

/** Shows: TV series and anime TV only, ranked by their own series pipeline (never the film list filtered).
 */
export default function Shows() {
  const picks = useKindRail("series");
  const anime = useKindRail("anime");
  const themed = useSeriesRails();
  const rails = themed.data?.rails.filter((x) => x.key !== "mix") ?? [];
  const loading = picks.isLoading || themed.isLoading;
  return (
    <div className="mx-auto max-w-[1800px] pb-24 pt-20">
      <div className="flex flex-wrap items-end justify-between gap-4 px-4 md:px-10">
        <div>
          <h1 className="font-display text-3xl font-extrabold md:text-4xl">Shows</h1>
          <p className="mt-1 text-sm text-muted">TV series and anime series only. Series have no ratings here, so rows are ranked by how close they are to your taste, plus popularity.</p>
        </div>
        <div className="flex gap-3">
          <Link to="/discover?type=show" className="glass-btn rounded-2xl px-4 py-2.5 text-sm font-semibold">Filter all shows</Link>
          <Link to="/series-fit" className="glass-btn rounded-2xl px-4 py-2.5 text-sm font-semibold">Fits your time</Link>
        </div>
      </div>
      <div className="mt-6 space-y-6">
        {loading && [0, 1, 2].map((i) => <RailSkeleton key={i} />)}
        {picks.data && picks.data.items.length > 0 && (
          <Rail title="Series picked for you" subtitle="From what you like and what is popular." items={picks.data.items} source="rail:series" personal={false} />
        )}
        {rails.map((x) => <Rail key={x.key} title={x.title} subtitle={x.subtitle} items={x.items} source={`rail:series_${x.key}`} personal={false} />)}
        {anime.data && anime.data.items.length > 0 && (
          <Rail title="Anime series for you" subtitle="From what you like and what is popular." items={anime.data.items} source="rail:anime" personal={false} />
        )}
        {!loading && !picks.data?.items.length && !rails.length && <p className="px-4 text-sm text-muted md:px-10">No shows to recommend yet. Try the filters.</p>}
      </div>
    </div>
  );
}
