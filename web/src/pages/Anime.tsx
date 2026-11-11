import { Link } from "react-router-dom";
import { useAnimeRails } from "../api/hooks";
import Rail from "../components/rail/Rail";
import { RailSkeleton } from "../components/Loading";

/** Anime: anime series (TV anime) and anime films (Japanese animated films) only. Live-action never appears here.
 *  Rows come from /recs/anime: series in the engine's anime order, films in the film hybrid order. */
export default function Anime() {
  const q = useAnimeRails();
  const rails = q.data?.rails ?? [];
  return (
    <div className="mx-auto max-w-[1800px] pb-24 pt-20">
      <div className="flex flex-wrap items-end justify-between gap-4 px-4 md:px-10">
        <div>
          <h1 className="font-display text-3xl font-extrabold md:text-4xl">Anime</h1>
          <p className="mt-1 text-sm text-muted">Anime series and anime films only, picked from your taste. Titles you have rated, watched or disliked are left out.</p>
        </div>
        <div className="flex gap-3">
          <Link to="/genres/anime" className="glass-btn rounded-2xl px-4 py-2.5 text-sm font-semibold">Browse all anime</Link>
        </div>
      </div>
      <div className="mt-6 space-y-6">
        {q.isLoading && [0, 1, 2].map((i) => <RailSkeleton key={i} />)}
        {rails.map((x) => <Rail key={x.key} title={x.title} subtitle={x.subtitle} items={x.items} source={`rail:anime_${x.key}`} personal={false} />)}
        {q.isError && <p className="px-4 text-sm text-muted md:px-10">Anime could not load. Try again in a moment.</p>}
        {!q.isLoading && !q.isError && !rails.length && <p className="px-4 text-sm text-muted md:px-10">No anime to recommend yet. Try browsing all anime.</p>}
      </div>
    </div>
  );
}
