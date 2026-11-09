import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useMe } from "../../api/hooks";
import { send } from "../../api/client";
import SearchBox from "./SearchBox";

export const TABS = [
  { to: "/", label: "Home" },
  { to: "/discover", label: "Discover" },
  { to: "/genres", label: "Genres" },
  { to: "/my-list", label: "My List" },
  { to: "/activity", label: "Activity" },
];

/** Translucent at the top, solid near-black after ~80px of scroll (spec 8.1). */
function useScrolled(threshold = 80) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);
  return scrolled;
}

export function Logo() {
  return (
    <Link to="/" className="font-display text-xl font-extrabold tracking-tight text-white" aria-label="FlickRaven home">
      Flick<span className="text-accent">Raven</span>
    </Link>
  );
}

export default function NavBar() {
  const scrolled = useScrolled();
  return (
    <header
      className={`fixed inset-x-0 top-0 z-40 transition-colors duration-200 ${
        scrolled ? "bg-bg/95 shadow-[0_1px_0_#ffffff10]" : "bg-gradient-to-b from-black/70 to-transparent"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-6 px-4 md:px-10">
        <Logo />
        <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.to === "/"}
              className={({ isActive }) =>
                `rounded-full px-3.5 py-1.5 text-sm transition-colors duration-150 ${
                  isActive ? "bg-white font-medium text-black" : "text-white/85 hover:bg-white/10"
                }`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
        <SearchBox />
        <AvatarMenu />
      </div>
    </header>
  );
}

function AvatarMenu() {
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const initial = (me?.display_name ?? "G").slice(0, 1).toUpperCase();
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="grid h-9 w-9 place-items-center rounded-full bg-surface-2 text-sm font-semibold ring-1 ring-white/10 hover:ring-white/30"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
      >
        {initial}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-52 overflow-hidden rounded-lg border border-white/10 bg-surface py-1 text-sm shadow-2xl"
          onMouseLeave={() => setOpen(false)}
        >
          <MenuLink to="/activity" onClick={() => setOpen(false)}>Taste Profile</MenuLink>
          <MenuLink to="/onboarding" onClick={() => setOpen(false)}>Preferences</MenuLink>
          <MenuLink to="/account" onClick={() => setOpen(false)}>Account</MenuLink>
          {me?.is_guest ? (
            <>
              <MenuLink to="/register" onClick={() => setOpen(false)}>Create account</MenuLink>
              <MenuLink to="/login" onClick={() => setOpen(false)}>Sign in</MenuLink>
            </>
          ) : (
            <button
              className="block w-full px-4 py-2 text-left hover:bg-white/10"
              onClick={async () => {
                await send("POST", "/auth/logout");
                qc.clear();
                setOpen(false);
                navigate("/login");
              }}
            >
              Sign out
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function MenuLink({ to, children, onClick }: { to: string; children: string; onClick: () => void }) {
  return (
    <Link to={to} onClick={onClick} className="block px-4 py-2 hover:bg-white/10" role="menuitem">
      {children}
    </Link>
  );
}