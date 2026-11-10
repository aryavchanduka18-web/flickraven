import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { SimilarPage } from "../api/hooks";
import { useMovie } from "../api/hooks";
import { PosterGrid } from "../components/card/PosterCard";
import { PageMessage } from "../components/Loading";

const PAGE = 12;

/** All stored similar titles for one title (up to 40), 12 at a time with Load more. */
export default function SimilarAll() {
  const id = Number(useParams().id);
  const movie = useMovie(id);
  const q = useInfiniteQuery({
    queryKey: ["similar-all", id],
    queryFn: ({ pageParam }) => api<SimilarPage>(`/movies/${id}/similar?offset=${pageParam}&limit=${PAGE}`),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total && last.items.length ? last.offset + PAGE : undefined),
  });
  if (q.isError) return <PageMessage title="Could not load similar titles" />;
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const total = q.data?.pages[0]?.total ?? 0;
  return (
    <div className="mx-auto max-w-[1800px] px-4 pb-20 pt-20 md:px-10">
      <Link to={`/movie/${id}`} className="text-sm text-muted hover:text-white">← Back to {movie.data?.title ?? "the title"}</Link>
      <h1 className="mt-2 font-display text-3xl font-extrabold">More like {movie.data?.title ?? "this"}</h1>
      <p className="mb-6 mt-1 text-sm text-muted">Most similar first, by story, themes, people and language. Same for everyone.</p>
      {q.isLoading ? <div className="h-64 animate-pulse rounded-md bg-surface" />
        : items.length === 0 ? <p className="text-sm text-muted">No similar titles found.</p>
        : <PosterGrid items={items} source="more_like_this_all" />}
      <div className="mt-8 flex flex-col items-center gap-2">
        {total > 0 && <p className="text-xs text-muted">Showing {items.length} of {total}</p>}
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
