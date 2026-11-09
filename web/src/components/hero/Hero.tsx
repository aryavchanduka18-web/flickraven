import ImdbScore from "../../components/movie/ImdbScore";
import { AnimatePresence, motion, useScroll, useTransform } from "framer-motion";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { RecItem } from "../../api/types";
import { useLogEvent } from "../../api/hooks";
import { languageName, runtime } from "../../lib/format";
import { tmdbImage } from "../../lib/tmdb";
import ActionButtons from "../feedback/ActionButtons";
import { agreementLabel } from "../../lib/confidence";
import { useUI } from "../layout/ui";

/** Top 5 picks, rotating. Blurred artwork + a subtle tint from the precomputed dominant color.
 *  No Play button: FlickRaven recommends, it does not stream (spec 8.5). */
export default function Hero({ items }: { items: RecItem[] }) {
  const [i, setI] = useState(0);
  const logEvent = useLogEvent();
  const { openWhy } = useUI();
  // On scroll the hero compresses: the artwork drifts and dims, the text lifts (spec 8.5).
  const { scrollY } = useScroll();
  const artY = useTransform(scrollY, [0, 600], [0, 120]);
  const artScale = useTransform(scrollY, [0, 600], [1, 1.06]);
  const fade = useTransform(scrollY, [0, 500], [1, 0.35]);
  const item = items[i];
  useEffect(() => setI(0), [items.length]);
  useEffect(() => {
    const t = window.setTimeout(() => setI((x) => (x + 1) % Math.max(items.length, 1)), 9000);
    return () => window.clearTimeout(t);
  }, [i, items.length]);
  if (!item) return null;
  const m = item.movie;
  const tint = m.dominant_color ?? "#141414";
  return (
    <section className="relative h-[78vh] min-h-[520px] w-full overflow-hidden" aria-roledescription="carousel" aria-label="Top picks">
      <AnimatePresence initial={false}>
        <motion.div key={m.id} className="absolute inset-0" style={{ y: artY, scale: artScale }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}>
          <img src={tmdbImage(m.backdrop ?? m.poster, "w1280")} alt="" className="absolute inset-0 h-full w-full object-cover" />
          <div className="absolute inset-0" style={{ background: `linear-gradient(90deg, ${tint}cc 0%, ${tint}55 35%, transparent 70%)` }} />
          <div className="absolute inset-0 bg-gradient-to-t from-bg via-bg/30 to-black/30" />
        </motion.div>
      </AnimatePresence>
      <motion.div style={{ opacity: fade }} className="relative z-10 mx-auto flex h-full max-w-[1800px] flex-col justify-end px-4 pb-16 md:px-10 md:pb-24">
        <AnimatePresence mode="wait">
          <motion.div key={m.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.45 }} className="max-w-2xl">
            {m.logo ? (
              <img src={tmdbImage(m.logo, "w500")} alt={m.title} className="mb-4 max-h-28 max-w-[70%] object-contain object-left drop-shadow-lg" />
            ) : (
              <h1 className="mb-3 font-display text-4xl font-extrabold leading-[1.05] drop-shadow-lg md:text-6xl">{m.title}</h1>
            )}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-white/85">
              {item.match_pct != null && <span className="text-2xl font-extrabold text-accent">{item.match_pct}% match</span>}
              {item.match_pct != null && agreementLabel(item.agreement) && (
                <span className="text-[11px] text-white/60">{agreementLabel(item.agreement)!.toLowerCase()} model agreement</span>
              )}
              <ImdbScore rating={m.imdb_rating} votes={m.imdb_votes} />
              {m.year && <span>{m.year}</span>}
              {m.runtime && <span>{runtime(m.runtime)}</span>}
              <span>{languageName(m.language)}</span>
              <span>{m.genres.slice(0, 3).join(" · ")}</span>
            </div>
            {item.reasons[0] && (
              <p className="mt-3 flex flex-wrap items-center gap-3 text-base text-white/90">
                {item.reasons[0].text}
                {item.match_pct != null && (
                  <button onClick={() => openWhy(m.id)}
                    className="rounded-full border border-white/30 bg-black/30 px-3 py-0.5 text-sm backdrop-blur hover:border-white">Why?</button>
                )}
              </p>
            )}
            {m.overview_short && <p className="mt-2 line-clamp-2 max-w-xl text-sm text-white/70">{m.overview_short}</p>}
            <div className="mt-6 flex items-center gap-3">
              <Link to={`/movie/${m.id}`} state={{ source: "hero", position: i }} onClick={() => logEvent("hero_view", m.id, "hero", i)}
                className="rounded-md bg-white px-5 py-2.5 text-sm font-semibold text-black transition-colors hover:bg-white/85">
                View Details
              </Link>
              <ActionButtons movieId={m.id} state={item.user_state} source="hero" size="md" />
            </div>
          </motion.div>
        </AnimatePresence>
        <div className="mt-8 flex items-center gap-3">
          <button aria-label="Previous pick" onClick={() => setI((i - 1 + items.length) % items.length)}
            className="grid h-9 w-9 place-items-center rounded-full border border-white/25 bg-black/30 backdrop-blur hover:bg-black/50">‹</button>
          <div className="flex gap-2">
            {items.map((it, j) => (
              <button key={it.movie.id} aria-label={`Pick ${j + 1}: ${it.movie.title}`} aria-current={i === j}
                onClick={() => setI(j)} className={`h-1.5 rounded-full transition-all duration-300 ${i === j ? "w-8 bg-white" : "w-3 bg-white/40"}`} />
            ))}
          </div>
          <button aria-label="Next pick" onClick={() => setI((i + 1) % items.length)}
            className="grid h-9 w-9 place-items-center rounded-full border border-white/25 bg-black/30 backdrop-blur hover:bg-black/50">›</button>
        </div>
      </motion.div>
    </section>
  );
}