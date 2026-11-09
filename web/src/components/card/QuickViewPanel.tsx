import ImdbScore from "../../components/movie/ImdbScore";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useLogEvent } from "../../api/hooks";
import { languageName, runtime } from "../../lib/format";
import { tmdbImage } from "../../lib/tmdb";
import ActionButtons from "../feedback/ActionButtons";
import WhyThis from "../explain/WhyThis";
import { useUI } from "../layout/ui";

export default function QuickViewPanel() {
  const { quickView: item, closeQuickView } = useUI();
  const logEvent = useLogEvent();
  useEffect(() => {
    if (item) logEvent("quick_view", item.movie.id, "quick_view");
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeQuickView();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.movie.id]);
  return (
    <AnimatePresence>
      {item && (
        <motion.div className="fixed inset-0 z-50 grid place-items-end bg-black/70 md:place-items-center" initial={{ opacity: 0 }}
          animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={closeQuickView}>
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={item.movie.title}
            onClick={(e) => e.stopPropagation()}
            initial={{ y: 24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 24, opacity: 0 }}
            transition={{ duration: 0.22 }}
            className="max-h-[90vh] w-full overflow-y-auto rounded-t-xl bg-surface md:w-[720px] md:rounded-xl"
          >
            <div className="relative aspect-video">
              <img src={tmdbImage(item.movie.backdrop ?? item.movie.poster, "w1280")} alt="" className="h-full w-full object-cover" />
              <div className="absolute inset-0 bg-gradient-to-t from-surface via-surface/20 to-transparent" />
              <button onClick={closeQuickView} aria-label="Close" className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-full bg-black/60 text-white">
                ✕
              </button>
            </div>
            <div className="space-y-3 p-5 pt-0">
              <h2 className="font-display text-2xl font-bold">{item.movie.title}</h2>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                {item.match_pct != null && <span className="text-lg font-extrabold text-accent">{item.match_pct}% match</span>}
                <ImdbScore rating={item.movie.imdb_rating} votes={item.movie.imdb_votes} />
                {item.movie.year && <span>{item.movie.year}</span>}
                {item.movie.runtime && <span>{runtime(item.movie.runtime)}</span>}
                <span>{languageName(item.movie.language)}</span>
                <span>{item.movie.genres.join(" · ")}</span>
              </div>
              {item.movie.overview_short && <p className="text-sm leading-relaxed text-white/85">{item.movie.overview_short}</p>}
              <WhyThis reasons={item.reasons} compact />
              <div className="flex items-center justify-between pt-2">
                <ActionButtons movieId={item.movie.id} state={item.user_state} source="quick_view" size="md" />
                <Link to={`/movie/${item.movie.id}`} onClick={closeQuickView}
                  className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-white/85">
                  View full details
                </Link>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}