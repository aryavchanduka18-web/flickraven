import { Link } from "react-router-dom";
import type { RecItem } from "../../api/types";
import { tmdbImage } from "../../lib/tmdb";
import ActionButtons from "../feedback/ActionButtons";
import ImdbScore from "../movie/ImdbScore";
import TypeBadge from "../movie/TypeBadge";

/** A compact portrait card for vertical grids: 2:3 poster, title, year, IMDb, Match % (only when the API sent
 *  one), up to two short reasons and the My List / like / dislike buttons. */
export default function PosterCard({ item, source, position }: { item: RecItem; source: string; position: number }) {
  const m = item.movie;
  const poster = tmdbImage(m.poster, "w342");
  return (
    <div className="group flex flex-col">
      <Link to={`/movie/${m.id}`} state={{ source, position }} className="block overflow-hidden rounded-md bg-surface-2"
        aria-label={`${m.title}${m.year ? ` (${m.year})` : ""}`}>
        <div className="relative aspect-[2/3]" style={m.dominant_color ? { backgroundColor: m.dominant_color } : undefined}>
          {poster ? (
            <img src={poster} alt="" loading="lazy" decoding="async"
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
          ) : (
            <div className="grid h-full place-items-center p-3 text-center font-display text-lg font-bold">{m.title}</div>
          )}
        </div>
      </Link>
      <div className="mt-2 flex-1">
        <Link to={`/movie/${m.id}`} state={{ source, position }} className="line-clamp-2 font-semibold leading-snug hover:underline">
          {m.title}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-muted">
          {m.year && <span>{m.year}</span>}
          <TypeBadge type={m.title_type} />
          <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
        </div>
        {item.match_pct != null && <p className="mt-1 text-sm font-bold text-accent">{item.match_pct}% match</p>}
        {item.reasons.length > 0 && (
          <ul className="mt-1.5 space-y-0.5 text-[13px] leading-snug text-white/75">
            {item.reasons.slice(0, 2).map((r) => <li key={r.code}>{r.text}</li>)}
          </ul>
        )}
      </div>
      <div className="mt-2"><ActionButtons movieId={m.id} state={item.user_state} source={source} /></div>
    </div>
  );
}

/** Four columns on wide screens, three on medium, two on phones. */
export function PosterGrid({ items, source }: { items: RecItem[]; source: string }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-3 xl:grid-cols-4">
      {items.map((it, i) => <PosterCard key={it.movie.id} item={it} source={source} position={i} />)}
    </div>
  );
}

/** The More Like This tile: a portrait poster with the Match % badge on it (only where the API sent one), and the
 *  title, rating and year underneath. One real reason under the title when there is one. */
export function SimilarTile({ item, source, position }: { item: RecItem; source: string; position: number }) {
  const m = item.movie;
  const poster = tmdbImage(m.poster, "w342");
  return (
    <Link to={`/movie/${m.id}`} state={{ source, position }} className="group block" aria-label={`${m.title}${m.year ? ` (${m.year})` : ""}`}>
      <div className="relative aspect-[2/3] overflow-hidden rounded-2xl bg-surface-2 ring-1 ring-white/10 transition duration-500 [transition-timing-function:var(--ease-out)] group-hover:-translate-y-1 group-hover:ring-white/30"
        style={m.dominant_color ? { backgroundColor: m.dominant_color } : undefined}>
        {poster ? (
          <img src={poster} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]" />
        ) : (
          <div className="grid h-full place-items-center p-3 text-center font-display text-lg font-bold">{m.title}</div>
        )}
        {item.match_pct != null && (
          <span className="glass absolute left-2 top-2 rounded-full px-2.5 py-0.5 text-[11px] font-bold !shadow-none">{item.match_pct}% match</span>
        )}
      </div>
      <h3 className="mt-2 line-clamp-1 text-[15px] font-semibold leading-snug">{m.title}</h3>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[13px] text-muted">
        <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
        {m.year && <span>{m.year}</span>}
        <TypeBadge type={m.title_type} />
      </div>
      {item.reasons[0] && <p className="mt-1 line-clamp-2 text-[12px] leading-snug text-white/60">{item.reasons[0].text}</p>}
    </Link>
  );
}

/** Three tiles per row (two on phones). */
export function SimilarGrid({ items, source }: { items: RecItem[]; source: string }) {
  return (
    <div className="grid max-w-[980px] grid-cols-2 gap-x-5 gap-y-8 sm:grid-cols-3" data-testid="similar-grid">
      {items.map((it, i) => <SimilarTile key={it.movie.id} item={it} source={source} position={i} />)}
    </div>
  );
}
