import ImdbScore from "../components/movie/ImdbScore";
import TypeBadge from "../components/movie/TypeBadge";
import WhereToWatch from "../components/movie/WhereToWatch";
import { useEffect } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useUI } from "../components/layout/ui";
import { ApiError } from "../api/client";
import { useFeedback, useFranchise, useLogEvent, useMovie, useSimilar } from "../api/hooks";
import ConfidenceCard from "../components/explain/ConfidenceCard";
import WhyThis from "../components/explain/WhyThis";
import RecOutcomeFeedback from "../components/explain/RecOutcomeFeedback";
import ActionButtons from "../components/feedback/ActionButtons";
import RatingDistribution from "../components/feedback/RatingDistribution";
import RatingStars from "../components/feedback/RatingStars";
import TasteTags from "../components/taste/TasteTags";
import TasteReason from "../components/taste/TasteReason";
import { PageMessage } from "../components/Loading";
import Rail from "../components/rail/Rail";
import { SimilarGrid } from "../components/card/PosterCard";
import { languageName, runtime } from "../lib/format";
import { tmdbImage } from "../lib/tmdb";

export default function Movie() {
  const id = Number(useParams().id);
  const loc = useLocation() as { state?: { source?: string; position?: number } };
  const movie = useMovie(id);
  const similar = useSimilar(id, 9);
  const navigate = useNavigate();
  const { openWhy } = useUI();
  // Actions here happen on the film page ("movie_page"); the row that led here is their origin, so it is still credited.
  const origin = loc.state?.source;
  const fb = useFeedback(id, "movie_page", origin);
  const logEvent = useLogEvent();
  const back = () => (loc as { key?: string }).key !== "default" ? navigate(-1) : navigate("/");
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
  const isFilm = !m.title_type || m.title_type === "movie";
  const facts: [string, string | null | undefined][] = [
    [isFilm ? "Release date" : "First aired", m.release_date], ["Status", m.series_status],
    ["Runtime", runtime(m.runtime)], ["Language", languageName(m.language)],
    ["Country", m.countries?.join(", ")], ["Certification", m.certification], ["Studios", m.studios?.slice(0, 3).join(", ")],
  ];
  const goTo = (anchor: string) => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <div>
      {/* Full-bleed header: the title's own backdrop on the right, black fade on the left for the text. */}
      <section data-sb-bleed className="hero-bleed relative isolate min-h-[78vh] overflow-hidden">
        <img src={tmdbImage(m.backdrop ?? m.poster, "w1280")} alt="" className="absolute inset-0 h-full w-full object-cover object-[72%_center] md:object-right" />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,#080808_0%,rgba(8,8,8,0.9)_26%,rgba(8,8,8,0.5)_48%,rgba(8,8,8,0)_74%)]" />
        <div className="absolute inset-0 bg-gradient-to-t from-bg via-bg/10 to-black/40" />
        <div data-sb-slide className="relative z-10 flex min-h-[78vh] flex-col justify-end px-5 pb-10 pt-24 md:pl-[calc(var(--sb)+76px)] md:pr-16">
          <button onClick={back} aria-label="Back" className="glass-btn absolute left-4 top-20 h-11 w-11 rounded-full md:left-[calc(var(--sb)+16px)] md:top-8">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M19 12H5m6-6-6 6 6 6" /></svg>
          </button>
          <div className="max-w-2xl hero-fade-in">
            {m.logo ? <img src={tmdbImage(m.logo, "w500")} alt={m.title} className="mb-4 max-h-28 max-w-[80%] object-contain object-left" />
              : <h1 className="font-display text-5xl font-extrabold leading-[1.02] tracking-tight md:text-7xl">{m.title}</h1>}
            {m.tagline && <p className="mt-2 text-lg italic text-white/70">{m.tagline}</p>}
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-white/85">
              {m.year && <span>{m.year}</span>}
              {m.certification && <span className="rounded border border-white/40 px-1.5 text-xs">{m.certification}</span>}
              {m.runtime && <span>{runtime(m.runtime)}{isFilm ? "" : " per episode"}</span>}
              {!isFilm && m.seasons != null && <span>{m.seasons} season{m.seasons === 1 ? "" : "s"}{m.episodes ? ` · ${m.episodes} episodes` : ""}</span>}
              <span>{m.genres.join(" · ")}</span>
              <TypeBadge type={m.title_type} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {m.match_pct != null && <span className="rounded-lg border border-accent/60 bg-accent/15 px-3 py-1 text-sm font-bold">{m.match_pct}% Match</span>}
              <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
            </div>
            {m.overview && <p className="mt-4 line-clamp-4 max-w-xl text-[15px] leading-relaxed text-white/85">{m.overview}</p>}
            <div className="mt-6 flex flex-wrap items-center gap-3">
              {m.watch && (
                <button type="button" onClick={() => goTo("where-to-watch")} className="glass-btn solid rounded-2xl px-6 py-3 text-[15px] font-semibold">Where to watch</button>
              )}
              <button type="button" aria-pressed={m.user_state.in_list}
                onClick={() => fb.mutate({ kind: "list", on: !m.user_state.in_list })}
                className={`glass-btn rounded-2xl px-5 py-3 text-[15px] font-semibold ${m.user_state.in_list ? "on" : ""}`}>
                {m.user_state.in_list ? "In your list" : "+ Add to list"}
              </button>
              {m.match_pct != null && (
                <button type="button" onClick={() => openWhy(m.id)} className="glass-btn rounded-2xl px-5 py-3 text-[15px] font-semibold">Why this?</button>
              )}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-6">
              <ActionButtons movieId={m.id} state={m.user_state} source="movie_page" origin={origin} size="md" showWatched />
              <RatingStars value={m.user_state.rating} onChange={(r) => fb.mutate({ kind: "rate", rating: r })} />
            </div>
            <div className="mt-3"><TasteTags movieId={m.id} rated={m.user_state.rating != null || m.user_state.reaction !== 0 || m.user_state.watched} /></div>
            {m.user_state.rating != null && <div className="mt-3"><RecOutcomeFeedback movieId={m.id} /></div>}
          </div>
          <nav className="mt-8 flex gap-1 border-b border-white/10 text-sm" aria-label="On this page">
            {[["Overview", "overview"], ["More like this", "more-like-this"], ["Cast & crew", "cast"]].map(([l, a], i) => (
              <button key={a} onClick={() => goTo(a)} className={`relative px-4 py-3 font-medium transition-colors ${i === 0 ? "text-white" : "text-white/60 hover:text-white"}`}>
                {l}
                {i === 0 && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />}
              </button>
            ))}
          </nav>
        </div>
      </section>

      <div className="mx-auto mt-8 grid max-w-[1800px] gap-10 px-4 md:grid-cols-[2fr_1fr] md:px-10">
        <div className="min-w-0 space-y-8">
          <span id="overview" className="block scroll-mt-24" />
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
          <div id="cast" className="scroll-mt-24">
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
      <section id="more-like-this" className="mx-auto mt-12 max-w-[1800px] scroll-mt-24 px-4 md:px-10">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="font-display text-xl font-bold md:text-2xl">More Like This</h2>
            <p className="text-sm text-muted">{m.title_type && m.title_type !== "movie" ? "Series" : "Films"} with a similar story, themes or people</p>
          </div>
          {similar.data && similar.data.total > similar.data.items.length && (
            <Link to={`/movie/${id}/similar`} className="text-sm text-white/80 underline underline-offset-4 hover:text-white">
              View all {similar.data.total} similar titles
            </Link>
          )}
        </div>
        {similar.data && similar.data.items.length > 0 ? (
          <SimilarGrid items={similar.data.items} source="more_like_this" />
        ) : (
          // Never leave the "More like this" tab pointing at nothing: say what happened.
          <p className="rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-6 text-sm text-muted" role="status">
            {similar.isError ? "Similar titles could not be loaded. Try again in a moment."
              : similar.isLoading ? "Finding similar titles…"
              : "No similar titles to show for this one yet."}
          </p>
        )}
      </section>
      {similar.data?.cross_kind && similar.data.cross_kind.items.length > 0 && (
        <section id="cross-kind" className="mx-auto mt-10 max-w-[1800px] px-4 md:px-10">
          <div className="mb-4">
            <h2 className="font-display text-xl font-bold md:text-2xl">{similar.data.cross_kind.title}</h2>
            <p className="text-sm text-muted">A different kind of show with a similar feel, picked with Google Gemini.</p>
          </div>
          <SimilarGrid items={similar.data.cross_kind.items} source="more_like_this" />
        </section>
      )}
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
