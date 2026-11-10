import ImdbScore from "../components/movie/ImdbScore";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import { PageMessage } from "../components/Loading";
import { tmdbImage } from "../lib/tmdb";

type Department = "Acting" | "Directing" | "Writing";
type PersonInfo = {
  id: number; name: string; profile_path: string | null; known_for: Department | null; film_count: number;
  departments: Partial<Record<Department, number>>;
  known_for_titles: { id: number; title: string; year: number | null; character: string | null }[];
};
type Credit = RecItem & { roles: Department[]; character: string | null };

const TABS: ("All" | Department)[] = ["All", "Acting", "Directing", "Writing"];

export default function Person() {
  const id = Number(useParams().id);
  const [tab, setTab] = useState<(typeof TABS)[number]>("All");
  const info = useQuery({ queryKey: ["person", id], queryFn: () => api<PersonInfo>(`/people/${id}`) });
  const films = useQuery({ queryKey: ["person-movies", id], queryFn: () => api<{ items: Credit[]; recommended: Credit[] }>(`/people/${id}/movies`) });
  useEffect(() => {
    window.scrollTo(0, 0);
    setTab("All");
  }, [id]);

  if (info.isLoading) return <div className="h-[50vh] animate-pulse bg-surface" />;
  if (info.isError || !info.data) return <PageMessage title="Person not found" />;
  const p = info.data;
  const tabs = TABS.filter((t) => t === "All" || p.departments[t]);
  const shown = (films.data?.items ?? []).filter((f) => tab === "All" || f.roles.includes(tab));
  const roles = (Object.keys(p.departments) as Department[]).sort((a, b) => (p.departments[b] ?? 0) - (p.departments[a] ?? 0));

  return (
    <div className="mx-auto max-w-[1800px] px-4 pb-24 pt-20 md:px-10">
      <header className="flex flex-col items-center gap-6 text-center md:flex-row md:items-end md:text-left">
        <div className="h-48 w-48 shrink-0 overflow-hidden rounded-full bg-surface-2 ring-1 ring-white/10 md:h-56 md:w-56">
          {p.profile_path && <img src={tmdbImage(p.profile_path, "w342")} alt={p.name} className="h-full w-full object-cover" />}
        </div>
        <div>
          <h1 className="font-display text-4xl font-extrabold md:text-5xl">{p.name}</h1>
          <p className="mt-2 text-white/80">{roles.join(" · ")}</p>
          <p className="mt-1 text-sm text-muted">{p.film_count} FlickRaven {p.film_count === 1 ? "film" : "films"}</p>
          {p.known_for_titles.length > 0 && (
            <p className="mt-3 max-w-2xl text-sm text-white/75">
              Known for{" "}
              {p.known_for_titles.map((t, i) => (
                <span key={t.id}>
                  <Link to={`/movie/${t.id}`} className="text-white hover:underline">{t.title}</Link>
                  {t.character ? <span className="text-muted"> as {t.character}</span> : null}
                  {i < p.known_for_titles.length - 1 ? ", " : ""}
                </span>
              ))}
            </p>
          )}
        </div>
      </header>

      {films.data && films.data.recommended.length > 0 && (
        <section className="mt-12" aria-label="Recommended for you">
          <h2 className="font-display text-xl font-bold">Recommended for you</h2>
          <p className="text-xs text-muted">Their films your recommender scores highest, among the ones you have not rated</p>
          <div className="no-scrollbar mt-3 flex gap-4 overflow-x-auto pb-2">
            {films.data.recommended.map((f) => <FilmTile key={f.movie.id} f={f} wide />)}
          </div>
        </section>
      )}

      <section className="mt-12">
        <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Filmography">
          <h2 className="mr-3 font-display text-xl font-bold">Filmography</h2>
          {tabs.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={`rounded-full px-4 py-1.5 text-sm ${tab === t ? "bg-white text-black" : "text-white/80 hover:bg-white/10"}`}>
              {t}{t !== "All" && p.departments[t] ? ` (${p.departments[t]})` : ""}
            </button>
          ))}
        </div>
        {films.isLoading && <div className="mt-6 h-40 animate-pulse rounded bg-surface" />}
        <div className="mt-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-8">
          {shown.map((f) => <FilmTile key={f.movie.id} f={f} />)}
        </div>
      </section>
    </div>
  );
}

function FilmTile({ f, wide = false }: { f: Credit; wide?: boolean }) {
  const m = f.movie;
  const img = wide ? tmdbImage(m.backdrop ?? m.poster, "w300") : tmdbImage(m.poster, "w342");
  return (
    <Link to={`/movie/${m.id}`} state={{ source: "person_page" }}
      className={`group block shrink-0 ${wide ? "w-64" : ""}`}>
      <div className={`overflow-hidden rounded-md bg-surface-2 ${wide ? "aspect-video" : "aspect-[2/3]"}`}>
        {img && <img src={img} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]" />}
      </div>
      <div className="mt-2 text-sm font-medium leading-tight">{m.title}</div>
      <div className="mt-0.5 text-xs text-muted">
        {[m.year, f.character ? `as ${f.character}` : f.roles.filter((r) => r !== "Acting").join(", ")].filter(Boolean).join(" · ")}
      </div>
      <div className="mt-0.5 flex gap-2 text-xs">
        {f.match_pct != null && <span className="text-base font-extrabold text-accent">{f.match_pct}% match</span>}
        <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} className="text-white/70" />
      </div>
    </Link>
  );
}
