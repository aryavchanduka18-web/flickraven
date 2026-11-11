import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { RecItem } from "../../api/types";

export type ToastAction = { label: string; run: () => void };

type UI = {
  quickView: RecItem | null;
  openQuickView: (item: RecItem) => void;
  closeQuickView: () => void;
  toast: string | null;
  /** A short message at the bottom. With `action` it also shows one button (for example Undo) and stays longer. */
  toastAction: ToastAction | null;
  notify: (msg: string, action?: ToastAction) => void;
  /** Film whose "Why?" panel is open. */
  whyId: number | null;
  openWhy: (movieId: number | null) => void;
  /** Film just disliked: the "why not?" sheet asks for a reason. */
  dislikeId: number | null;
  askDislikeReason: (movieId: number | null) => void;
  /** Desktop sidebar: open or hidden. Remembered in this browser. */
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
};

const SIDEBAR_KEY = "fr-sb";
function sidebarWasOpen(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) !== "0";
  } catch {
    return true;
  }
}

const Ctx = createContext<UI | null>(null);

export function UIProvider({ children }: { children: ReactNode }) {
  const [quickView, setQuickView] = useState<RecItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [toastAction, setToastAction] = useState<ToastAction | null>(null);
  const [whyId, setWhyId] = useState<number | null>(null);
  const [dislikeId, setDislikeId] = useState<number | null>(null);
  const [sidebarOpen, setSidebar] = useState(sidebarWasOpen);
  const setSidebarOpen = useCallback((open: boolean) => {
    setSidebar(open);
    try {
      localStorage.setItem(SIDEBAR_KEY, open ? "1" : "0");
    } catch {
      /* private mode: it just resets next visit */
    }
  }, []);
  const notify = useCallback((msg: string, action?: ToastAction) => {
    setToast(msg);
    setToastAction(action ?? null);
    window.setTimeout(() => {
      setToast((t) => {
        if (t === msg) setToastAction(null);
        return t === msg ? null : t;
      });
    }, action ? 6500 : 2600);
  }, []);
  return (
    <Ctx.Provider value={{ quickView, openQuickView: setQuickView, closeQuickView: () => setQuickView(null), toast, toastAction, notify,
      whyId, openWhy: setWhyId, dislikeId, askDislikeReason: setDislikeId, sidebarOpen, setSidebarOpen }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUI(): UI {
  const v = useContext(Ctx);
  if (!v) throw new Error("useUI outside UIProvider");
  return v;
}
