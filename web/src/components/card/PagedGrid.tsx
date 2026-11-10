import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import type { RecItem } from "../../api/types";
import MovieGrid from "./MovieGrid";
import { PosterGrid } from "./PosterCard";

type Page = { items: RecItem[]; total: number; page: number };

/** A grid that keeps loading the next server page (40 films) as you scroll, with a Load more button
 *  as a fallback, so every film in a genre or filter can be reached. */
export default function PagedGrid({ queryKey, path, source, personal = true, onTotal, poster = false }: {
  queryKey: unknown[]; path: (page: number) => string; source: string; personal?: boolean; onTotal?: (n: number) => void;
  /** Vertical poster cards (2:3, four per row on wide screens) instead of the wide 16:9 cards. */
  poster?: boolean;
}) {
  const q = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => api<Page>(path(pageParam)),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * 40 < last.total ? last.page + 1 : undefined),
  });
  const sentinel = useRef<HTMLDivElement>(null);
  const total = q.data?.pages[0]?.total;
  useEffect(() => {
    if (total != null) onTotal?.(total);
  }, [total, onTotal]);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((e) => {
      if (e[0].isIntersecting && q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage();
    }, { rootMargin: "800px" });
    io.observe(el);
    return () => io.disconnect();
  }, [q.hasNextPage, q.isFetchingNextPage, q.fetchNextPage]);

  if (q.isLoading) return <div className="h-64 animate-pulse rounded-md bg-surface" />;
  if (q.isError) return <p className="text-sm text-red-300">Could not load these titles. Try again in a moment.</p>;
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  if (!items.length) return <p className="text-sm text-muted">No match found.</p>;
  return (
    <div>
      {poster ? <PosterGrid items={items} source={source} /> : <MovieGrid items={items} source={source} personal={personal} />}
      <div ref={sentinel} className="flex flex-col items-center gap-2 pb-16">
        <p className="text-xs text-muted">Showing {items.length.toLocaleString()} of {(total ?? 0).toLocaleString()}</p>
        {q.hasNextPage && (
          <button onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}
            className="rounded-md border border-white/20 px-5 py-2 text-sm hover:border-white/50 disabled:opacity-60">
            {q.isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
