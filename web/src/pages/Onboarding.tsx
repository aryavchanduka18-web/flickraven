import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api, send } from "../api/client";
import type { RecItem } from "../api/types";
import { CardArtwork } from "../components/card/MovieCard";
import { languageName } from "../lib/format";

type Candidates = {
  movies: RecItem[];
  series: RecItem[];
  anime: RecItem[];
  languages: { code: string; films: number }[];
  genres: { id: number; name: string }[];
};
const STEPS = ["Titles you love", "Your languages", "Genres"];
const KINDS = [["movies", "Films"], ["series", "Series"], ["anime", "Anime"]] as const;

/** Onboarding: preference signals, not behavior. The user stays "cold" until 3 real actions (spec 6.1). */
export default function Onboarding() {
  const data = useQuery({ queryKey: ["onboarding"], queryFn: () => api<Candidates>("/onboarding/candidates") });
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState<"movies" | "series" | "anime">("movies");
  const [anime, setAnime] = useState(false);
  const [picks, setPicks] = useState<number[]>([]);
  const [langs, setLangs] = useState<string[]>(["en"]);
  const [liked, setLiked] = useState<number[]>([]);
  const [disliked, setDisliked] = useState<number[]>([]);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const save = useMutation({
    mutationFn: async () => {
      await send("POST", "/onboarding", { movie_ids: picks, languages: langs, liked_genre_ids: liked, disliked_genre_ids: disliked });
      if (anime) await send("PUT", "/me/preferences", { show_anime: true });
    },
    onSuccess: () => {
      qc.invalidateQueries();
      navigate("/");
    },
  });
  const toggle = <T,>(list: T[], set: (v: T[]) => void, v: T, max = 99) =>
    set(list.includes(v) ? list.filter((x) => x !== v) : list.length < max ? [...list, v] : list);
  const canNext = [picks.length >= 5, langs.length >= 1, true][step];

  return (
    <div className="mx-auto max-w-[1400px] px-4 pb-24 pt-24 md:px-10">
      <p className="text-sm text-muted">Step {step + 1} of 3</p>
      <h1 className="mt-1 font-display text-3xl font-extrabold">{STEPS[step]}</h1>
      {step === 0 && (
        <p className="mt-2 text-sm text-muted">
          Pick 5 to 10 films, series or anime you like. {picks.length}/10 picked. Use Letterboxd or IMDb? You can also{" "}
          <Link to="/account#import" className="text-white underline">import your ratings</Link> after this.
        </p>
      )}
      <div className="mt-6">
        {data.isLoading && <p className="text-muted">Loading films…</p>}
        {step === 0 && data.data && (
          <div className="mb-4 flex gap-2" role="tablist" aria-label="Type">
            {KINDS.filter(([k]) => k !== "anime" || anime).map(([k, label]) => (
              <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
                className={`rounded-full px-4 py-1.5 text-sm ${kind === k ? "bg-white font-medium text-black" : "border border-white/20 text-white/85 hover:bg-white/10"}`}>
                {label}
              </button>
            ))}
            <label className="ml-2 flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={anime} onChange={(e) => { setAnime(e.target.checked); if (!e.target.checked && kind === "anime") setKind("movies"); }} />
              I also watch anime
            </label>
          </div>
        )}
        {step === 0 && data.data && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
            {data.data[kind].map((it) => {
              const on = picks.includes(it.movie.id);
              return (
                <button key={it.movie.id} onClick={() => toggle(picks, setPicks, it.movie.id, 10)} aria-pressed={on}
                  className={`relative rounded-md text-left ring-2 transition ${on ? "ring-white" : "ring-transparent hover:ring-white/30"}`}>
                  <CardArtwork item={it} />
                  {on && <span className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-white text-sm font-bold text-black">✓</span>}
                  <span className="mt-1 block text-xs text-muted">{it.movie.year} · {languageName(it.movie.language)}</span>
                </button>
              );
            })}
          </div>
        )}
        {step === 1 && data.data && (
          <Chips items={data.data.languages.map((l) => ({ key: l.code, label: `${languageName(l.code)}`, sub: `${l.films} films` }))}
            selected={langs} onToggle={(k) => toggle(langs, setLangs, k)} />
        )}
        {step === 2 && data.data && (
          <>
            <p className="mb-4 text-sm text-muted">Tap a genre once if you like it, twice if you want to avoid it, three times to clear it.</p>
            <div className="flex flex-wrap gap-2">
              {data.data.genres.map((g) => {
                const state = liked.includes(g.id) ? "like" : disliked.includes(g.id) ? "avoid" : "none";
                const next = () => {
                  setLiked(state === "none" ? [...liked, g.id] : liked.filter((x) => x !== g.id));
                  setDisliked(state === "like" ? [...disliked, g.id] : disliked.filter((x) => x !== g.id));
                };
                return (
                  <button key={g.id} onClick={next} aria-pressed={state !== "none"}
                    className={`rounded-full border px-4 py-2 text-sm transition-colors ${state === "like" ? "border-white bg-white text-black" : state === "avoid" ? "border-red-400/70 bg-red-500/15 text-red-200 line-through" : "border-white/20 hover:border-white/50"}`}>
                    {g.name}{state === "like" && <span className="ml-2 text-xs text-black/60">like</span>}{state === "avoid" && <span className="ml-2 text-xs no-underline">avoid</span>}
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-white/10 bg-bg/95 px-4 py-3 md:px-10">
        <div className="mx-auto flex max-w-[1400px] justify-between">
          <button disabled={step === 0} onClick={() => setStep(step - 1)} className="rounded-md px-4 py-2 text-sm text-muted disabled:opacity-30">Back</button>
          {step < 2 ? (
            <button disabled={!canNext} onClick={() => setStep(step + 1)} className="rounded-md bg-white px-6 py-2 text-sm font-semibold text-black disabled:opacity-40">Next</button>
          ) : (
            <button disabled={save.isPending} onClick={() => save.mutate()} className="rounded-md bg-white px-6 py-2 text-sm font-semibold text-black disabled:opacity-40">
              {save.isPending ? "Building your recommendations…" : "Show my recommendations"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Chips<K extends string | number>({ items, selected, onToggle }: { items: { key: K; label: string; sub?: string }[]; selected: K[]; onToggle: (k: K) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((it) => {
        const on = selected.includes(it.key);
        return (
          <button key={String(it.key)} onClick={() => onToggle(it.key)} aria-pressed={on}
            className={`rounded-full border px-4 py-2 text-sm transition-colors ${on ? "border-white bg-white text-black" : "border-white/20 hover:border-white/50"}`}>
            {it.label}{it.sub && <span className={`ml-2 text-xs ${on ? "text-black/60" : "text-muted"}`}>{it.sub}</span>}
          </button>
        );
      })}
    </div>
  );
}