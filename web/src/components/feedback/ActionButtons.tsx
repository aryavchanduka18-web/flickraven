import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { undoNotInterested, useFeedback, useNotInterested } from "../../api/hooks";
import { canHideFrom } from "../../lib/notInterested";
import type { UserState } from "../../api/types";
import { useUI } from "../layout/ui";

type Props = { movieId: number; state: UserState; source?: string; origin?: string; size?: "sm" | "md"; showWatched?: boolean };

const Icon = {
  like: (on: boolean) => (
    <svg viewBox="0 0 24 24" className="h-[1.1em] w-[1.1em]" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
      <path d="M7 11v9H4v-9h3Zm0 0 4-7a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17.3 20H7" />
    </svg>
  ),
  dislike: (on: boolean) => (
    <svg viewBox="0 0 24 24" className="h-[1.1em] w-[1.1em] rotate-180" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
      <path d="M7 11v9H4v-9h3Zm0 0 4-7a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17.3 20H7" />
    </svg>
  ),
  list: (on: boolean) => (
    <svg viewBox="0 0 24 24" className="h-[1.1em] w-[1.1em]" fill="none" stroke="currentColor" strokeWidth="1.9">
      {on ? <motion.path d="m5 12 4.5 4.5L19 7" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.3 }} />
        : <path d="M12 5v14M5 12h14" />}
    </svg>
  ),
  hide: () => (
    <svg viewBox="0 0 24 24" className="h-[1.1em] w-[1.1em]" fill="none" stroke="currentColor" strokeWidth="1.9">
      <path d="m6 6 12 12M18 6 6 18" />
    </svg>
  ),
  watched: (on: boolean) => (
    <svg viewBox="0 0 24 24" className="h-[1.1em] w-[1.1em]" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" fill={on ? "#080808" : "none"} />
    </svg>
  ),
};

/** One round action button. Turning it on gives a short pop of the icon, plus a small burst of dots for
 *  Like; anyone whose system asks for reduced motion gets none of it. */
function ActionButton({ on, label, title, onClick, burst, size, children }: {
  on: boolean; label: string; title: string; onClick: () => void; burst?: boolean; size: "sm" | "md"; children: ReactNode;
}) {
  const reduce = useReducedMotion();
  const [fired, setFired] = useState(0);
  const cls = `relative grid place-items-center rounded-full border transition-colors duration-150 ${
    size === "sm" ? "h-8 w-8 text-sm" : "h-11 w-11 text-base"
  } ${on ? "border-white bg-white text-black" : "border-white/30 bg-black/40 text-white hover:border-white"}`;
  return (
    <motion.button
      className={cls}
      aria-pressed={on}
      aria-label={label}
      title={title}
      whileTap={reduce ? undefined : { scale: 0.85 }}
      onClick={() => {
        if (!on) setFired((n) => n + 1);
        onClick();
      }}
    >
      <motion.span key={fired} className="grid place-items-center"
        initial={reduce || !fired ? false : { scale: 1.45 }} animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 500, damping: 14 }}>
        {children}
      </motion.span>
      <AnimatePresence>
        {burst && fired > 0 && !reduce && on && (
          <span key={fired} className="pointer-events-none absolute inset-0" aria-hidden>
            {Array.from({ length: 8 }, (_, i) => {
              const a = (i / 8) * Math.PI * 2;
              return (
                <motion.span key={i} className="absolute left-1/2 top-1/2 -ml-[3px] -mt-[3px] h-1.5 w-1.5 rounded-full bg-accent"
                  initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
                  animate={{ x: Math.cos(a) * 22, y: Math.sin(a) * 22, opacity: 0, scale: 0.4 }}
                  transition={{ duration: 0.5, ease: "easeOut" }} />
              );
            })}
          </span>
        )}
      </AnimatePresence>
    </motion.button>
  );
}

export default function ActionButtons({ movieId, state: server, source, origin, size = "sm", showWatched = false }: Props) {
  const fb = useFeedback(movieId, source, origin);
  const hide = useNotInterested(movieId, source);
  const qc = useQueryClient();
  // "Not interested" is for recommendation rows only (lib/notInterested.ts), not More Like This, search or My List.
  const canHide = canHideFrom(source) && !server.in_list && server.reaction === 0 && server.rating == null;
  const { notify, askDislikeReason } = useUI();
  // Optimistic: the button changes on click; the server's answer replaces it when the lists refresh.
  const [state, setState] = useState(server);
  useEffect(() => setState(server), [server.in_list, server.reaction, server.watched, server.rating]);
  return (
    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
      <ActionButton size={size} on={state.in_list} label={state.in_list ? "Remove from My List" : "Add to My List"}
        title={state.in_list ? "Remove from My List" : "Add to My List"}
        onClick={() => {
          setState({ ...state, in_list: !state.in_list });
          fb.mutate({ kind: "list", on: !state.in_list });
          notify(state.in_list ? "Removed from My List" : "Added to My List");
        }}>
        {Icon.list(state.in_list)}
      </ActionButton>
      <ActionButton size={size} burst on={state.reaction === 1} label="Like" title="Like"
        onClick={() => {
          setState({ ...state, reaction: state.reaction === 1 ? 0 : 1 });
          fb.mutate({ kind: "react", value: state.reaction === 1 ? 0 : 1 });
          notify(state.reaction === 1 ? "Like removed" : "Liked. Your picks will lean this way.");
        }}>
        {Icon.like(state.reaction === 1)}
      </ActionButton>
      <ActionButton size={size} on={state.reaction === -1} label="Dislike" title="Not for me"
        onClick={() => {
          setState({ ...state, reaction: state.reaction === -1 ? 0 : -1 });
          fb.mutate({ kind: "react", value: state.reaction === -1 ? 0 : -1 });
          if (state.reaction === -1) notify("Dislike removed");
          else askDislikeReason(movieId);           // the sheet asks why, then confirms
        }}>
        {Icon.dislike(state.reaction === -1)}
      </ActionButton>
      {canHide && (
        <ActionButton size={size} on={false} label="Not interested" title="Not interested: hide this, small effect on your picks"
          onClick={() => {
            hide.mutate(false);
            notify("Hidden from your picks. Not a dislike: your taste profile is unchanged.",
              { label: "Undo", run: () => { undoNotInterested(qc, movieId); } });
          }}>
          {Icon.hide()}
        </ActionButton>
      )}
      {showWatched && (
        <ActionButton size={size} on={state.watched} label={state.watched ? "Unmark watched" : "Mark watched"}
          title={state.watched ? "Watched" : "Mark watched"}
          onClick={() => {
            setState({ ...state, watched: !state.watched });
            fb.mutate({ kind: "watched", on: !state.watched });
            notify(state.watched ? "Unmarked as watched" : "Marked as watched");
          }}>
          {Icon.watched(state.watched)}
        </ActionButton>
      )}
    </div>
  );
}
