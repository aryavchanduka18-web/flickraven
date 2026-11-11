import ImdbScore from "../../components/movie/ImdbScore";
import TypeBadge from "../../components/movie/TypeBadge";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { MovieDetail, RecItem } from "../../api/types";
import { useCanHover } from "../../hooks/useCanHover";
import { agreementLabel } from "../../lib/confidence";
import { backdropSrcSet, tmdbImage } from "../../lib/tmdb";
import { languageName } from "../../lib/format";
import ActionButtons from "../feedback/ActionButtons";
import { useUI } from "../layout/ui";

type Props = { item: RecItem; source: string; position: number; personal?: boolean };

export function CardArtwork({ item, eager = false }: { item: RecItem; eager?: boolean }) {
  const m = item.movie;
  const img = m.backdrop ? tmdbImage(m.backdrop, "w780") : tmdbImage(m.poster, "w500");
  return (
    <div className="relative aspect-video overflow-hidden rounded-md bg-surface-2" style={m.dominant_color ? { backgroundColor: m.dominant_color } : undefined}>
      {img && (
        <img
          src={img}
          srcSet={m.backdrop ? backdropSrcSet(m.backdrop) : undefined}
          sizes="(min-width: 1536px) 30vw, (min-width: 1280px) 34vw, (min-width: 1024px) 38vw, (min-width: 640px) 46vw, 78vw"
          alt=""
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          className={`h-full w-full object-cover ${m.backdrop ? "" : "scale-110 blur-sm"}`}
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/25 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 p-3 md:p-4">
        {m.logo ? (
          <img src={tmdbImage(m.logo, "w500")} alt={m.title} className="max-h-12 max-w-[60%] object-contain object-left drop-shadow md:max-h-16" loading="lazy" />
        ) : (
          <h3 className="font-display text-lg font-bold leading-tight drop-shadow md:text-xl">{m.title}</h3>
        )}
      </div>
    </div>
  );
}

export function CardMeta({ item, personal }: { item: RecItem; personal?: boolean }) {
  const m = item.movie;
  return (
    <div className="mt-2">
      {/* Match % leads; model agreement is a quiet footnote to it (details on the film page and in Why?). */}
      {personal && item.match_pct != null && (
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-extrabold leading-tight text-accent">{item.match_pct}% match</span>
          {agreementLabel(item.agreement) && (
            <span className="text-[10px] text-muted" title={`Model agreement ${item.agreement}%`}>
              {agreementLabel(item.agreement)!.toLowerCase()} agreement
            </span>
          )}
        </div>
      )}
      <div className="flex items-center gap-2 text-[13px] text-muted">
        {m.year && <span>{m.year}</span>}
        <TypeBadge type={m.title_type} />
        <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
        {m.language && <span>{languageName(m.language)}</span>}
      </div>
    </div>
  );
}

const detailQuery = (id: number) => ({
  queryKey: ["movie", id],
  queryFn: () => api<MovieDetail>(`/movies/${id}`),
  staleTime: 60_000,
});
const INTENT_MS = 200;          // hover intent: no flicker when the pointer crosses a rail
const MAX_WAIT_MS = 600;        // open with placeholders if the details take longer than this

export default function MovieCard({ item, source, position, personal = true }: Props) {
  const canHover = useCanHover();
  const navigate = useNavigate();
  const { openQuickView } = useUI();
  const [hover, setHover] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const card = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const m = item.movie;
  const qc = useQueryClient();
  const reduce = useReducedMotion();
  const inside = useRef(false);
  const close = () => {
    window.clearTimeout(timer.current);
    setHover(false);
  };
  // While the details are open, the wheel over the card or the details scrolls only the details: never the
  // page, never the rail. A page scroll from elsewhere (keyboard, scrollbar) closes them.
  useEffect(() => {
    if (!hover) return;
    const el = card.current;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (body.current) body.current.scrollTop += e.deltaY;
    };
    el?.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("scroll", close, { passive: true });
    window.addEventListener("resize", close);
    return () => {
      el?.removeEventListener("wheel", onWheel);
      window.removeEventListener("scroll", close);
      window.removeEventListener("resize", close);
    };
  }, [hover]);
  const open = () => navigate(`/movie/${m.id}`, { state: { source, position } });

  return (
    <motion.div
      ref={card}
      className="relative"
      onMouseEnter={() => {
        if (!canHover) return;
        inside.current = true;
        window.clearTimeout(timer.current);
        // Start loading the details now, and open only when they are in (or after MAX_WAIT_MS), so the
        // panel appears once, at its final size, instead of growing when the details arrive.
        const ready = qc.prefetchQuery(detailQuery(m.id));
        const started = Date.now();
        timer.current = window.setTimeout(() => {
          const wait = new Promise((r) => window.setTimeout(r, Math.max(0, MAX_WAIT_MS - (Date.now() - started))));
          Promise.race([ready, wait]).then(() => {
            if (inside.current) setHover(true);
          });
        }, INTENT_MS);
      }}
      onMouseLeave={() => {
        inside.current = false;
        // A short grace period lets the pointer move from the card onto the details below it.
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setHover(false), 120);
      }}
      style={{ zIndex: hover ? 20 : 1 }}
    >
      {/* The artwork zooms inside its frame; the card itself keeps its size, so the details stay attached. */}
      <button onClick={open} className="block w-full overflow-hidden rounded-md text-left" aria-label={`${m.title}${m.year ? ` (${m.year})` : ""}`}>
        <motion.div animate={{ scale: hover && !reduce ? 1.04 : 1 }} transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}>
          <CardArtwork item={item} />
        </motion.div>
      </button>
      <div className="flex items-start justify-between gap-2">
        <CardMeta item={item} personal={personal} />
        {!canHover && (
          <button
            onClick={() => openQuickView(item)}
            className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/25 text-white"
            aria-label={`Quick view ${m.title}`}
          >
            <Chevron />
          </button>
        )}
      </div>
      {createPortal(
        <AnimatePresence>
          {hover && card.current && (
            <HoverDetails item={item} source={source} anchor={card.current} body={body}
              onEnter={() => {
                inside.current = true;
                window.clearTimeout(timer.current);
              }}
              onLeave={() => {
                inside.current = false;
                close();
              }} />
          )}
        </AnimatePresence>,
        document.body,
      )}
    </motion.div>
  );
}

/** The details under a hovered card, rendered in a portal on top of everything (no rail can clip it), placed
 *  under the card and never taller than the space left on screen. The mouse wheel scrolls only its body. */
function HoverDetails({ item, source, anchor, body, onEnter, onLeave }: {
  item: RecItem; source: string; anchor: HTMLElement; body: RefObject<HTMLDivElement | null>;
  onEnter: () => void; onLeave: () => void;
}) {
  const { openQuickView, openWhy } = useUI();
  const navigate = useNavigate();
  const m = item.movie;
  const panel = useRef<HTMLDivElement>(null);
  const detail = useQuery(detailQuery(m.id));
  const reduce = useReducedMotion();
  const [place, setPlace] = useState(() => placement(anchor));
  // Follow the card: re-measure on any scroll (page or rail) and on resize.
  useLayoutEffect(() => {
    const update = () => setPlace(placement(anchor));
    window.addEventListener("scroll", update, { capture: true, passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, { capture: true });
      window.removeEventListener("resize", update);
    };
  }, [anchor]);
  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    // A native, non-passive listener: React's onWheel cannot cancel the page scroll.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (body.current) body.current.scrollTop += e.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [body]);
  const d = detail.data;
  // iOS-style open: the panel first appears as a glass capsule (title + buttons), then grows into the full box
  // on a spring. Only its body's height animates; the text is laid out at its final width from the start, so
  // nothing reflows while it grows. Reduced motion: it simply fades in at full size.
  const spring = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 320, damping: 32, mass: 0.9 };
  const reveal = (i: number) => (reduce ? {} : {
    initial: { opacity: 0, y: place.above ? -6 : 6 },
    animate: { opacity: 1, y: 0, transition: { delay: 0.1 + i * 0.045, duration: 0.32, ease: [0.16, 1, 0.3, 1] as const } },
  });
  return (
    <motion.div
      ref={panel}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.94, y: place.above ? 8 : -8, borderRadius: 30 }}
      animate={{ opacity: 1, scale: 1, y: 0, borderRadius: 26, transition: reduce ? { duration: 0.15 } : {
        opacity: { duration: 0.18, ease: "easeOut" }, default: spring } }}
      exit={reduce ? { opacity: 0, transition: { duration: 0.1 } }
        : { opacity: 0, scale: 0.96, transition: { duration: 0.14, ease: [0.4, 0, 1, 1] } }}
      style={{ ...place.style, transformOrigin: place.above ? "50% 100%" : "50% 0%" }}
      className={`hover-glass z-[45] flex cursor-pointer overflow-hidden ${place.above ? "flex-col-reverse" : "flex-col"}`}
      data-testid="hover-details"
      // The panel covers the cards below it (My List, genre grids), so a click on it must open this title's page,
      // except on its own buttons and links (rate, list, Why?, cast).
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a, button, input, select, textarea")) return;
        navigate(`/movie/${m.id}`, { state: { source } });
      }}
    >
      {/* The capsule: title and actions in one row. It sits next to the card, above or below it. */}
      <div className="flex min-h-[56px] items-center gap-2 py-2 pl-5 pr-2">
        <Link to={`/movie/${m.id}`} state={{ source }} title={m.title}
          className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-[-0.01em] hover:underline">{m.title}</Link>
        {/* The film's own record (fresh) wins over the rail's copy, which may be older. */}
        <ActionButtons movieId={m.id} state={detail.data?.user_state ?? item.user_state} source={source} />
        <button
          onClick={() => openQuickView(item)}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/20 bg-white/10 text-white transition-colors hover:border-white/50 hover:bg-white/20"
          aria-label={`Quick view ${m.title}`}
          title="Quick View"
        >
          <Chevron />
        </button>
      </div>
      <motion.div initial={reduce ? false : { height: 0 }} animate={{ height: "auto", transition: { ...spring, delay: reduce ? 0 : 0.07 } }}
        className="overflow-hidden">
        <div className={`mx-4 h-px bg-white/10 ${place.above ? "mt-3" : ""}`} aria-hidden />
        <div ref={body} style={{ maxHeight: place.maxBody }} className="overflow-y-auto overscroll-contain px-4 pb-4 pt-3"
          tabIndex={0} aria-label={`${m.title} details`}>
          <motion.div {...reveal(0)} className="flex flex-wrap gap-1.5">
            {[...m.genres.slice(0, 3), d?.runtime ? `${d.runtime} min` : null, d?.certification].filter(Boolean).map((t) => (
              <span key={t} className="rounded-full border border-white/10 bg-white/[0.07] px-2.5 py-0.5 text-[11px] text-white/80">{t}</span>
            ))}
          </motion.div>
          {item.reasons[0] && (
            <motion.p {...reveal(1)} className="mt-2.5 text-xs text-white/75">
              {item.reasons[0].text}
              {item.match_pct != null && (
                <button onClick={() => openWhy(m.id)} className="ml-2 font-medium text-white underline underline-offset-2">Why?</button>
              )}
            </motion.p>
          )}
          {(d?.overview ?? m.overview_short) && (
            <motion.p {...reveal(2)} className="mt-2 text-xs leading-relaxed text-white/85">{d?.overview ?? m.overview_short}</motion.p>
          )}
          {!d ? (
            // Same size as the real rows, so nothing moves when the details arrive.
            <div aria-hidden>
              <div className="mt-2 h-4 w-40 animate-pulse rounded-full bg-white/10" />
              <div className="mt-2 flex gap-2">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} className="w-12 shrink-0">
                    <div className="mx-auto h-10 w-10 animate-pulse rounded-full bg-white/10" />
                    <div className="mx-auto mt-1 h-[13px] w-10 animate-pulse rounded-full bg-white/10" />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <motion.div {...reveal(3)}>
              {d.directors.length > 0 && (
                <p className="mt-2 text-xs text-muted">Directed by <span className="text-white/85">{d.directors.map((x) => x.name).join(", ")}</span></p>
              )}
              {d.cast.length > 0 && (
                <div className="mt-2.5 flex gap-2">
                  {d.cast.slice(0, 5).map((c) => (
                    <Link key={c.id} to={`/person/${c.id}`} className="group w-12 shrink-0 text-center" title={c.name}>
                      <div className="mx-auto h-10 w-10 overflow-hidden rounded-full bg-white/10 ring-1 ring-white/15 transition-shadow group-hover:ring-white/50">
                        {c.profile_path && <FadeImg src={tmdbImage(c.profile_path, "w300")} />}
                      </div>
                      <div className="mt-1 truncate text-[10px] leading-tight text-white/70">{c.name}</div>
                    </Link>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

/** A small image that fades in once loaded instead of popping in. */
function FadeImg({ src }: { src?: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <img src={src} alt="" decoding="async" onLoad={() => setLoaded(true)}
      className={`h-full w-full object-cover transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`} />
  );
}

/** Under the card when there is room; above it when the card sits near the bottom of the screen. It floats a few
 *  pixels off the card (the 120 ms leave grace covers the gap). */
const GAP = 6;
function placement(anchor: HTMLElement): { style: CSSProperties; maxBody: number; above: boolean } {
  const r = anchor.getBoundingClientRect();
  const below = window.innerHeight - r.bottom;
  const above = below < 240 && r.top > below;
  const room = (above ? r.top : below) - 90;
  const base: CSSProperties = { position: "fixed", left: r.left, width: r.width };
  return {
    above,
    maxBody: Math.max(120, Math.min(260, room)),
    style: above ? { ...base, bottom: window.innerHeight - r.top + GAP } : { ...base, top: r.bottom + GAP },
  };
}

export function Chevron() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}