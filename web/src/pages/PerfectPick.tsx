import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { send } from "../api/client";
import type { RecItem } from "../api/types";
import ImdbScore from "../components/movie/ImdbScore";
import TypeBadge from "../components/movie/TypeBadge";
import { tmdbImage } from "../lib/tmdb";

type Option = [value: string, label: string, hint: string];
const KINDS: Option[] = [["movie", "A movie", "One sitting"], ["series", "A TV series", "Something to follow"], ["either", "Either is fine", "Films and series together"]];
const MOODS: Option[] = [
  ["Funny", "Funny", "Make me laugh"], ["Feel-good", "Feel-good", "Warm and easy"], ["Romantic", "Romantic", "Love stories"], ["Relaxed", "Relaxed", "Gentle, nothing heavy"],
  ["Intense", "Intense", "Edge of the seat"], ["Mind-bending", "Mind-bending", "Make me think"], ["Scary", "Scary", "Keep the lights on"],
  ["Emotional", "Emotional", "Let me feel something"], ["Suspenseful", "Suspenseful", "Keep me guessing"], ["Mysterious", "Mysterious", "A puzzle to solve"],
  ["", "No mood in mind", "Surprise me"],
];
const GENRES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "Thriller", "War", "Western"];
const LANGS: [string, string][] = [["en", "English"], ["hi", "Hindi"], ["ko", "Korean"], ["ja", "Japanese"], ["ta", "Tamil"], ["te", "Telugu"], ["ml", "Malayalam"], ["other", "Other languages"]];
const TIMES: Record<string, Option[]> = {
  movie: [["lt90", "Under 90 minutes", "A short film"], ["90_120", "90 to 120 minutes", "A normal film night"], ["120_180", "2 to 3 hours", "An epic is fine"], ["any", "Longer is fine", "No limit"]],
  series: [["season", "One short season", "Just one season"], ["h10", "Under 10 hours", "A weekend"], ["h20", "10 to 20 hours", "A few weeks"], ["h30", "20 to 30 hours", "A long journey"], ["any", "No strict limit", "Any length"]],
  either: [["e120", "Under 2 hours", "Films, or a very short series"], ["e180", "Under 3 hours", "A film, or a short series"], ["e600", "Under 10 hours", "A film, or a short series"], ["any", "No limit", "Anything"]],
};
const STATUSES: Option[] = [["any", "Either", ""], ["completed", "Finished series", "Story is complete"], ["airing", "Still airing", "New episodes coming"]];
const ADVENTURE: Option[] = [
  ["familiar", "Familiar", "Close to what you already love"], ["balanced", "A bit of both", "Two safe picks and one surprise"],
  ["adventurous", "Unexpected, but my taste", "Less known, still on your taste"],
];
type Answers = { kind: string; mood: string; genres: string[]; languages: string[]; time: string; status: string; adventure: string };
const EMPTY: Answers = { kind: "", mood: "", genres: [], languages: [], time: "", status: "any", adventure: "" };
type Result = { items: RecItem[]; message: string | null; relaxed?: string[] };
const STEPS = ["kind", "mood", "genres", "languages", "time", "adventure"] as const;
const TITLES: Record<(typeof STEPS)[number], string> = {
  kind: "What are you looking for?", mood: "What mood are you in?", genres: "Which genres interest you?",
  languages: "Which languages are fine?", time: "How much time do you have?", adventure: "Familiar, or something new?",
};

export default function PerfectPick() {
  const [step, setStep] = useState(0);
  const [a, setA] = useState<Answers>(EMPTY);
  const [other, setOther] = useState(false);
  const [shown, setShown] = useState<number[]>([]);
  const run = useMutation({
    mutationFn: (v: { answers: Answers; exclude: number[]; other: boolean }) =>
      send<Result>("POST", "/recs/perfect-pick", {
        kind: v.answers.kind, mood: v.answers.mood || null, genres: v.answers.genres, languages: v.answers.languages,
        time: v.answers.time, status: v.answers.kind === "movie" ? "any" : v.answers.status, adventure: v.answers.adventure,
        other_languages: v.other, exclude: v.exclude,
      }),
    onSuccess: (r) => setShown((s) => [...s, ...r.items.map((i) => i.movie.id)]),
  });
  const done = step >= STEPS.length;
  const go = (next: Answers) => {
    if (step + 1 < STEPS.length) return setStep(step + 1);
    setStep(STEPS.length);
    setShown([]);
    run.mutate({ answers: next, exclude: [], other });
  };
  const set = (patch: Partial<Answers>) => setA({ ...a, ...patch });
  const pickOne = (key: "kind" | "mood" | "adventure", v: string) => {
    // changing the kind clears a time chosen for the other kind
    const next = key === "kind" && v !== a.kind ? { ...a, kind: v, time: "", status: "any" } : { ...a, [key]: v };
    setA(next);
    go(next);
  };
  const toggle = (key: "genres" | "languages", v: string) => set({ [key]: a[key].includes(v) ? a[key].filter((x) => x !== v) : [...a[key], v] });
  const current = STEPS[Math.min(step, STEPS.length - 1)];
  const timeText = TIMES[a.kind]?.find((t) => t[0] === a.time)?.[1];
  const card = (on: boolean) => `glass-btn hero-fade-in flex-col items-start rounded-3xl p-5 text-left ${on ? "on" : ""}`;
  const pill = (on: boolean) => `glass-btn rounded-full px-4 py-2 text-sm font-semibold ${on ? "on" : ""}`;
  return (
    <div className="mx-auto max-w-[1100px] px-4 pb-24 pt-20 md:px-10">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">The Perfect Pick</p>
      <div className="mt-3 flex gap-2" aria-hidden>
        {[...STEPS, "end"].map((_, i) => <i key={i} className={`h-1 flex-1 rounded-full transition-colors duration-500 ${i <= step ? "bg-white" : "bg-white/15"}`} />)}
      </div>
      {!done ? (
        <div className="mt-8" key={current}>
          <p className="text-xs uppercase tracking-widest text-white/50">Question {step + 1} of {STEPS.length}</p>
          <h1 className="mt-1 font-display text-3xl font-extrabold md:text-5xl">{TITLES[current]}</h1>
          {current === "kind" && <p className="mt-2 text-muted">Six quick questions. You can go back and change any answer.</p>}
          {current === "genres" && <p className="mt-2 text-muted">Pick as many as you like, or none.</p>}
          {current === "languages" && <p className="mt-2 text-muted">Pick as many as you like. None means any language.</p>}

          {(current === "kind" || current === "mood" || current === "adventure") && (
            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              {(current === "kind" ? KINDS : current === "mood" ? MOODS : ADVENTURE).map(([v, label, hint], i) => (
                <button key={v || "none"} onClick={() => pickOne(current, v)} style={{ animationDelay: `${i * 50}ms` }} className={card(a[current] === v && (v !== "" || a.mood === ""))}>
                  <b className="text-lg">{label}</b><span className="text-sm opacity-70">{hint}</span>
                </button>
              ))}
            </div>
          )}

          {current === "genres" && (
            <div className="mt-8 flex flex-wrap gap-2">
              {GENRES.map((g) => <button key={g} aria-pressed={a.genres.includes(g)} onClick={() => toggle("genres", g)} className={pill(a.genres.includes(g))}>{g}</button>)}
            </div>
          )}
          {current === "languages" && (
            <div className="mt-8 flex flex-wrap gap-2">
              {LANGS.map(([c, n]) => <button key={c} aria-pressed={a.languages.includes(c)} onClick={() => toggle("languages", c)} className={pill(a.languages.includes(c))}>{n}</button>)}
              <button aria-pressed={!a.languages.length} onClick={() => set({ languages: [] })} className={pill(!a.languages.length)}>Any language</button>
            </div>
          )}

          {current === "time" && (
            <>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {(TIMES[a.kind] ?? TIMES.movie).map(([v, label, hint], i) => (
                  <button key={v} onClick={() => set({ time: v })} aria-pressed={a.time === v} style={{ animationDelay: `${i * 50}ms` }} className={card(a.time === v)}>
                    <b className="text-lg">{label}</b><span className="text-sm opacity-70">{hint}</span>
                  </button>
                ))}
              </div>
              {a.kind !== "movie" && (
                <div className="mt-6">
                  <p className="text-sm text-white/70">For series: finished or still airing?</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {STATUSES.map(([v, label]) => <button key={v} aria-pressed={a.status === v} onClick={() => set({ status: v })} className={pill(a.status === v)}>{label}</button>)}
                  </div>
                </div>
              )}
            </>
          )}

          <div className="mt-8 flex gap-3">
            {step > 0 && <button onClick={() => setStep(step - 1)} className="glass-btn rounded-2xl px-5 py-2.5 text-sm font-semibold">Back</button>}
            {(current === "genres" || current === "languages") && <button onClick={() => go(a)} className="glass-btn solid rounded-2xl px-6 py-2.5 text-sm font-semibold">Continue</button>}
            {current === "time" && <button disabled={!a.time} onClick={() => go(a)} className="glass-btn solid rounded-2xl px-6 py-2.5 text-sm font-semibold disabled:opacity-40">Continue</button>}
          </div>
        </div>
      ) : (
        <div className="mt-8">
          <h1 className="font-display text-3xl font-extrabold md:text-5xl">Your three picks</h1>
          <p className="mt-2 text-muted">{[KINDS.find((k) => k[0] === a.kind)?.[1], a.mood, a.genres.join(", "), a.languages.length ? LANGS.filter(([c]) => a.languages.includes(c)).map(([, n]) => n).join(", ") : "", timeText, ADVENTURE.find((t) => t[0] === a.adventure)?.[1].toLowerCase()].filter(Boolean).join(" · ")}</p>
          {run.isPending && <div className="mt-8 h-72 animate-pulse rounded-3xl bg-surface" />}
          {run.isError && <p className="mt-6 text-sm text-red-300">{(run.error as Error).message}</p>}
          {run.data?.message && <p className="glass mt-6 rounded-2xl px-4 py-3 text-sm">{run.data.message}</p>}
          {run.data && (
            <div className="mt-8 grid gap-5 md:grid-cols-3">
              {run.data.items.map((it, i) => (
                <article key={it.movie.id} className="glass hero-fade-in flex flex-col overflow-hidden rounded-3xl" style={{ animationDelay: `${i * 90}ms` }}>
                  <Link to={`/movie/${it.movie.id}`} state={{ source: "perfect_pick", position: i }} className="relative block aspect-[2/3]">
                    {it.movie.poster && <img src={tmdbImage(it.movie.poster, "w342")} alt="" className="h-full w-full object-cover" />}
                    <span className="glass absolute left-3 top-3 grid h-8 w-8 place-items-center rounded-full text-sm font-bold">{i + 1}</span>
                  </Link>
                  <div className="flex flex-1 flex-col p-4">
                    <h2 className="font-display text-xl font-bold">{it.movie.title}</h2>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-muted">
                      {it.movie.year && <span>{it.movie.year}</span>}<TypeBadge type={it.movie.title_type} />
                      <ImdbScore rating={it.movie.imdb_rating} votes={it.movie.imdb_votes} />
                    </div>
                    <ul className="mt-3 space-y-1 text-sm text-white/80">{it.reasons.map((r) => <li key={r.code}>{r.text}</li>)}</ul>
                    <div className="mt-auto flex gap-2 pt-4">
                      <Link to={`/movie/${it.movie.id}`} className="glass-btn solid rounded-xl px-4 py-2 text-sm font-semibold">Details</Link>
                      <button onClick={() => run.mutate({ answers: a, exclude: shown, other })} className="glass-btn rounded-xl px-4 py-2 text-sm font-semibold" title="Get three new picks">Not these</button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-white/75">
              <input type="checkbox" checked={other} onChange={(e) => { setOther(e.target.checked); setShown([]); run.mutate({ answers: a, exclude: [], other: e.target.checked }); }} />
              Include other languages
            </label>
            <button onClick={() => setStep(0)} className="glass-btn ml-auto rounded-2xl px-5 py-2.5 text-sm font-semibold">Change answers</button>
            <button onClick={() => { setStep(0); setA(EMPTY); setOther(false); }} className="glass-btn rounded-2xl px-5 py-2.5 text-sm font-semibold">Start over</button>
          </div>
        </div>
      )}
    </div>
  );
}
