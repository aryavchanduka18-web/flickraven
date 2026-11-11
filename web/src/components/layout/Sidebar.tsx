import { motion, useReducedMotion } from "framer-motion";
import { NavLink } from "react-router-dom";
import { AvatarMenu, Logo, TABS } from "./NavBar";
import SearchBox from "./SearchBox";
import { ActivityIcon, AnimeIcon, DiscoverIcon, GenresIcon, HomeIcon, ListIcon, MoviesIcon, ShowsIcon, SidebarIcon, SparkIcon } from "./icons";
import { useUI } from "./ui";

const ICONS: Record<string, (p: { className?: string }) => React.JSX.Element> = {
  "/": HomeIcon,
  "/discover": DiscoverIcon,
  "/movies": MoviesIcon,
  "/shows": ShowsIcon,
  "/anime": AnimeIcon,
  "/pick": SparkIcon,
  "/genres": GenresIcon,
  "/my-list": ListIcon,
  "/activity": ActivityIcon,
};

/** Desktop navigation: a floating dark-glass panel on the left (Apple TV style). A tall button hides it; a small
 *  glass button then floats where it was. Phones use the bottom tab bar instead. */
export default function Sidebar({ moving }: { moving: boolean }) {
  const { sidebarOpen, setSidebarOpen } = useUI();
  const reduce = useReducedMotion();
  return (
    <>
      <aside
        aria-label="Main"
        inert={!sidebarOpen}
        data-testid="sidebar"
        className={`glass fixed bottom-4 left-4 top-4 z-40 hidden w-[236px] flex-col gap-0.5 rounded-[28px] p-3 md:flex ${moving ? "moving" : ""}`}
        style={{
          transform: sidebarOpen ? "none" : "translate3d(-112%,0,0)",
          opacity: sidebarOpen ? 1 : 0,
          pointerEvents: sidebarOpen ? "auto" : "none",
          transition: reduce ? "none" : "transform .65s var(--ease-out), opacity .45s var(--ease-out)",
          willChange: "transform",
        }}
      >
        <div className="flex items-center justify-between pb-3 pl-2 pr-1 pt-1">
          <Logo className="h-8" />
          <button className="glass-btn h-[50px] w-[42px] rounded-2xl" aria-label="Hide sidebar" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(false)}>
            <SidebarIcon />
          </button>
        </div>
        <div className="pb-2">
          <SearchBox variant="sidebar" />
        </div>
        <nav className="flex flex-col gap-0.5">
          {TABS.map((t) => {
            const Icon = ICONS[t.to] ?? HomeIcon;
            return (
              <NavLink key={t.to} to={t.to} end={t.to === "/"}
                className={({ isActive }) => `relative flex items-center gap-3 rounded-2xl px-3 py-2.5 text-[15px] font-semibold transition-colors duration-200 ${isActive ? "text-[#111]" : "text-[#e9e9e9] hover:bg-white/[0.09]"}`}>
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <motion.span layoutId="sidebar-active" aria-hidden className="absolute inset-0 rounded-2xl bg-[#f5f5f5]"
                        transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 520, damping: 40 }} />
                    )}
                    <Icon className="relative h-5 w-5 shrink-0" />
                    <span className="relative">{t.label}</span>
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>
        <div className="mt-auto border-t border-white/10 pt-2">
          <AvatarMenu up withName />
        </div>
      </aside>
      <div
        inert={sidebarOpen}
        className="fixed left-4 top-4 z-40 hidden gap-2 md:flex"
        style={{
          opacity: sidebarOpen ? 0 : 1,
          transform: sidebarOpen ? "translateX(-14px) scale(.85)" : "none",
          pointerEvents: sidebarOpen ? "none" : "auto",
          transition: reduce ? "none" : "opacity .4s var(--ease-out), transform .6s var(--spring)",
        }}
      >
        <button className="glass-btn h-[50px] w-[42px] rounded-2xl" aria-label="Show sidebar" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}>
          <SidebarIcon />
        </button>
      </div>
    </>
  );
}
