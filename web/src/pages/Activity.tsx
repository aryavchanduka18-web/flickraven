import RecReport from "../components/explain/RecReport";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { languageName } from "../lib/format";
import { tmdbImage } from "../lib/tmdb";

type Item = { id: number; event_type: string; value: number | null; created_at: string; movie_id: number | null; title: string | null; backdrop_path: string | null };
type Taste = {
  top_genres: { genre: string; count: number }[]; top_languages: { language: string; count: number }[];
  eras: { decade: number; count: number }[]; average_rating: number | null; like_dislike_ratio: number | null;
  films_rated: number; films_saved: number; discovery_mode: string; stage: string; behavioral_count: number; onboarding_count: number;
};
const LABEL: Record<string, string> = {
  detail_view: "Viewed", quick_view: "Quick viewed", search_click: "Opened from search", rate: "Rated", unrate: "Removed rating",
  like: "Liked", dislike: "Disliked", clear_reaction: "Cleared reaction", list_add: "Added to My List", list_remove: "Removed from My List",
  watched: "Marked watched", unwatched: "Unmarked watched", onboarding_pick: "Picked in onboarding", hero_view: "Opened from hero",
};
const TABS = [["", "All"], ["ratings", "Ratings"], ["likes", "Likes"], ["list", "My List"], ["watched", "Watched"], ["views", "Views"]];

export default function Activity() {
  const [type, setType] = useState("");
  const taste = useQuery({ queryKey: ["taste"], queryFn: () => api<Taste>("/me/taste-profile") });
  const q = useQuery({ queryKey: ["activity", type], queryFn: () => api<{ items: Item[] }>(`/activity${type ? `?type=${type}` : ""}`) });
  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Activity</h1>
      <RecReport />
      {taste.data && <TasteProfile t={taste.data} />}
      <div className="mt-10 flex flex-wrap gap-2" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={type === k} onClick={() => setType(k)}
            className={`rounded-full px-4 py-1.5 text-sm ${type === k ? "bg-white text-black" : "text-white/80 hover:bg-white/10"}`}>{l}</button>
        ))}
      </div>
      <ol className="mt-6 divide-y divide-white/5">
        {q.data?.items.map((it) => (
          <li key={it.id} className="flex items-center gap-4 py-3">
            <div className="aspect-video w-28 shrink-0 overflow-hidden rounded bg-surface-2">
              {it.backdrop_path && <img src={tmdbImage(it.backdrop_path, "w300")} alt="" loading="lazy" className="h-full w-full object-cover" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm"><span className="text-muted">{LABEL[it.event_type] ?? it.event_type}</span>{" "}
                {it.movie_id && <Link to={`/movie/${it.movie_id}`} className="font-medium hover:underline">{it.title}</Link>}
                {it.event_type === "rate" && it.value != null && <span className="ml-2 text-accent">{it.value}/10</span>}
              </div>
              <div className="text-xs text-muted">{new Date(it.created_at).toLocaleString()}</div>
            </div>
          </li>
        ))}
        {q.data && !q.data.items.length && <li className="py-6 text-sm text-muted">Nothing here yet.</li>}
      </ol>
    </div>
  );
}

function TasteProfile({ t }: { t: Taste }) {
  const max = Math.max(1, ...t.top_genres.map((g) => g.count));
  const stat = (label: string, value: string | number | null) => (
    <div className="rounded-lg bg-surface p-4"><div className="text-xs text-muted">{label}</div><div className="mt-1 text-xl font-semibold">{value ?? "–"}</div></div>
  );
  return (
    <section className="mt-6 grid gap-6 md:grid-cols-[1.4fr_1fr]" aria-label="Taste Profile">
      <div className="rounded-lg bg-surface p-5">
        <h2 className="mb-4 text-sm font-semibold">Your top genres</h2>
        {t.top_genres.length ? t.top_genres.map((g) => (
          <div key={g.genre} className="mb-2 flex items-center gap-3 text-sm">
            <span className="w-28 shrink-0 text-white/85">{g.genre}</span>
            <div className="h-2 flex-1 rounded-full bg-white/10"><div className="h-2 rounded-full bg-white/80" style={{ width: `${(g.count / max) * 100}%` }} /></div>
            <span className="w-6 text-right text-xs text-muted">{g.count}</span>
          </div>
        )) : <p className="text-sm text-muted">Rate or like a few films to see your taste.</p>}
        <div className="mt-4 text-sm text-muted">
          Languages: {t.top_languages.map((l) => languageName(l.language)).join(", ") || "–"} · Eras: {t.eras.map((e) => `${e.decade}s`).join(", ") || "–"}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {stat("Films rated", t.films_rated)}{stat("Films saved", t.films_saved)}
        {stat("Average rating", t.average_rating)}{stat("Likes per dislike", t.like_dislike_ratio)}
        {stat("Discovery", t.discovery_mode)}{stat("Stage", `${t.stage} (${t.behavioral_count})`)}
      </div>
    </section>
  );
}