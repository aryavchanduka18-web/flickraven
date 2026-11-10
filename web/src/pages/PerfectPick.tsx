import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { send } from "../api/client";
import type { RecItem } from "../api/types";
import ImdbScore from "../components/movie/ImdbScore";
import TypeBadge from "../components/movie/TypeBadge";
import { tmdbImage } from "../lib/tmdb";

type Option = [value: string, label: string, hint: string];
const MOODS: Option[] = [
  ["Funny", "Funny", "Make me laugh"], ["Feel-good", "Feel-good", "Warm and easy"], ["Relaxed", "Relaxed", "Gentle, nothing heavy"],
  ["Intense", "Intense", "Edge of the seat"], ["Mind-bending", "Mind-bending", "Make me think"], ["Scary", "Scary", "Keep the lights on"],
];
const TIMES: Option[] = [
  ["short", "Under 90 minutes", "A short film"], ["medium", "About 2 hours", "A normal film night"],
  ["long", "Plenty of time", "Long films are fine"], ["series", "A series", "25 hours or less in total"],
];
const ADVENTURE: Option[] = [
  ["familiar", "Familiar", "Close to what you already love"], ["balanced", "A bit of both", "Two safe picks and one surprise"],
  ["adventurous", "Adventurous", "Less known, still on your taste"],
];
type Result = { items: RecItem[]; message: string | null };

export default function PerfectPick() {
  const [step, setStep] = useState(0);
  const [a, setA] = useState({ mood: "", time: "", adventure: "" });
  const [other, setOther] = useState(false);
  const [shown, setShown] = useState<number[]>([]);
  const run = useMutation({
    mutationFn: (v: { answers: typeof a; exclude: number[]; other: boolean }) =>
      send<Result>("POST", "/recs/perfect-pick", { mood: v.answers.mood, time: v.answers.time, adventure: v.answers.adventure, other_languages: v.other, exclude: v.exclude }),
    onSuccess: (r) => setShown((s) => [...s, ...r.items.map((i) => i.movie.id)]),
  });
  const ask = (key: keyof typeof a, v: string) => {
    const next = { ...a, [key]: v };
    setA(next);
    if (step < 2) return setStep(step + 1);
    setStep(3);
    setShown([]);
    run.mutate({ answers: next, exclude: [], other });
  };
  const questions = [
    ["What are you in the mood for?", "mood", MOODS], ["How much time do you have?", "time", TIMES], ["Familiar or adventurous?", "adventure", ADVENTURE],
  ] as const;
  return (
    <div className="mx-auto max-w-[1100px] px-4 pb-24 pt-20 md:px-10">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">The Perfect Pick</p>
      <div className="mt-3 flex gap-2" aria-hidden>
        {[0, 1, 2, 3].map((i) => <i key={i} className={`h-1 flex-1 rounded-full transition-colors duration-500 ${i <= step ? "bg-white" : "bg-white/15"}`} />)}
      </div>
      {step < 3 ? (
        <div className="mt-8" key={step}>
          <h1 className="font-display text-3xl font-extrabold md:text-5xl">{questions[step][0]}</h1>
          <p className="mt-2 text-muted">One tap each. About a minute in total.</p>
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {questions[step][2].map(([v, label, hint], i) => (
              <button key={v} onClick={() => ask(questions[step][1], v)} style={{ animationDelay: `${i * 60}ms` }}
                className={`glass-btn hero-fade-in flex-col items-start rounded-3xl p-5 text-left ${a[questions[step][1]] === v ? "on" : ""}`}>
                <b className="text-lg">{label}</b>
                <span className="text-sm opacity-70">{hint}</span>
              </button>
            ))}
          </div>
          {step > 0 && <button onClick={() => setStep(step - 1)} className="glass-btn mt-6 rounded-2xl px-5 py-2.5 text-sm font-semibold">Back</button>}
        </div>
      ) : (
        <div className="mt-8">
          <h1 className="font-display text-3xl font-extrabold md:text-5xl">Your three picks</h1>
          <p className="mt-2 text-muted">{a.mood} · {TIMES.find((t) => t[0] === a.time)?.[1]} · {ADVENTURE.find((t) => t[0] === a.adventure)?.[1].toLowerCase()}</p>
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
              Include languages outside my profile
            </label>
            <button onClick={() => { setStep(0); setA({ mood: "", time: "", adventure: "" }); }} className="glass-btn ml-auto rounded-2xl px-5 py-2.5 text-sm font-semibold">Start over</button>
          </div>
        </div>
      )}
    </div>
  );
}
