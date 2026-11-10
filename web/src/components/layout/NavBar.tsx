import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useMe } from "../../api/hooks";
import { send } from "../../api/client";
import SearchBox from "./SearchBox";

export const TABS = [
  { to: "/", label: "Home" },
  { to: "/discover", label: "Discover" },
  { to: "/pick", label: "Perfect Pick" },
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

export function Logo({ className = "h-9" }: { className?: string }) {
  return (
    <Link to="/" aria-label="FlickRaven home" className="inline-flex">
      <img src="/flickraven-logo.png" alt="FlickRaven" width={719} height={179} className={`${className} w-auto select-none`} draggable={false} />
    </Link>
  );
}

export default function NavBar() {
  const scrolled = useScrolled();
  return (
    <header
      className={`fixed inset-x-0 top-0 z-40 transition-colors duration-200 md:hidden ${
        scrolled ? "bg-bg/95 shadow-[0_1px_0_#ffffff10]" : "bg-gradient-to-b from-black/70 to-transparent"
      }`}
    >
      <div className="mx-auto flex h-16 items-center gap-3 px-4">
        <Logo className="h-8" />
        <SearchBox />
        <AvatarMenu />
      </div>
    </header>
  );
}

export function AvatarMenu({ up = false, withName = false }: { up?: boolean; withName?: boolean }) {
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const initial = (me?.display_name ?? "G").slice(0, 1).toUpperCase();
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={withName ? "flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left hover:bg-white/10" : "grid h-9 w-9 place-items-center rounded-full bg-surface-2 text-sm font-semibold ring-1 ring-white/10 hover:ring-white/30"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
      >
        {withName ? (
          <>
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-bold">{initial}</span>
            <span className="min-w-0 truncate text-[15px] font-semibold">{me?.display_name ?? "Guest"}</span>
          </>
        ) : initial}
      </button>
      {open && (
        <div
          role="menu"
          className={`absolute z-50 w-52 overflow-hidden rounded-2xl border border-white/10 bg-surface/95 py-1 text-sm shadow-2xl backdrop-blur-xl ${up ? "bottom-full left-0 mb-2" : "right-0 mt-2"}`}
          onMouseLeave={() => setOpen(false)}
        >
          <MenuLink to="/taste-dna" onClick={() => setOpen(false)}>My Taste DNA</MenuLink>
          <MenuLink to="/activity" onClick={() => setOpen(false)}>Taste Profile</MenuLink>
          <MenuLink to="/performance" onClick={() => setOpen(false)}>Recommendation report</MenuLink>
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