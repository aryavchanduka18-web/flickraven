import ImdbScore from "../components/movie/ImdbScore";
import TypeBadge from "../components/movie/TypeBadge";
import WhereToWatch from "../components/movie/WhereToWatch";
import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useFeedback, useFranchise, useLogEvent, useMovie, useSimilar } from "../api/hooks";
import ConfidenceCard from "../components/explain/ConfidenceCard";
import WhyThis from "../components/explain/WhyThis";
import ActionButtons from "../components/feedback/ActionButtons";
import RatingDistribution from "../components/feedback/RatingDistribution";
import RatingStars from "../components/feedback/RatingStars";
import TasteTags from "../components/taste/TasteTags";
import TasteReason from "../components/taste/TasteReason";
import { PageMessage } from "../components/Loading";
import Rail from "../components/rail/Rail";
import { languageName, runtime } from "../lib/format";
import { tmdbImage } from "../lib/tmdb";

export default function Movie() {
  const id = Number(useParams().id);
  const loc = useLocation() as { state?: { source?: string; position?: number } };
  const movie = useMovie(id);
  const similar = useSimilar(id);
  const fb = useFeedback(id, loc.state?.source ?? "movie_page");
  const logEvent = useLogEvent();
  useEffect(() => {
    window.scrollTo(0, 0);
    logEvent("detail_view", id, loc.state?.source ?? "direct", loc.state?.position);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (movie.isLoading) return <div className="h-[70vh] animate-pulse bg-surface" />;
  if (movie.isError && movie.error instanceof ApiError && movie.error.status === 404) return <PageMessage title="Film not found" />;
  if (movie.isError || !movie.data)
    return (
      <PageMessage title="This film could not be loaded">
        Something went wrong on our side.{" "}
        <button onClick={() => movie.refetch()} className="text-white underline underline-offset-4">Try again</button>
      </PageMessage>
    );
  const m = movie.data;
  const tint = m.dominant_color ?? "#141414";
  const facts: [string, string | null | undefined][] = [
    [m.title_type && m.title_type !== "movie" ? "First aired" : "Release date", m.release_date], ["Status", m.series_status],
    ["Runtime", runtime(m.runtime)], ["Language", languageName(m.language)],
    ["Country", m.countries?.join(", ")], ["Certification", m.certification], ["Studios", m.studios?.slice(0, 3).join(", ")],
  ];
  return (
    <div>
      <section className="relative min-h-[70vh] overflow-hidden">
        <img src={tmdbImage(m.backdrop ?? m.poster, "w1280")} alt="" className="absolute inset-0 h-full w-full object-cover" />
        <div className="absolute inset-0" style={{ background: `linear-gradient(90deg, ${tint}dd 0%, ${tint}66 40%, transparent 75%)` }} />
        <div className="absolute inset-0 bg-gradient-to-t from-bg via-bg/40 to-black/40" />
        <div className="relative z-10 mx-auto flex min-h-[70vh] max-w-[1800px] items-end gap-8 px-4 pb-12 pt-28 md:px-10">
          {m.poster && <img src={tmdbImage(m.poster, "w342")} alt={`${m.title} poster`} className="hidden w-52 rounded-md shadow-2xl md:block" />}
          <div className="max-w-3xl">
            {m.logo ? <img src={tmdbImage(m.logo, "w500")} alt={m.title} className="mb-4 max-h-28 max-w-[80%] object-contain object-left" />
              : <h1 className="font-display text-4xl font-extrabold md:text-5xl">{m.title}</h1>}
            {m.tagline && <p className="mt-2 text-lg italic text-white/75">{m.tagline}</p>}
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-white/85">
              {m.match_pct != null && <span className="text-2xl font-extrabold text-accent">{m.match_pct}% match</span>}
              <TypeBadge type={m.title_type} />
              <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
              {m.year && <span>{m.year}</span>}
              {m.title_type && m.title_type !== "movie" && m.seasons != null && (
                <span>{m.seasons} season{m.seasons === 1 ? "" : "s"}{m.episodes ? ` · ${m.episodes} episodes` : ""}</span>
              )}
              {m.runtime && <span>{runtime(m.runtime)}{m.title_type && m.title_type !== "movie" ? " per episode" : ""}</span>}
              {m.certification && <span className="rounded border border-white/40 px-1.5 text-xs">{m.certification}</span>}
              <span>{m.genres.join(" · ")}</span>
            </div>
            <div className="mt-6 flex flex-wrap items-center gap-6">
              <ActionButtons movieId={m.id} state={m.user_state} source="movie_page" size="md" showWatched />
              <RatingStars value={m.user_state.rating} onChange={(r) => fb.mutate({ kind: "rate", rating: r })} />
            </div>
            <div className="mt-3"><TasteTags movieId={m.id} rated={m.user_state.rating != null || m.user_state.reaction !== 0 || m.user_state.watched} /></div>
          </div>
        </div>
      </section>

      <div className="mx-auto grid max-w-[1800px] gap-10 px-4 md:grid-cols-[2fr_1fr] md:px-10">
        <div className="min-w-0 space-y-8">
          {m.overview && <p className="max-w-3xl text-base leading-relaxed text-white/90">{m.overview}</p>}
          <WhereToWatch watch={m.watch} title={m.title} />
          {m.in_profile && (
            <p className="rounded-lg border border-white/10 bg-surface px-4 py-3 text-sm text-white/85">
              {m.user_state.rating != null ? `You rated this ${m.user_state.rating}/10. ` : m.user_state.reaction > 0 ? "You liked this. " : "You marked this as not for you. "}
              It is part of your taste profile, so FlickRaven does not recommend it back to you; it shapes your other recommendations.
            </p>
          )}
          <WhyThis reasons={m.why} />
          <TasteReason movieId={m.id} />
          <ConfidenceCard c={m.confidence} />
          <Credits title="Directed by" people={m.directors} />
          <Credits title={m.title_type && m.title_type !== "movie" ? "Created by" : "Written by"} people={m.writers} />
          <div>
            <h3 className="mb-3 text-sm font-semibold text-muted">Cast</h3>
            <div className="no-scrollbar flex gap-4 overflow-x-auto pb-2">
              {m.cast.map((c) => (
                <Link key={c.id} to={`/person/${c.id}`} className="group w-24 shrink-0 text-center" aria-label={`${c.name}: view filmography`}>
                  <div className="relative mx-auto h-24 w-24 overflow-hidden rounded-full bg-surface-2 ring-1 ring-white/10 transition group-hover:ring-white/40">
                    {c.profile_path && <img src={tmdbImage(c.profile_path, "w300")} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105" />}
                    <span className="absolute inset-0 grid place-items-center bg-black/55 px-2 text-[10px] font-medium leading-tight opacity-0 transition-opacity duration-150 group-hover:opacity-100">View filmography</span>
                  </div>
                  <div className="mt-2 text-xs font-medium leading-tight group-hover:underline">{c.name}</div>
                  {c.character && <div className="text-[11px] leading-tight text-muted">{c.character}</div>}
                </Link>
              ))}
            </div>
          </div>
          {m.keywords.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {m.keywords.slice(0, 20).map((k) => (
                <Link key={k} to={`/search?q=${encodeURIComponent(k)}`} className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/75 hover:border-white/40">{k}</Link>
              ))}
            </div>
          )}
        </div>
        <aside className="min-w-0 space-y-8">
          <div>
            <h3 className="mb-3 text-sm font-semibold text-muted">{m.title_type && m.title_type !== "movie" ? "FlickRaven ratings" : "Community ratings (MovieLens)"}</h3>
            <RatingDistribution hist={m.rating_hist} />
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            {facts.filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          {m.awards.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-muted">Awards</h3>
              <ul className="space-y-1 text-sm">
                {m.awards.slice(0, 12).map((a, i) => (
                  <li key={i}><span className={a.result === "won" ? "text-white" : "text-white/70"}>{a.result === "won" ? "Won" : "Nominated"}</span>: {a.award}{a.category ? `, ${a.category}` : ""}{a.year ? ` (${a.year})` : ""}</li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-muted">Source: Wikidata</p>
            </div>
          )}
        </aside>
      </div>
      <FranchiseRails id={m.id} />
      {similar.data && <div className="mt-12"><Rail title="More Like This" subtitle="Films most similar to this one" items={similar.data.items} source="more_like_this" personal={false} /></div>}
    </div>
  );
}

function Credits({ title, people }: { title: string; people: { id: number; name: string }[] }) {
  if (!people.length) return null;
  return (
    <div className="text-sm">
      <span className="text-muted">{title} </span>
      {people.map((p, i) => (
        <span key={p.id}>
          <Link to={`/person/${p.id}`} className="hover:underline" title="View filmography">{p.name}</Link>
          {i < people.length - 1 ? ", " : ""}
        </span>
      ))}
    </div>
  );
}
/** "More from <collection>" (all parts in release order), studio universes such as Marvel, or fallbacks. */
function FranchiseRails({ id }: { id: number }) {
  const { data } = useFranchise(id);
  if (!data?.sections.length) return null;
  return (
    <div className="mt-12 space-y-4">
      {data.sections.map((s) => {
        const items = s.kind === "collection" ? s.items.filter((i) => i.movie.id !== id) : s.items;
        const at = s.items.findIndex((i) => i.movie.id === id);
        const subtitle = s.kind === "collection" ? `Part ${at + 1} of ${s.items.length} · in release order`
          : s.kind === "universe" ? "In release order" : "Newest first";
        return <Rail key={s.key} title={s.title} subtitle={subtitle} items={items} source={`franchise_${s.kind}`} personal={false} />;
      })}
    </div>
  );
}
