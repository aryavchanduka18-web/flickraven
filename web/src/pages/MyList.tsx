import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import MovieGrid from "../components/card/MovieGrid";
import { PageMessage } from "../components/Loading";

export default function MyList() {
  const [sort, setSort] = useState("recent");
  const q = useQuery({ queryKey: ["list", sort], queryFn: () => api<{ items: RecItem[] }>(`/list?sort=${sort}`) });
  if (q.data && !q.data.items.length) return <PageMessage title="Your list is empty">Use the + button on any film to save it here.</PageMessage>;
  return (
    <div className="mx-auto max-w-[1800px] px-4 pt-20 md:px-10">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-3xl font-extrabold">My List</h1>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort"
          className="rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm">
          <option value="recent">Recently added</option><option value="rating">Rating</option><option value="year">Year</option><option value="genre">Genre</option>
        </select>
      </div>
      <div className="mt-6">{q.data && <MovieGrid items={q.data.items} source="my_list" personal={false} />}</div>
    </div>
  );
}