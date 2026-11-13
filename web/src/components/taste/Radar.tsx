export type RadarPoint = { key: string; label: string; you: number; catalog: number };

const LINE = 14;

/** Side labels with two or more words go on two lines so they stay narrow; top and bottom labels stay on one. */
function lines(label: string, side: boolean): string[] {
  const words = label.split(" ");
  if (!side || words.length < 2) return [label];
  const cut = Math.ceil(words.length / 2);
  return [words.slice(0, cut).join(" "), words.slice(cut).join(" ")];
}

/** Radar of your trait levels (red) against the catalog average (grey outline). Values are 0-100.
 *  The drawing area is wider than the chart so long side labels ("Psychological tension") are never cut off. */
export default function Radar({ points }: { points: RadarPoint[] }) {
  const w = 480, h = 340, cx = w / 2, cy = h / 2, r = 112, n = points.length;
  const at = (i: number, v: number) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2;
    return [cx + Math.cos(a) * r * (v / 100), cy + Math.sin(a) * r * (v / 100)] as const;
  };
  const poly = (vals: number[]) => vals.map((v, i) => at(i, v).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" className="mx-auto w-full max-w-[520px] overflow-visible"
      aria-label={`Taste radar: ${points.map((p) => `${p.label} ${p.you} out of 100`).join(", ")}`}>
      {[25, 50, 75, 100].map((g) => <polygon key={g} points={poly(points.map(() => g))} fill="none" stroke="#ffffff1a" />)}
      {points.map((_, i) => { const [x, y] = at(i, 100); return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#ffffff1a" />; })}
      <polygon points={poly(points.map((p) => p.catalog))} fill="none" stroke="#ffffff66" strokeDasharray="4 4" />
      <polygon points={poly(points.map((p) => p.you))} fill="#c8102e55" stroke="#e0263f" strokeWidth="2" />
      {points.map((p, i) => {
        const [x, y] = at(i, 116);
        const anchor = x < cx - 4 ? "end" : x > cx + 4 ? "start" : "middle";
        const ls = lines(p.label, anchor !== "middle");
        const top = y - ((ls.length - 1) * LINE) / 2;
        return (
          <text key={p.key} x={x} y={top} fontSize="13" fill="#d4d4d4" textAnchor={anchor} dominantBaseline="middle">
            {ls.length === 1 ? p.label : ls.map((t, j) => <tspan key={j} x={x} dy={j === 0 ? 0 : LINE}>{t}</tspan>)}
          </text>
        );
      })}
    </svg>
  );
}
