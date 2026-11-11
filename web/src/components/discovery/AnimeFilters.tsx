import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";

export type AnimeTag = { key: string; label: string; group: "genre" | "theme" | "mature"; titles: number };
export type AnimeSel = { tags: string[]; avoid: string[] };
export const NO_ANIME_SEL: AnimeSel = { tags: [], avoid: [] };

/** Query-string part for the chosen anime tags (empty when nothing is chosen). */
export function animeQuery(s: AnimeSel): string {
  return (s.tags.length ? `&anime_tags=${s.tags.join(",")}` : "") + (s.avoid.length ? `&anime_avoid=${s.avoid.join(",")}` : "");
}

const toggle = (list: string[], k: string) => (list.includes(k) ? list.filter((x) => x !== k) : [...list, k]);

/** Anime-only filters: Genres (pick several, any of them matches), then More filters with Themes, a Mature section
 *  and an Avoid list. Only tags the catalog really has enough titles for are offered. A filter narrows what you
 *  browse; it is never a signal about your taste. */
export default function AnimeFilters({ value, onChange }: { value: AnimeSel; onChange: (s: AnimeSel) => void }) {
  const q = useQuery({ queryKey: ["anime-tags"], queryFn: () => api<{ tags: AnimeTag[] }>("/genres/anime/tags"), staleTime: 3600_000 });
  const [more, setMore] = useState(false);
  const tags = q.data?.tags ?? [];
  if (!tags.length) return null;
  const by = (g: string) => tags.filter((t) => t.group === g);
  const chip = (t: AnimeTag, on: boolean, click: () => void, extra = "") => (
    <button key={t.key + extra} aria-pressed={on} onClick={click} title={`${t.titles.toLocaleString()} titles`}
      className={`glass-btn rounded-full px-4 py-1.5 text-sm ${on ? "on" : ""}`}>{t.label}</button>
  );
  const nChosen = value.tags.length + value.avoid.length;
  const avoidable = tags.filter((t) => ["ecchi", "harem", "horror"].includes(t.key));
  return (
    <div className="mt-3 space-y-3">
      <div role="group" aria-label="Genres">
        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Genres <span className="font-normal normal-case">(pick any, a title needs just one)</span></div>
        <div className="flex flex-wrap gap-2">{by("genre").map((t) => chip(t, value.tags.includes(t.key), () => onChange({ ...value, tags: toggle(value.tags, t.key) })))}</div>
      </div>
      <button onClick={() => setMore(!more)} aria-expanded={more} className="glass-btn rounded-full px-4 py-1.5 text-sm font-semibold">
        More filters{nChosen ? ` (${nChosen} on)` : ""}
      </button>
      {more && (
        <div className="space-y-3 rounded-md border border-white/10 p-3">
          <div role="group" aria-label="Themes">
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Themes</div>
            <div className="flex flex-wrap gap-2">{by("theme").map((t) => chip(t, value.tags.includes(t.key), () => onChange({ ...value, tags: toggle(value.tags, t.key) }), "t"))}</div>
          </div>
          {!!by("mature").length && (
            <div role="group" aria-label="Mature content">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Mature content (adult fan service)</div>
              <div className="flex flex-wrap gap-2">{by("mature").map((t) => chip(t, value.tags.includes(t.key), () => onChange({ ...value, tags: toggle(value.tags, t.key) }), "m"))}</div>
            </div>
          )}
          <div role="group" aria-label="Avoid">
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Avoid (hide titles with these)</div>
            <div className="flex flex-wrap gap-2">{avoidable.map((t) => chip(t, value.avoid.includes(t.key), () => onChange({ ...value, avoid: toggle(value.avoid, t.key) }), "a"))}</div>
          </div>
        </div>
      )}
      {nChosen > 0 && <button onClick={() => onChange(NO_ANIME_SEL)} className="text-sm text-muted underline">Clear anime filters</button>}
    </div>
  );
}
