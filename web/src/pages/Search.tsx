import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import MovieGrid from "../components/card/MovieGrid";
import { languageName } from "../lib/format";
import { tmdbImage } from "../lib/tmdb";

type Understood = { genres: string[]; language: string | null; year: number | null; decade: [number, number] | null; kind?: string | null; text: string };
type SearchRes = {
  items: RecItem[];
  understood: Understood;
  people: { id: number; name: string; profile_path: string | null; films: number }[];
  genres: { name: string; slug: string }[];
};

/** "Hindi Comedy films from 2019", from the words the search understood. */
function describe(u: Understood): string | null {
  if (!u.genres.length && !u.language && !u.year && !u.decade && !u.kind) return null;
  const when = u.year ? ` from ${u.year}` : u.decade ? ` from the ${u.decade[0]}s` : "";
  const kind = [u.language ? languageName(u.language) : null, ...u.genres].filter(Boolean).join(" ");
  const noun = u.kind === "anime" ? "anime" : u.kind === "series" ? "series" : "films";
  return `${kind || "All"} ${noun}${when}${u.text ? ` matching "${u.text}"` : ", most popular first"}`;
}

export default function Search() {
  const q = useSearchParams()[0].get("q") ?? "";
  const res = useQuery({ queryKey: ["search", q], queryFn: () => api<SearchRes>(`/search?q=${encodeURIComponent(q)}`), enabled: !!q });
  const d = res.data;
  const what = d ? describe(d.understood) : null;
  return (
    <div className="mx-auto max-w-[1800px] px-4 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Results for "{q}"</h1>
      {what && <p className="mt-1 text-sm text-muted">Showing {what}</p>}
      {d && (d.genres.length > 0 || d.people.length > 0) && (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {d.genres.map((g) => (
            <Link key={g.slug} to={`/genres/${g.slug}`} className="rounded-full border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10">
              {g.name} films
            </Link>
          ))}
          {d.people.map((p) => (
            <Link key={p.id} to={`/person/${p.id}`} className="flex items-center gap-2 rounded-full border border-white/20 py-1 pl-1 pr-4 text-sm hover:bg-white/10">
              {p.profile_path ? <img src={tmdbImage(p.profile_path, "w300")} alt="" className="h-8 w-8 rounded-full object-cover" /> : <span className="h-8 w-8 rounded-full bg-surface-2" />}
              {p.name}
            </Link>
          ))}
        </div>
      )}
      <div className="mt-6">
        {d && (d.items.length ? <MovieGrid items={d.items} source="search" personal={false} /> : <p className="text-muted">No films match. Try fewer words or another spelling.</p>)}
      </div>
    </div>
  );
}
