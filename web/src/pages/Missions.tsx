import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RecItem } from "../api/types";
import Rail from "../components/rail/Rail";

type Mission = { key: string; title: string; description: string; goal: number; progress: number; done: boolean; suggestions: RecItem[] };

/** Discovery missions: personal challenges, progress counted from what you watched, rated or liked. */
export default function Missions() {
  const { data } = useQuery({ queryKey: ["missions"], queryFn: () => api<{ missions: Mission[] }>("/me/missions") });
  return (
    <div className="mx-auto max-w-[1800px] px-4 pb-20 pt-24 md:px-10">
      <h1 className="font-display text-3xl font-extrabold">Discovery missions</h1>
      <p className="mt-1 text-sm text-muted">Small challenges to widen what you watch. Progress counts titles you mark watched, rate or like.</p>
      <div className="mt-8 space-y-10">
        {data?.missions.map((m) => (
          <section key={m.key}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-xl font-bold">{m.title} {m.done && <span className="ml-2 text-sm text-accent">Completed</span>}</h2>
              <span className="text-sm text-muted">{m.progress} / {m.goal}</span>
            </div>
            <p className="text-sm text-muted">{m.description}</p>
            <div className="mt-2 h-2 w-full max-w-md overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-accent" style={{ width: `${(100 * m.progress) / m.goal}%` }} />
            </div>
            {m.suggestions.length > 0 && (
              <div className="-mx-4 mt-3 md:-mx-10">
                <Rail title="Ideas to get you there" items={m.suggestions} source={`mission:${m.key}`} personal={false} />
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
