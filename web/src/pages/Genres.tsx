import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import PagedGrid from "../components/card/PagedGrid";
import { tmdbImage } from "../lib/tmdb";

export function Genres() {
  const q = useQuery({ queryKey: ["genres"], queryFn: () => api<{ genres: { id: number; name: string; slug: string; films: number; backdrop: string | null }[] }>("/genres") });
  return (
    <div className="mx-auto max-w-[1800px] px-4 pt-20 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Genres</h1>
      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
        {q.data?.genres.map((g) => (
          <Link key={g.slug} to={`/genres/${g.slug}`} className="group relative aspect-video overflow-hidden rounded-md bg-surface">
            {g.backdrop && <img src={tmdbImage(g.backdrop, "w780")} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" />}
            <div className="absolute inset-0 bg-gradient-to-t from-black/90 to-black/10" />
            <div className="absolute bottom-3 left-4">
              <div className="font-display text-xl font-bold">{g.name}</div>
              <div className="text-xs text-muted">{g.films.toLocaleString()} {g.slug === "anime" ? "titles" : "films"}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function Genre() {
  const slug = useParams().slug!;
  const [total, setTotal] = useState<number | null>(null);
  const name = useQuery({ queryKey: ["genres"], queryFn: () => api<{ genres: { name: string; slug: string }[] }>("/genres") })
    .data?.genres.find((x) => x.slug === slug)?.name;
  return (
    <div className="mx-auto max-w-[1800px] px-4 pt-20 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">{name ?? ""}</h1>
      <p className="mt-1 text-sm text-muted">{total != null ? `${total.toLocaleString()} ${slug === "anime" ? "titles" : "films"}, ` : ""}{slug === "anime" ? "most popular first (Japanese animation: TV anime and films)." : "ranked for you by the recommender."}</p>
      <div className="mt-6">
        <PagedGrid queryKey={["genre", slug]} path={(p) => `/genres/${slug}/movies?page=${p}`} source={`genre:${slug}`} onTotal={setTotal} />
      </div>
    </div>
  );
}
