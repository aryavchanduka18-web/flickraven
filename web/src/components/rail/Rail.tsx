import { useEffect, useRef, useState } from "react";
import type { RecItem } from "../../api/types";
import { CARD_VISIBLE, ROW_VISIBLE, record, useDwell } from "../../lib/impressions";
import MovieCard from "../card/MovieCard";

type Props = {
  title: string; subtitle?: string; items: RecItem[]; source: string; personal?: boolean;
  /** Home film rows: lets the person hide the row, and says when it moved because of their use. */
  onHide?: () => void; learned?: "up" | "down" | null;
  /** The row's place on the page (for impressions). */
  slot?: number;
};

/** One horizontal rail. Card width gives about 2-3 large cards on desktop with the next one peeking,
 *  about 2 on tablet and 1-1.5 on phones (spec 8.4). Vertical padding keeps hovered cards unclipped. */
export default function Rail({ title, subtitle, items, source, personal = true, onHide, learned, slot }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const section = useRef<HTMLElement>(null);
  // The row counts as seen when half of it has been on screen for a second. Not seen, not counted: never a "no".
  useDwell(section, () => record({ surface: source, kind: "row", position: slot, visible_ms: 1000 }),
    { threshold: ROW_VISIBLE, key: items.length > 0 });
  const [edge, setEdge] = useState({ start: true, end: false });

  const update = () => {
    const el = scroller.current;
    if (!el) return;
    setEdge({ start: el.scrollLeft < 8, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 8 });
  };
  useEffect(update, [items.length]);

  const scrollBy = (dir: number) => {
    const el = scroller.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: "smooth" });
  };

  if (!items.length) return null;
  return (
    <section ref={section} className="group/rail relative" aria-label={title}>
      <div className="mb-1 flex items-baseline gap-3 px-4 md:px-10">
        <h2 className="font-display text-lg font-bold md:text-xl">{title}</h2>
        {learned && (
          <span className="rounded-full border border-white/15 px-2 py-0.5 text-[11px] text-muted"
            title="Rows move from how you use them: ones you open and like go up, ones you skip go down.">
            {learned === "up" ? "Moved up: you use this row" : "Moved down: you skip this row"}
          </span>
        )}
        {onHide && (
          <button onClick={onHide} className="ml-auto text-xs text-muted hover:text-white" aria-label={`Show fewer rows like ${title}`}>
            Hide row
          </button>
        )}
      </div>
      {subtitle && <p className="-mt-0.5 mb-1 px-4 text-xs text-muted md:px-10">{subtitle}</p>}
      <div
        ref={scroller}
        onScroll={update}
        className="no-scrollbar flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-28 pt-3 -mb-24 md:scroll-px-10 md:gap-4 md:px-10"
      >
        {items.map((it, i) => (
          <SeenCard key={it.movie.id} movieId={it.movie.id} source={source} position={i}>
            <MovieCard item={it} source={source} position={i} personal={personal} />
          </SeenCard>
        ))}
      </div>
      <RailArrow side="left" hidden={edge.start} onClick={() => scrollBy(-1)} />
      <RailArrow side="right" hidden={edge.end} onClick={() => scrollBy(1)} />
    </section>
  );
}

/** A card counts once 60% of it is inside the page and the row's scroll window for a second (the browser clips
 *  cards scrolled out of the row's window, so they do not count). */
function SeenCard({ movieId, source, position, children }: { movieId: number; source: string; position: number; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useDwell(ref, () => record({ surface: source, kind: "card", movie_id: movieId, position, visible_ms: 1000 }), { threshold: CARD_VISIBLE });
  return (
    <div ref={ref} className="w-[78vw] shrink-0 snap-start sm:w-[calc((100vw-var(--sb))*0.46)] lg:w-[calc((100vw-var(--sb))*0.38)] xl:w-[calc((100vw-var(--sb))*0.34)] 2xl:w-[calc((100vw-var(--sb))*0.30)]">
      {children}
    </div>
  );
}

function RailArrow({ side, hidden, onClick }: { side: "left" | "right"; hidden: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label={side === "left" ? "Scroll left" : "Scroll right"}
      tabIndex={hidden ? -1 : 0}
      className={`glass-btn absolute top-[calc(50%-3rem)] z-30 hidden h-[46px] w-[46px] rounded-full transition-opacity duration-300 md:inline-flex ${
        hidden ? "pointer-events-none opacity-0" : "opacity-90 hover:opacity-100"
      } ${side === "left" ? "left-3" : "right-3"}`}
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
        <path d={side === "left" ? "m15 6-6 6 6 6" : "m9 6 6 6-6 6"} />
      </svg>
    </button>
  );
}