import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useMe } from "../../api/hooks";

const KEY = "cm_guest_banner_closed";
const HIDDEN_ON = ["/login", "/register", "/onboarding", "/account"];

function closedBefore(): boolean {
  try {
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** A slim bar under the nav for guests who have started to build a taste profile. */
export default function GuestBanner() {
  const { data: me } = useMe();
  const { pathname } = useLocation();
  const [closed, setClosed] = useState(closedBefore);
  const started = me && (Number(me.counts.ratings) + Number(me.counts.likes) + Number(me.counts.list) + Number(me.counts.onboarding_count) > 0);
  if (!me?.is_guest || !started || closed || HIDDEN_ON.includes(pathname)) return null;
  const close = () => {
    setClosed(true);
    try {
      sessionStorage.setItem(KEY, "1");
    } catch {
      /* private mode: just hide it for now */
    }
  };
  return (
    <div className="shell-main fixed inset-x-0 top-16 z-30 flex justify-center px-4 md:top-4" role="region" aria-label="Guest notice">
      <div className="flex items-center gap-3 rounded-full border border-white/10 bg-surface/95 py-1.5 pl-4 pr-1.5 text-sm shadow-xl backdrop-blur">
        <span>Create an account to keep your taste</span>
        <Link to="/register" className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-black">Create account</Link>
        <button onClick={close} aria-label="Hide this notice" className="grid h-7 w-7 place-items-center rounded-full text-white/60 hover:bg-white/10">✕</button>
      </div>
    </div>
  );
}
