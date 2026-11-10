import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { PageMessage } from "../components/Loading";

type Day = { day: string; signups: number; active: number; ratings: number };
type Stats = {
  accounts: number; guests: number; signups_7d: number; signups_30d: number;
  active_accounts: { day: number; week: number; month: number };
  active_guests: { day: number; week: number; month: number };
  returning_accounts_7d: number; ratings_7d: number; imported_ratings_total: number;
  database_bytes: number; database_limit_bytes: number;
  daily: Day[]; top_films_7d: { id: number; title: string; people: number }[];
};

function Tile({ label, value, note }: { label: string; value: number | string; note?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-surface p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 font-display text-3xl font-extrabold tabular-nums">{value}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}

/** One bar per day for the last 30 days; the newest day is on the right. */
function Bars({ title, days, pick }: { title: string; days: Day[]; pick: (d: Day) => number }) {
  const max = Math.max(1, ...days.map(pick));
  const total = days.reduce((s, d) => s + pick(d), 0);
  return (
    <section className="rounded-xl border border-white/10 bg-surface p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-muted">max {max} a day · {total} in 30 days</span>
      </div>
      <div className="mt-3 flex h-24 items-end gap-[3px]" role="img" aria-label={`${title}, last 30 days`}>
        {days.map((d) => (
          <div key={d.day} title={`${d.day}: ${pick(d)}`} className="flex-1 rounded-t-sm bg-accent/80"
            style={{ height: `${Math.max(pick(d) ? 4 : 1, (pick(d) / max) * 100)}%`, opacity: pick(d) ? 1 : 0.25 }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted"><span>{days[0]?.day}</span><span>today</span></div>
    </section>
  );
}

const mb = (b: number) => `${Math.round(b / 1024 / 1024)} MB`;

/** Private usage numbers for the site owner. Hidden (404) for everyone else; see ADMIN_EMAILS in docs/deploy.md. */
export default function StatsPage() {
  const q = useQuery({ queryKey: ["admin-stats"], queryFn: () => api<Stats>("/admin/stats"), retry: false, refetchInterval: 60_000 });
  if (q.isLoading) return <PageMessage title="Loading" />;
  if (q.error) {
    const hidden = q.error instanceof ApiError && q.error.status === 404;
    return <PageMessage title={hidden ? "Page not found" : "Could not load the numbers"}>{hidden ? <Link to="/" className="underline">Go home</Link> : null}</PageMessage>;
  }
  const s = q.data!;
  const used = s.database_bytes / s.database_limit_bytes;
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 pb-24 pt-20 md:px-10">
      <div>
        <h1 className="font-display text-3xl font-extrabold">Usage</h1>
        <p className="mt-1 text-sm text-muted">Only you can see this page. Totals only, never what one person watched. Updates every minute.</p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Accounts" value={s.accounts} note={`+${s.signups_7d} this week, +${s.signups_30d} in 30 days`} />
        <Tile label="Active accounts this week" value={s.active_accounts.week} note={`${s.active_accounts.day} today, ${s.active_accounts.month} in 30 days`} />
        <Tile label="Came back on 2+ days this week" value={s.returning_accounts_7d} note="The number that matters most" />
        <Tile label="Active guests this week" value={s.active_guests.week} note={`${s.guests} guest sessions stored`} />
        <Tile label="Ratings this week" value={s.ratings_7d} />
        <Tile label="Imported ratings (all time)" value={s.imported_ratings_total} />
        <Tile label="Database used" value={`${Math.round(used * 100)}%`} note={`${mb(s.database_bytes)} of ${mb(s.database_limit_bytes)} on Neon free`} />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Bars title="New accounts" days={s.daily} pick={(d) => d.signups} />
        <Bars title="Active people" days={s.daily} pick={(d) => d.active} />
        <Bars title="Ratings" days={s.daily} pick={(d) => d.ratings} />
      </div>
      <section className="rounded-xl border border-white/10 bg-surface p-4">
        <h2 className="text-sm font-semibold">Most opened films this week</h2>
        {s.top_films_7d.length === 0 ? <p className="mt-2 text-sm text-muted">Nothing yet.</p> : (
          <ol className="mt-2 space-y-1 text-sm">
            {s.top_films_7d.map((f, i) => (
              <li key={f.id} className="flex justify-between gap-4">
                <Link to={`/movie/${f.id}`} className="hover:underline">{i + 1}. {f.title}</Link>
                <span className="tabular-nums text-muted">{f.people} {f.people === 1 ? "person" : "people"}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
