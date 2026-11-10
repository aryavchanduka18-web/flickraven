import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { tmdbImage } from "../../lib/tmdb";
import { SearchIcon } from "./icons";

type Suggest = {
  films: { id: number; title: string; year: number | null; poster: string | null }[];
  people: { id: number; name: string; profile_path: string | null; films: number }[];
  genres: { name: string; slug: string }[];
};

/** Search-as-you-type: films, people and genres under the box after 2 letters; Enter opens all results. */
export default function SearchBox({ variant = "bar" }: { variant?: "bar" | "sidebar" }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 180);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const res = useQuery({
    queryKey: ["suggest", debounced],
    queryFn: () => api<Suggest>(`/search/suggest?q=${encodeURIComponent(debounced)}`),
    enabled: debounced.length >= 2,
    staleTime: 60_000,
  });
  const d = res.data;
  const any = !!d && (d.films.length > 0 || d.people.length > 0 || d.genres.length > 0);
  const go = (to: string) => {
    setOpen(false);
    setQ("");
    navigate(to);
  };

  return (
    <form
      ref={box}
      className={variant === "sidebar" ? "relative w-full" : "relative ml-auto"}
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) go(`/search?q=${encodeURIComponent(q.trim())}`);
      }}
    >
      {variant === "sidebar" && <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-white/80" />}
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder={variant === "sidebar" ? "Search" : "Search titles, people, genres"}
        aria-label="Search"
        autoComplete="off"
        className={variant === "sidebar"
          ? "w-full rounded-2xl border border-transparent bg-white/[0.07] py-2.5 pl-11 pr-3 text-[15px] font-semibold text-white placeholder:font-semibold placeholder:text-white/70 transition-colors focus:border-white/25 focus:bg-white/[0.12] focus:outline-none"
          : "w-36 rounded-full border border-white/15 bg-black/40 px-4 py-1.5 text-sm text-white placeholder:text-white/45 focus:w-56 focus:outline-none md:w-56 md:focus:w-72 transition-[width] duration-200"}
      />
      {open && debounced.length >= 2 && (
        <div className={`absolute top-12 z-50 max-h-[70vh] w-[min(92vw,22rem)] overflow-y-auto rounded-2xl border border-white/10 bg-bg/95 p-2 shadow-2xl backdrop-blur-xl ${variant === "sidebar" ? "left-0" : "right-0"}`}>
          {any ? (
            <>
              {d!.genres.length > 0 && (
                <div className="flex flex-wrap gap-2 p-2">
                  {d!.genres.map((g) => (
                    <button key={g.slug} type="button" onClick={() => go(`/genres/${g.slug}`)}
                      className="rounded-full border border-white/20 px-3 py-1 text-xs hover:bg-white/10">
                      {g.name}
                    </button>
                  ))}
                </div>
              )}
              {d!.films.map((f) => (
                <Link key={f.id} to={`/movie/${f.id}`} onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-md p-2 hover:bg-white/10">
                  {f.poster ? <img src={tmdbImage(f.poster, "w300")} alt="" className="h-12 w-8 rounded object-cover" /> : <span className="h-12 w-8 rounded bg-surface-2" />}
                  <span className="min-w-0 truncate text-sm">
                    {f.title}
                    {f.year ? <span className="text-muted"> · {f.year}</span> : null}
                  </span>
                </Link>
              ))}
              {d!.people.length > 0 && <div className="px-2 pb-1 pt-2 text-xs uppercase tracking-wide text-muted">People</div>}
              {d!.people.map((p) => (
                <Link key={p.id} to={`/person/${p.id}`} onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-md p-2 hover:bg-white/10">
                  {p.profile_path ? <img src={tmdbImage(p.profile_path, "w300")} alt="" className="h-9 w-9 rounded-full object-cover" /> : <span className="h-9 w-9 rounded-full bg-surface-2" />}
                  <span className="text-sm">
                    {p.name} <span className="text-muted">· {p.films} films</span>
                  </span>
                </Link>
              ))}
              <button type="submit" className="mt-1 w-full rounded-md p-2 text-left text-sm text-accent hover:bg-white/10">
                See all results for "{debounced}"
              </button>
            </>
          ) : res.isFetching ? (
            <p className="p-3 text-sm text-muted">Searching…</p>
          ) : (
            <p className="p-3 text-sm text-muted">No match found yet. Press Enter to search everything.</p>
          )}
        </div>
      )}
    </form>
  );
}
