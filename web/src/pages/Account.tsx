import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, send } from "../api/client";
import { useMe } from "../api/hooks";
import { ImportRatings } from "../components/account/ImportRatings";
import { PasswordChecklist } from "../components/account/PasswordChecklist";
import { PageMessage } from "../components/Loading";
import { useUI } from "../components/layout/ui";
import { errorText, field } from "./Auth";

function Section({ title, children, danger }: { title: string; children: ReactNode; danger?: boolean }) {
  return (
    <section className={`rounded-xl border p-5 ${danger ? "border-red-500/30" : "border-white/10"} bg-surface`}>
      <h2 className="font-display text-lg font-bold">{title}</h2>
      <div className="mt-4 space-y-3">{children}</div>
    </section>
  );
}

function Problem({ error }: { error: unknown }) {
  return error ? <p role="alert" className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300">{errorText(error)}</p> : null;
}

const button = "rounded-md bg-white px-4 py-2 text-sm font-semibold text-black disabled:opacity-60";

type Sharing = { enabled: boolean; summary: string | null; min_liked: number };

/** Opt-in, off by default: a short taste line for the AI assistant. Shows the exact words Google would receive. */
export function AiTasteSharing() {
  const qc = useQueryClient();
  const { notify } = useUI();
  const { data } = useQuery({ queryKey: ["taste-sharing"], queryFn: () => api<Sharing>("/assistant/taste-sharing") });
  const save = useMutation({
    mutationFn: (enabled: boolean) => send<Sharing>("PUT", "/assistant/taste-sharing", { enabled }),
    onSuccess: (r) => {
      qc.setQueryData(["taste-sharing"], r);
      qc.invalidateQueries({ queryKey: ["assistant-status"] });
      notify(r.enabled ? "The assistant can now use your taste summary" : "Your taste summary is no longer shared");
    },
  });
  if (!data) return null;
  return (
    <>
      <label className="flex items-start gap-3 text-sm">
        <input type="checkbox" className="mt-1" checked={data.enabled} disabled={save.isPending}
          onChange={(e) => save.mutate(e.target.checked)} />
        <span>
          <b>Share a short taste summary with the AI assistant</b>
          <span className="mt-1 block text-white/70">
            Better-fitting suggestions and a short reason why each one suits you. Off unless you turn it on. Only sent when you ask the
            assistant for suggestions, and it never includes titles, ratings, your name or your email.
          </span>
        </span>
      </label>
      <div className="rounded-md bg-white/[0.04] px-3 py-2 text-sm">
        <p className="text-xs text-muted">Exactly what Google would receive:</p>
        <p className="mt-1 text-white/85">
          {data.summary ?? `Nothing yet. Like or rate at least ${data.min_liked} titles first.`}
        </p>
      </div>
      <Problem error={save.error} />
      <p className="text-xs text-muted">
        The assistant uses Google Gemini's free tier, where Google may use prompts to improve its products. See the{" "}
        <Link to="/privacy" className="underline">Privacy policy</Link>.
      </p>
    </>
  );
}

export default function Account() {
  const { data: me, isLoading } = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { notify } = useUI();
  const [name, setName] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [deletePw, setDeletePw] = useState("");
  const [sure, setSure] = useState(false);

  useEffect(() => setName(me?.display_name ?? ""), [me?.display_name]);
  const { hash } = useLocation();
  useEffect(() => {
    if (me && (hash === "#import" || hash === "#ai")) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [me, hash]);

  const rename = useMutation({
    mutationFn: () => send("PATCH", "/me", { display_name: name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); notify("Name saved"); },
  });
  const change = useMutation({
    mutationFn: () => send("POST", "/auth/change-password", { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent(""); setNext(""); setConfirm("");
      notify("Password changed. Other devices are signed out.");
    },
  });
  const remove = useMutation({
    mutationFn: () => send("DELETE", "/me", me?.is_guest ? {} : { password: deletePw }),
    onSuccess: () => { qc.clear(); navigate("/"); notify("Your account and its data were deleted"); },
  });
  const signOut = async () => {
    await send("POST", "/auth/logout");
    qc.clear();
    navigate("/login");
  };

  if (isLoading || !me) return <PageMessage title="Loading your account" />;
  const mismatch = confirm.length > 0 && confirm !== next;

  return (
    <div className="mx-auto max-w-xl space-y-6 px-4 pb-24 pt-20">
      <h1 className="font-display text-3xl font-extrabold">Account</h1>

      {me.is_guest && (
        <div className="rounded-xl border border-accent/40 bg-accent/10 p-5">
          <p className="font-semibold">You are browsing as a guest.</p>
          <p className="mt-1 text-sm text-white/80">Create an account to keep your taste. Everything you rated, liked and saved moves into it.</p>
          <div className="mt-3 flex gap-3">
            <Link to="/register" className={button}>Create account</Link>
            <Link to="/login" className="rounded-md px-4 py-2 text-sm text-white/85 ring-1 ring-white/20 hover:bg-white/10">Sign in</Link>
          </div>
        </div>
      )}

      <Section title="Profile">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); rename.mutate(); }}>
          <label className="block text-sm text-muted">Name
            <input className={`${field} mt-1`} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
          </label>
          <div className="text-sm text-muted">Email
            <p className="mt-1 text-white">{me.email ?? "None yet (guest)"}</p>
          </div>
          <Problem error={rename.error} />
          <button className={button} disabled={rename.isPending || !name.trim() || name.trim() === me.display_name}>Save name</button>
        </form>
      </Section>

      <div id="ai" className="scroll-mt-24">
        <Section title="AI assistant">
          <AiTasteSharing />
        </Section>
      </div>

      <div id="import" className="scroll-mt-24">
        <Section title="Import your ratings">
          <ImportRatings />
        </Section>
      </div>

      {!me.is_guest && (
        <Section title="Change password">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); change.mutate(); }}>
            <input className={field} type="password" placeholder="Current password" aria-label="Current password" autoComplete="current-password"
              value={current} onChange={(e) => setCurrent(e.target.value)} />
            <input className={field} type="password" placeholder="New password" aria-label="New password" autoComplete="new-password"
              value={next} onChange={(e) => setNext(e.target.value)} />
            <PasswordChecklist password={next} />
            <input className={field} type="password" placeholder="Repeat the new password" aria-label="Repeat the new password" autoComplete="new-password"
              value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            {mismatch && <p className="text-sm text-red-300">The two new passwords do not match.</p>}
            <Problem error={change.error} />
            <p className="text-xs text-muted">Changing it signs you out on every other device.</p>
            <button className={button} disabled={change.isPending || !current || !next || confirm !== next}>Change password</button>
          </form>
        </Section>
      )}

      {!me.is_guest && (
        <Section title="Sign out">
          <button className="rounded-md px-4 py-2 text-sm ring-1 ring-white/20 hover:bg-white/10" onClick={signOut}>Sign out of this device</button>
        </Section>
      )}

      <Section title={me.is_guest ? "Delete guest data" : "Delete account"} danger>
        <p className="text-sm text-white/80">
          This removes {me.is_guest ? "this guest session" : "your account"} and all of its ratings, likes, My List, watched films and activity
          history. It cannot be undone.
        </p>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); remove.mutate(); }}>
          {!me.is_guest && (
            <input className={field} type="password" placeholder="Your password" aria-label="Password to confirm deletion" autoComplete="current-password"
              value={deletePw} onChange={(e) => setDeletePw(e.target.value)} />
          )}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /> I understand this cannot be undone
          </label>
          <Problem error={remove.error} />
          <button className="rounded-md bg-red-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            disabled={remove.isPending || !sure || (!me.is_guest && !deletePw)}>
            {me.is_guest ? "Delete guest data" : "Delete my account"}
          </button>
        </form>
      </Section>

      <p className="text-xs text-muted">
        FlickRaven does not send emails, so there is no password reset. Keep your password safe. See the <Link to="/privacy" className="underline">Privacy policy</Link> for what is stored.
      </p>
    </div>
  );
}
