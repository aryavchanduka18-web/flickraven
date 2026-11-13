import ImdbScore from "../../components/movie/ImdbScore";
import { AnimatePresence, motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { RecItem } from "../../api/types";
import { useFeedback, useLogEvent } from "../../api/hooks";
import { ROW_VISIBLE, record, useDwell } from "../../lib/impressions";
import { languageName, runtime } from "../../lib/format";
import { tmdbImage } from "../../lib/tmdb";
import { agreementLabel } from "../../lib/confidence";
import { useUI } from "../layout/ui";

const Chevron = ({ left = false }: { left?: boolean }) => (
  <svg viewBox="0 0 24 24" className="h-[22px] w-[22px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={left ? "m15 6-6 6 6 6" : "m9 6 6 6-6 6"} />
  </svg>
);

/** Three buttons, as on the Apple TV home screen: View details, Add to list, Why this. */
function HeroButtons({ item, index }: { item: RecItem; index: number }) {
  const m = item.movie;
  const fb = useFeedback(m.id, "hero");
  const logEvent = useLogEvent();
  const { openWhy, notify } = useUI();
  const inList = item.user_state.in_list;
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      <Link to={`/movie/${m.id}`} state={{ source: "hero", position: index }} onClick={() => logEvent("hero_view", m.id, "hero", index)}
        className="glass-btn solid rounded-2xl px-6 py-3 text-[15px] font-semibold">
        View details
      </Link>
      <button type="button" aria-pressed={inList}
        onClick={() => {
          fb.mutate({ kind: "list", on: !inList });
          notify(inList ? "Removed from My List" : "Added to My List");
        }}
        className={`glass-btn rounded-2xl px-5 py-3 text-[15px] font-semibold ${inList ? "on" : ""}`}>
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d={inList ? "m5 12.5 4.5 4.5L19 7.5" : "M12 5v14M5 12h14"} />
        </svg>
        {inList ? "In your list" : "Add to list"}
      </button>
      {item.match_pct != null && (
        <button type="button" onClick={() => openWhy(m.id)} className="glass-btn rounded-2xl px-5 py-3 text-[15px] font-semibold">
          Why this?
        </button>
      )}
    </div>
  );
}

/** Top picks, rotating, as a full-bleed header: the film's own 16:9 picture fills the screen and fades to black on the
 *  left, where the title, the facts and the three buttons sit. No Play button: FlickRaven recommends, it does not
 *  stream (spec 8.5). */
export default function Hero({ items }: { items: RecItem[] }) {
  const [i, setI] = useState(0);
  const reduce = useReducedMotion();
  // On scroll the picture drifts and dims, the text lifts (spec 8.5).
  const { scrollY } = useScroll();
  const artY = useTransform(scrollY, [0, 600], [0, 120]);
  const artScale = useTransform(scrollY, [0, 600], [1, 1.06]);
  const fade = useTransform(scrollY, [0, 500], [1, 0.35]);
  const item = items[i];
  const sectionRef = useRef<HTMLElement>(null);
  // A hero slide counts once the hero is half on screen and the slide has been shown for a second.
  useDwell(sectionRef, () => item && record({ surface: "hero", kind: "card", movie_id: item.movie.id, position: i, visible_ms: 1000 }),
    { threshold: ROW_VISIBLE, key: item?.movie.id });
  useEffect(() => setI(0), [items.length]);
  useEffect(() => {
    const t = window.setTimeout(() => setI((x) => (x + 1) % Math.max(items.length, 1)), 9000);
    return () => window.clearTimeout(t);
  }, [i, items.length]);
  // Load the next slide's picture while this one shows, so the fade does not wait on the network.
  useEffect(() => {
    const next = items[(i + 1) % Math.max(items.length, 1)]?.movie;
    const src = next && tmdbImage(next.backdrop ?? next.poster, "w1280");
    if (src) new Image().src = src;
  }, [i, items]);
  if (!item) return null;
  const m = item.movie;
  const go = (n: number) => setI((n + items.length) % items.length);
  return (
    <section ref={sectionRef} data-sb-bleed className="hero-bleed relative h-[82vh] min-h-[560px] overflow-hidden isolate" aria-roledescription="carousel" aria-label="Top picks">
      <AnimatePresence initial={false}>
        <motion.div key={m.id} className="absolute inset-0" style={{ y: artY, scale: artScale }} initial={{ opacity: 0, scale: reduce ? 1 : 1.04 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }}>
          <img src={tmdbImage(m.backdrop ?? m.poster, "w1280")} alt="" fetchPriority="high" decoding="async"
            className="absolute inset-0 h-full w-full object-cover object-[72%_center] md:object-right" />
          {/* Black on the left for the text, clear on the right for the picture. */}
          <div className="absolute inset-0 bg-[linear-gradient(90deg,#080808_0%,rgba(8,8,8,0.9)_24%,rgba(8,8,8,0.5)_46%,rgba(8,8,8,0)_72%)]" />
          <div className="absolute inset-0 bg-gradient-to-t from-bg via-bg/20 to-black/35" />
        </motion.div>
      </AnimatePresence>
      <motion.div style={{ opacity: fade }} data-sb-slide
        className="relative z-10 flex h-full flex-col justify-end px-5 pb-14 md:pb-20 md:pl-[calc(var(--sb)+76px)] md:pr-24">
        <AnimatePresence mode="wait">
          <motion.div key={m.id} initial={{ opacity: 0, y: reduce ? 0 : 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reduce ? 0 : -8 }}
            transition={{ duration: 0.55, ease: [0.2, 0.8, 0.2, 1] }} className="max-w-2xl">
            {m.logo ? (
              <img src={tmdbImage(m.logo, "w500")} alt={m.title} className="mb-4 max-h-28 max-w-[70%] object-contain object-left drop-shadow-lg" />
            ) : (
              <h1 className="mb-3 font-display text-5xl font-extrabold leading-[1.02] tracking-tight drop-shadow-lg md:text-7xl">{m.title}</h1>
            )}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-white/85">
              {m.title_type === "anime" && <span className="rounded-full border border-white/30 px-2.5 py-0.5 text-xs font-semibold">Anime series</span>}
              {m.title_type === "series" && <span className="rounded-full border border-white/30 px-2.5 py-0.5 text-xs font-semibold">Series</span>}
              {m.year && <span>{m.year}</span>}
              {m.runtime && <span>{runtime(m.runtime)}</span>}
              <span>{m.genres.slice(0, 3).join(" · ")}</span>
              <span>{languageName(m.language)}</span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {item.match_pct != null && (
                <span className="rounded-lg border border-accent/60 bg-accent/15 px-3 py-1 text-sm font-bold text-white">{item.match_pct}% Match</span>
              )}
              <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
              {item.match_pct != null && agreementLabel(item.agreement) && (
                <span className="text-[11px] text-white/60">{agreementLabel(item.agreement)!.toLowerCase()} model agreement</span>
              )}
            </div>
            {m.overview_short && <p className="mt-4 line-clamp-3 max-w-xl text-[15px] leading-relaxed text-white/85">{m.overview_short}</p>}
            {item.reasons[0] && <p className="mt-2 text-sm text-white/65">{item.reasons[0].text}</p>}
            <HeroButtons item={item} index={i} />
          </motion.div>
        </AnimatePresence>
        <div className="mt-8 flex gap-2" role="tablist" aria-label="Choose a pick">
          {items.map((it, j) => (
            <button key={it.movie.id} role="tab" aria-label={`Pick ${j + 1}: ${it.movie.title}`} aria-selected={i === j}
              onClick={() => setI(j)} className={`h-1.5 rounded-full transition-all duration-500 ${i === j ? "w-8 bg-white" : "w-3 bg-white/35 hover:bg-white/60"}`} />
          ))}
        </div>
      </motion.div>
      {items.length > 1 && (
        <>
          <button aria-label="Previous pick" onClick={() => go(i - 1)} data-sb-slide
            className="glass-btn absolute left-3 top-[46%] z-20 hidden h-11 w-11 rounded-full md:left-[calc(var(--sb)+12px)] md:inline-flex md:h-[52px] md:w-[52px]">
            <Chevron left />
          </button>
          <button aria-label="Next pick" onClick={() => go(i + 1)}
            className="glass-btn absolute right-3 top-[46%] z-20 hidden h-11 w-11 rounded-full md:right-5 md:inline-flex md:h-[52px] md:w-[52px]">
            <Chevron />
          </button>
        </>
      )}
    </section>
  );
}
