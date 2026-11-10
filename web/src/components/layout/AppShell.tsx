import { AnimatePresence, motion } from "framer-motion";
import { useLayoutEffect, useRef, useState } from "react";
import { Outlet } from "react-router-dom";
import Footer from "./Footer";
import MobileTabBar from "./MobileTabBar";
import NavBar from "./NavBar";
import Sidebar from "./Sidebar";
import { useUI } from "./ui";
import QuickViewPanel from "../card/QuickViewPanel";
import GuestBanner from "../account/GuestBanner";
import WhyPanel from "../explain/WhyPanel";
import DislikeReasonSheet from "../feedback/DislikeReasonSheet";

/** Pieces of the page that should glide when the sidebar opens or closes: everything in the main area except
 *  full-bleed heroes (`data-sb-bleed`, which stay put), plus anything marked `data-sb-slide` inside them. */
function slideTargets(root: Element): Element[] {
  const out: Element[] = [];
  const walk = (el: Element) => {
    for (const c of Array.from(el.children)) {
      if (c.hasAttribute("data-sb-bleed")) continue;
      if (c.querySelector("[data-sb-bleed]")) walk(c);
      else out.push(c);
    }
  };
  walk(root);
  document.querySelectorAll("[data-sb-slide]").forEach((e) => out.push(e));
  return out;
}

export default function AppShell() {
  const { toast, sidebarOpen } = useUI();
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const [moving, setMoving] = useState(false);

  // The layout changes at once; the content then glides from where it was. Only transforms move, so it stays on
  // the GPU (animating the layout every frame was janky in the prototype). The panel goes solid while it slides.
  useLayoutEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const wide = window.matchMedia("(min-width: 768px)").matches;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!wide || calm || !main.current) return;
    const d = sidebarOpen ? -250 : 250;
    for (const el of slideTargets(main.current)) {
      el.animate([{ transform: `translateX(${d}px)` }, { transform: "translateX(0)" }], { duration: 650, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    setMoving(true);
    const t = window.setTimeout(() => setMoving(false), 720);
    return () => window.clearTimeout(t);
  }, [sidebarOpen]);

  return (
    <div className="shell min-h-screen bg-bg text-ink" data-sidebar={sidebarOpen ? "open" : "hidden"}>
      <NavBar />
      <Sidebar moving={moving} />
      <GuestBanner />
      <main ref={main} className="shell-main pb-20 md:pb-0">
        <Outlet />
      </main>
      <div className="shell-main"><Footer /></div>
      <MobileTabBar />
      <QuickViewPanel />
      <WhyPanel />
      <DislikeReasonSheet />
      <AnimatePresence>
        {toast && (
          <motion.div
            role="status"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={{ duration: 0.18 }}
            className="glass fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-full px-5 py-2.5 text-sm font-medium text-white md:bottom-8"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
