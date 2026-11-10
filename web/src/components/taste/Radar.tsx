export type RadarPoint = { key: string; label: string; you: number; catalog: number };

/** Radar of your trait levels (red) against the catalog average (grey outline). Values are 0-100. */
export default function Radar({ points }: { points: RadarPoint[] }) {
  const size = 340, c = size / 2, r = 112, n = points.length;
  const at = (i: number, v: number) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2;
    return [c + Math.cos(a) * r * (v / 100), c + Math.sin(a) * r * (v / 100)] as const;
  };
  const poly = (vals: number[]) => vals.map((v, i) => at(i, v).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${size} ${size}`} role="img" className="mx-auto w-full max-w-[420px]"
      aria-label={`Taste radar: ${points.map((p) => `${p.label} ${p.you} out of 100`).join(", ")}`}>
      {[25, 50, 75, 100].map((g) => <polygon key={g} points={poly(points.map(() => g))} fill="none" stroke="#ffffff1a" />)}
      {points.map((_, i) => { const [x, y] = at(i, 100); return <line key={i} x1={c} y1={c} x2={x} y2={y} stroke="#ffffff1a" />; })}
      <polygon points={poly(points.map((p) => p.catalog))} fill="none" stroke="#ffffff66" strokeDasharray="4 4" />
      <polygon points={poly(points.map((p) => p.you))} fill="#c8102e55" stroke="#e0263f" strokeWidth="2" />
      {points.map((p, i) => {
        const [x, y] = at(i, 122);
        return <text key={p.key} x={x} y={y} fontSize="11" fill="#d4d4d4" textAnchor={x < c - 4 ? "end" : x > c + 4 ? "start" : "middle"} dominantBaseline="middle">{p.label}</text>;
      })}
    </svg>
  );
}
