import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { LineChart, ScatterChart } from "../components/lab/charts";

const NAMES: Record<string, string> = {
  bias: "Bias baseline", popularity: "Popularity", content: "Content-based", user_cf: "User CF", item_cf: "Item CF",
  svd: "Funk SVD", als: "Implicit ALS", hybrid_blend: "Hybrid (blend only)", hybrid_familiar: "Hybrid · Familiar",
  hybrid_balanced: "Hybrid · Balanced", hybrid_discover: "Hybrid · Discover",
};
const COLORS = ["#ffffff", "#C8102E", "#8fb3ff", "#f2c14e", "#7bd389", "#c792ea", "#ff9e7a", "#a7a7a7"];
type CI = { mean: number; ci_low: number; ci_high: number };
const get = <T,>(path: string) => () => api<T>(path);

function useLab<T>(key: string) {
  return useQuery({ queryKey: ["lab", key], queryFn: get<T>(`/lab/${key}`), retry: false });
}

export default function Lab() {
  return (
    <div className="mx-auto max-w-[1200px] space-y-14 px-4 pb-20 pt-20 md:px-10">
      <header>
        <h1 className="font-display text-3xl font-extrabold">Research Lab</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted">
          How the engine is built and how well it works. Every number on this page is read from a file in
          <code className="mx-1 rounded bg-surface-2 px-1">artifacts/</code>produced by the offline pipeline.
        </p>
      </header>
      <Models />
      <Comparison />
      <Weights />
      <ColdStart />
      <NewMovies />
      <Diversity />
      <Calibration />
      <CatalogAudit />
      <UserInspector />
      <Shilling />
      <TasteMap />
      <Ncf />
    </div>
  );
}

function Section({ title, children, note }: { title: string; children: React.ReactNode; note?: string }) {
  return (
    <section>
      <h2 className="font-display text-xl font-bold">{title}</h2>
      {note && <p className="mt-1 max-w-3xl text-sm text-muted">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

const Missing = ({ q }: { q: { isError: boolean } }) => (q.isError ? <p className="text-sm text-muted">Not produced yet (run the pipeline).</p> : null);

function Models() {
  const q = useLab<Record<string, Record<string, unknown>>>("models");
  return (
    <Section title="Models" note="Each model and its settings, tuned on the validation split.">
      <Missing q={q} />
      <div className="grid gap-3 md:grid-cols-2">
        {q.data && Object.entries(q.data).map(([k, s]) => (
          <div key={k} className="rounded-lg bg-surface p-4 text-sm">
            <div className="font-semibold">{NAMES[k] ?? k}</div>
            <div className="mt-1 text-xs text-muted">
              {Object.entries(s).filter(([, v]) => typeof v !== "object").map(([kk, v]) => `${kk} = ${v}`).join(" · ")}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Comparison() {
  const q = useLab<Record<string, { ranking?: Record<string, { ranking?: unknown }>; [k: string]: unknown }>>("metrics");
  const [split, setSplit] = useState<"test_comparison" | "global_cutoff">("test_comparison");
  const data = q.data?.[split] as undefined | { ranking: Record<string, Record<string, CI | number>>; ratings: Record<string, { rmse: CI; mae: CI }>; evaluated_users: number };
  const fmt = (c: CI) => `${c.mean.toFixed(4)} [${c.ci_low.toFixed(4)}, ${c.ci_high.toFixed(4)}]`;
  return (
    <Section title="Model comparison" note="Full ranking over every MovieLens film the user has not rated. Brackets: 95% bootstrap confidence intervals over users. A gap is only claimed when the intervals do not overlap.">
      <div className="mb-3 flex gap-2">
        {(["test_comparison", "global_cutoff"] as const).map((s) => (
          <button key={s} onClick={() => setSplit(s)} className={`rounded-full px-3 py-1 text-sm ${split === s ? "bg-white text-black" : "text-white/75 hover:bg-white/10"}`}>
            {s === "test_comparison" ? "Per-user time split (test)" : "Global time cutoff"}
          </button>
        ))}
      </div>
      {!data ? <p className="text-sm text-muted">Not produced yet.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="text-xs text-muted"><tr>{["Model", "P@10", "R@10", "MAP@10", "NDCG@10", "Coverage", "Diversity", "Long tail"].map((h) => <th key={h} className="py-2 pr-4 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {Object.entries(data.ranking).map(([k, r]) => (
                <tr key={k} className="border-t border-white/5">
                  <td className="py-2 pr-4 font-medium">{NAMES[k] ?? k}</td>
                  {["precision", "recall", "map", "ndcg"].map((m) => <td key={m} className="py-2 pr-4 tabular-nums">{fmt(r[m] as CI)}</td>)}
                  <td className="py-2 pr-4 tabular-nums">{(100 * (r.coverage as number)).toFixed(1)}%</td>
                  <td className="py-2 pr-4 tabular-nums">{(r.diversity as CI).mean.toFixed(3)}</td>
                  <td className="py-2 pr-4 tabular-nums">{(r.long_tail_share as number).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-muted">
            RMSE: {Object.entries(data.ratings).map(([k, v]) => `${NAMES[k] ?? k} ${fmt(v.rmse)}`).join(" · ")} · {data.evaluated_users.toLocaleString()} evaluated users
          </p>
        </div>
      )}
    </Section>
  );
}

function Weights() {
  const q = useLab<Record<string, Record<string, number>>>("weights");
  const sources = ["popularity", "content", "item_cf", "user_cf", "svd", "als"];
  return (
    <Section title="Hybrid weights per user stage" note="Tuned by grid search on validation NDCG@10 using simulated users (onboarding = 5 earliest films rated 8+).">
      <Missing q={q} />
      {q.data && (
        <table className="text-sm">
          <thead className="text-xs text-muted"><tr><th className="py-2 pr-6 text-left font-medium">Stage</th>{sources.map((s) => <th key={s} className="py-2 pr-6 text-left font-medium">{NAMES[s]}</th>)}</tr></thead>
          <tbody>{Object.entries(q.data).map(([stage, w]) => (
            <tr key={stage} className="border-t border-white/5"><td className="py-2 pr-6 capitalize">{stage}</td>
              {sources.map((s) => <td key={s} className="py-2 pr-6 tabular-nums">{(w[s] ?? 0).toFixed(2)}</td>)}</tr>
          ))}</tbody>
        </table>
      )}
    </Section>
  );
}

function ColdStart() {
  const q = useLab<{ k_values: number[]; results: Record<string, Record<string, number>> }>("cold-start");
  const models = ["hybrid_balanced", "popularity", "content", "item_cf", "svd", "als"];
  const series = q.data ? models.flatMap((m, i) => [true, false].map((withOb) => ({
    name: `${NAMES[m]} ${withOb ? "(with onboarding)" : "(without)"}`, dashed: !withOb, color: COLORS[i],
    points: q.data!.k_values.map((k) => [k, q.data!.results[`k${k}_${withOb ? "with" : "without"}_onboarding`][m]] as [number, number]),
  }))) : [];
  return (
    <Section title="Cold start" note="NDCG@10 against the number of real ratings the system knows. Solid lines include simulated onboarding (5 picked films); dashed lines do not. The gap is what onboarding is worth.">
      <Missing q={q} />
      {q.data && <LineChart series={series} xLabel="Known behavioral ratings (k)" yLabel="NDCG@10" />}
    </Section>
  );
}

function NewMovies() {
  const q = useLab<{ results: Record<string, { hit_rate_at_50: number }>; random_baseline_hit_rate: number; users: number; holdout_films: number }>("new-movies");
  return (
    <Section title="New movies" note="500 MovieLens films had every rating removed from training. Hit rate@50: how often a held-out film the user later rated 7+ appears in their top 50. Collaborative models cannot recommend a film nobody has rated.">
      <Missing q={q} />
      {q.data && (
        <div className="space-y-2">
          {Object.entries(q.data.results).map(([k, v]) => {
            const max = Math.max(...Object.values(q.data!.results).map((r) => r.hit_rate_at_50), 0.0001);
            return (
              <div key={k} className="flex items-center gap-3 text-sm">
                <span className="w-44 shrink-0">{NAMES[k] ?? k}</span>
                <div className="h-3 flex-1 rounded bg-white/5"><div className="h-3 rounded bg-white/80" style={{ width: `${(v.hit_rate_at_50 / max) * 100}%` }} /></div>
                <span className="w-20 text-right tabular-nums">{(100 * v.hit_rate_at_50).toFixed(2)}%</span>
              </div>
            );
          })}
          <p className="text-xs text-muted">Random top-50 would hit {(100 * q.data.random_baseline_hit_rate).toFixed(2)}% · {q.data.users.toLocaleString()} users · {q.data.holdout_films} held-out films</p>
        </div>
      )}
    </Section>
  );
}

function Diversity() {
  const q = useLab<{ sweep: { lambda: number; ndcg: number; diversity: number }[]; modes: Record<string, { ndcg: number; diversity: number }> }>("diversity");
  return (
    <Section title="Diversity trade-off" note="MMR with lambda from 0.5 to 1.0: lower lambda gives more varied lists at some cost in NDCG@10. The three Discovery Modes are marked.">
      <Missing q={q} />
      {q.data && <ScatterChart xLabel="Intra-list diversity" yLabel="NDCG@10" points={q.data.sweep.map((p) => ({ x: p.diversity, y: p.ndcg }))}
        marks={Object.entries(q.data.modes).map(([m, v]) => ({ x: v.diversity, y: v.ndcg, label: m[0].toUpperCase() + m.slice(1) }))} />}
    </Section>
  );
}

function Calibration() {
  const q = useLab<{ stages: Record<string, { ece: number; passes: boolean; bins: { predicted: number; observed: number; n: number }[]; mean_match_pct: number }> }>("calibration");
  return (
    <Section title="Match % calibration" note="Predicted probability of a 7+ rating against the share actually rated 7+, on the test split. Close to the diagonal means Match % can be trusted.">
      <Missing q={q} />
      {q.data && (
        <div className="grid gap-6 md:grid-cols-3">
          {Object.entries(q.data.stages).map(([s, v]) => (
            <div key={s} className="rounded-lg bg-surface p-4">
              <div className="text-sm font-semibold capitalize">{s}</div>
              <div className="text-xs text-muted">ECE {v.ece.toFixed(3)} · {v.passes ? "passes" : "does not pass"} · mean Match {v.mean_match_pct.toFixed(0)}%</div>
              <LineChart width={320} height={220} xLabel="predicted" yLabel="observed"
                series={[{ name: "observed", color: "#ffffff", points: v.bins.map((b) => [Number(b.predicted.toFixed(2)), b.observed]) },
                         { name: "perfect", color: "#a7a7a7", dashed: true, points: v.bins.map((b) => [Number(b.predicted.toFixed(2)), b.predicted]) }]} />
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function CatalogAudit() {
  const q = useLab<{ catalog_by_part: Record<string, number>; catalog_total: number; catalog_by_language: Record<string, number>; coverage_top_500_us: { pct: number; in_catalog: number }; coverage_top_1000_us: { pct: number; in_catalog: number } }>("catalog-audit");
  const PARTS: Record<string, string> = { A: "MovieLens backbone", B: "International enrichment", C: "Recent releases", D: "Hollywood enrichment" };
  return (
    <Section title="Catalog audit" note="What the website can show (the product catalog). Models are evaluated on part A only.">
      <Missing q={q} />
      {q.data && (
        <div className="grid gap-6 md:grid-cols-3 text-sm">
          <div className="rounded-lg bg-surface p-4">{Object.entries(q.data.catalog_by_part).map(([k, v]) => <div key={k} className="flex justify-between py-0.5"><span>{PARTS[k] ?? k}</span><span className="tabular-nums">{v.toLocaleString()}</span></div>)}
            <div className="mt-2 flex justify-between border-t border-white/10 pt-2 font-semibold"><span>Total</span><span>{q.data.catalog_total.toLocaleString()}</span></div></div>
          <div className="rounded-lg bg-surface p-4">{Object.entries(q.data.catalog_by_language).slice(0, 12).map(([k, v]) => <div key={k} className="flex justify-between py-0.5"><span>{k}</span><span className="tabular-nums">{v.toLocaleString()}</span></div>)}</div>
          <div className="rounded-lg bg-surface p-4">
            <div>Top 500 US films in the catalog: <b>{q.data.coverage_top_500_us.pct}%</b></div>
            <div className="mt-1">Top 1,000 US films: <b>{q.data.coverage_top_1000_us.pct}%</b></div>
            <p className="mt-2 text-xs text-muted">Measured from TMDB vote counts; the full list of missing films and reasons is in docs/catalog-audit.md.</p>
          </div>
        </div>
      )}
    </Section>
  );
}

function UserInspector() {
  const [uid, setUid] = useState("");
  const q = useQuery({ queryKey: ["lab", "user", uid], queryFn: get<{ stage: string; behavioral_count: number; onboarding_count: number; weights: Record<string, number>;
    items: { movie_id: number; title: string; final_score: number; match_pct: number; shares: Record<string, number>; reasons: { text: string }[] }[] }>(`/lab/user/${uid}/candidates`), enabled: !!uid, retry: false });
  return (
    <Section title="User Inspector" note="Enter your own user id (signed in) or the demo account's id to see their stage, counts, and for each recommended film the per-source share of the score, the final score, Match % and the reasons shown on the site.">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setUid((e.currentTarget.elements.namedItem("uid") as HTMLInputElement).value); }}>
        <input name="uid" placeholder="User id" className="w-32 rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm" />
        <button className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-black">Inspect</button>
      </form>
      {q.isError && <p className="mt-3 text-sm text-muted">You can only inspect your own account (sign in first) or the demo account.</p>}
      {q.data && (
        <div className="mt-4 overflow-x-auto">
          <p className="text-sm">Stage <b className="capitalize">{q.data.stage}</b> · behavioral count {q.data.behavioral_count} · onboarding {q.data.onboarding_count}</p>
          <table className="mt-3 w-full min-w-[800px] text-sm">
            <thead className="text-xs text-muted"><tr><th className="py-2 text-left font-medium">Film</th><th className="text-left font-medium">Score</th><th className="text-left font-medium">Match</th><th className="text-left font-medium">Source shares</th><th className="text-left font-medium">Reasons</th></tr></thead>
            <tbody>{q.data.items.map((it) => (
              <tr key={it.movie_id} className="border-t border-white/5 align-top">
                <td className="py-2 pr-4">{it.title}</td><td className="pr-4 tabular-nums">{it.final_score.toFixed(3)}</td><td className="pr-4">{it.match_pct}%</td>
                <td className="pr-4 text-xs text-muted">{Object.entries(it.shares).filter(([, v]) => v > 0.01).map(([k, v]) => `${NAMES[k] ?? k} ${(100 * v).toFixed(0)}%`).join(" · ")}</td>
                <td className="text-xs">{it.reasons.map((r) => r.text).join(" · ")}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
function Shilling() {
  type Res = { prediction_shift: number; hit_ratio_before: number; hit_ratio_after: number };
  const q = useLab<{ results: { attack: string; size: number; fake_profiles: number; attacked: Record<string, Res>; defended: Record<string, Res>;
    detection: { precision: number; recall: number; false_positive_rate: number; real_users_removed: number } }[] }>("shilling");
  return (
    <Section title="Shilling attack and defense (advanced)" note="Fake profiles push 5 little-known films. Prediction shift = how much the predicted rating of the targets rose (1-10 scale); hit ratio = share of real users who get a target in their top 10. The defense flags unusual profiles, removes them and retrains. Lab only: nothing on the website can be attacked.">
      <Missing q={q} />
      {q.data && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="text-xs text-muted"><tr>
              {["Attack", "Fake profiles", "Model", "Shift (attacked)", "Hit ratio before → attacked", "Shift (defended)", "Detection P / R", "Real users removed"].map((h) => <th key={h} className="py-2 pr-4 text-left font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {q.data.results.flatMap((r) => Object.keys(r.attacked).map((m, i) => (
                <tr key={`${r.attack}${r.size}${m}`} className={i === 0 ? "border-t border-white/10" : ""}>
                  <td className="py-1.5 pr-4">{i === 0 ? `${r.attack}, ${(r.size * 100).toFixed(0)}%` : ""}</td>
                  <td className="pr-4 tabular-nums">{i === 0 ? r.fake_profiles : ""}</td>
                  <td className="pr-4">{NAMES[m] ?? m}</td>
                  <td className="pr-4 tabular-nums">{r.attacked[m].prediction_shift.toFixed(2)}</td>
                  <td className="pr-4 tabular-nums">{(100 * r.attacked[m].hit_ratio_before).toFixed(1)}% → {(100 * r.attacked[m].hit_ratio_after).toFixed(1)}%</td>
                  <td className="pr-4 tabular-nums">{r.defended[m].prediction_shift.toFixed(2)}</td>
                  <td className="pr-4 tabular-nums">{i === 0 ? `${(100 * r.detection.precision).toFixed(0)}% / ${(100 * r.detection.recall).toFixed(0)}%` : ""}</td>
                  <td className="tabular-nums">{i === 0 ? r.detection.real_users_removed : ""}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function TasteMap() {
  const [uid, setUid] = useState("");
  const q = useQuery({ queryKey: ["lab", "taste", uid], retry: false,
    queryFn: get<{ points: { x: number; y: number; title: string; genre: string }[]; explained_variance_ratio: number[]; you?: { x: number; y: number; ratings_used: number } }>(`/lab/taste-map${uid ? `?user_id=${uid}` : ""}`) });
  const [hover, setHover] = useState<string | null>(null);
  if (q.isError) return <Section title="Taste map (advanced)"><p className="text-sm text-muted">{uid ? "You can only place your own account (sign in first) or the demo account." : "Not produced yet."}</p>{uid && <button className="mt-2 text-sm underline" onClick={() => setUid("")}>Show the map without a user</button>}</Section>;
  const pts = q.data?.points ?? [];
  const genres = Array.from(new Set(pts.map((p) => p.genre))).slice(0, 8);
  const color = (g: string) => COLORS[genres.indexOf(g)] ?? "#555";
  const xs = pts.map((p) => p.x).concat(q.data?.you ? [q.data.you.x] : []), ys = pts.map((p) => p.y).concat(q.data?.you ? [q.data.you.y] : []);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const W = 700, H = 460, sx = (x: number) => 10 + ((x - x0) / (x1 - x0 || 1)) * (W - 20), sy = (y: number) => H - 10 - ((y - y0) / (y1 - y0 || 1)) * (H - 20);
  return (
    <Section title="Taste map (advanced)" note={`PCA of the SVD film vectors to 2D, colored by main genre. A user is placed with the same projection. The two axes explain ${q.data ? (100 * q.data.explained_variance_ratio[0]).toFixed(1) : "–"}% and ${q.data ? (100 * q.data.explained_variance_ratio[1]).toFixed(1) : "–"}% of the variance, so it is a rough picture of the model, not a recommender.`}>
      <form className="mb-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); setUid((e.currentTarget.elements.namedItem("tuid") as HTMLInputElement).value); }}>
        <input name="tuid" placeholder="Place user id" className="w-36 rounded-md border border-white/15 bg-surface-2 px-3 py-2 text-sm" />
        <button className="rounded-md border border-white/20 px-4 py-2 text-sm">Place</button>
        {hover && <span className="self-center text-sm text-muted">{hover}</span>}
      </form>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg bg-surface" role="img" aria-label="Taste map">
        {pts.map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r="2.2" fill={color(p.genre)} opacity="0.75" onMouseEnter={() => setHover(`${p.title} · ${p.genre}`)} />)}
        {q.data?.you && <g><circle cx={sx(q.data.you.x)} cy={sy(q.data.you.y)} r="8" fill="none" stroke="#C8102E" strokeWidth="3" /><text x={sx(q.data.you.x) + 12} y={sy(q.data.you.y) + 4} fill="#fff" fontSize="14" fontWeight="600">You</text></g>}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted">{genres.map((g) => <span key={g} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: color(g) }} />{g}</span>)}</div>
    </Section>
  );
}

function Ncf() {
  const q = useLab<{ ranking: Record<string, CI | number>; compare_ndcg: Record<string, number>; evaluated_users: number }>("ncf");
  return (
    <Section title="Neural Collaborative Filtering (advanced)" note="NeuMF (GMF + MLP) trained on positives with 4 sampled negatives, evaluated with exactly the same full-ranking protocol on the test split. Lab only: it has no cheap fold-in for new users, so the website never serves it.">
      <Missing q={q} />
      {q.data && (
        <p className="text-sm">
          NCF NDCG@10 <b>{(q.data.ranking.ndcg as CI).mean.toFixed(4)}</b> [{(q.data.ranking.ndcg as CI).ci_low.toFixed(4)}, {(q.data.ranking.ndcg as CI).ci_high.toFixed(4)}]
          {" "}· for comparison: {Object.entries(q.data.compare_ndcg).map(([k, v]) => `${NAMES[k] ?? k} ${v.toFixed(4)}`).join(" · ")}
        </p>
      )}
    </Section>
  );
}