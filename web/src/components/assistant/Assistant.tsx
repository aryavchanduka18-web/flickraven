import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, send } from "../../api/client";
import type { RecItem } from "../../api/types";
import { readAddIntent, type AddIntent } from "../../lib/assistantActions";
import { parseReply, titleKey } from "../../lib/assistantText";
import { SparkIcon } from "../layout/icons";

// `local`: an add-to-list exchange handled in the browser. It is never sent to the chat endpoint or to Gemini,
// so what someone saves does not reach Google.
type Msg = { role: "user" | "assistant"; text: string; items?: RecItem[]; local?: boolean };
type Status = { enabled: boolean; remaining: number; cap: number };
const CHIPS = ["Something like Prisoners, with a bigger twist", "A light comedy under two hours", "What is Inception about?", "Something outside my usual genres"];

function Spoiler({ text }: { text: string }) {
  const [shown, setShown] = useState(false);
  return (
    <button type="button" onClick={() => setShown(true)} aria-label={shown ? "Spoiler" : "Spoiler, tap to show"}
      className={`rounded px-1 transition ${shown ? "bg-white/10" : "bg-white/20 text-transparent blur-[5px] hover:bg-white/30"}`}>{text}</button>
  );
}

function Reply({ msg }: { msg: Msg }) {
  const byTitle = new Map((msg.items ?? []).map((i) => [i.movie.title.toLowerCase(), i]));
  return (
    <>
      {parseReply(msg.text).map((p, i) => {
        if (p.kind === "spoiler") return <Spoiler key={i} text={p.text} />;
        if (p.kind === "title") {
          const hit = byTitle.get(titleKey(p.text));
          return hit ? <Link key={i} to={`/movie/${hit.movie.id}`} className="font-semibold underline underline-offset-2">{p.text}</Link> : <span key={i} className="font-semibold">{p.text}</span>;
        }
        return <span key={i}>{p.text}</span>;
      })}
    </>
  );
}

const WHICH = "Which one? Tap + My List on its card, or type “the first one”.";
const fmtList = (t: string[]) => (t.length < 2 ? t[0] ?? "" : `${t.slice(0, -1).join(", ")} and ${t.at(-1)}`);

/** The titles a reply recommended, each with its own My List button. The assistant only proposes; the add happens
 *  when the person taps (or types "add it") and uses the normal My List endpoint with their own sign-in. */
function ReplyCards({ items, busy, failed, onAdd }: { items: RecItem[]; busy: Set<number>; failed: Set<number>; onAdd: (ids: number[]) => void }) {
  const open = items.filter((i) => !i.user_state.in_list);
  return (
    <div className="mt-2.5 space-y-1.5">
      {items.map((it, n) => (
        <div key={it.movie.id} className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-2.5 py-1.5">
          <span className="w-4 shrink-0 text-[11px] text-white/40">{n + 1}</span>
          <div className="min-w-0 flex-1">
            <Link to={`/movie/${it.movie.id}`} className="block truncate font-semibold hover:underline">
              {it.movie.title}{it.movie.year ? <span className="font-normal text-white/50"> ({it.movie.year})</span> : null}
            </Link>
            {it.reasons?.[0]?.code === "taste_dna" && <p className="text-[11px] leading-snug text-white/55">{it.reasons[0].text}</p>}
          </div>
          {it.user_state.in_list ? (
            <span className="shrink-0 text-xs text-white/60">✓ In your list</span>
          ) : (
            <button type="button" disabled={busy.has(it.movie.id)} onClick={() => onAdd([it.movie.id])}
              aria-label={`Add ${it.movie.title} to My List`} className="glass-btn shrink-0 rounded-full px-2.5 py-1 text-xs disabled:opacity-60">
              {busy.has(it.movie.id) ? "Adding…" : failed.has(it.movie.id) ? "Retry add" : "+ My List"}
            </button>
          )}
        </div>
      ))}
      {open.length > 0 && (
        <p className="pt-0.5 text-xs text-white/60">
          {items.length === 1 ? "Want me to add this to your list?" : "Want me to add one to your list?"} Tap the button, or type
          {items.length === 1 ? " “yes, add it”." : " “add the second one”."}
        </p>
      )}
    </div>
  );
}

/** A floating chat button and panel. Replies come from Gemini via our server; titles in a reply link only when
 *  they exist in our catalog. User text is shown as text, never as HTML. */
function AssistantInner() {
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api<Status>("/assistant/status"), staleTime: 60_000, retry: false });
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<Set<number>>(new Set());
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const busyRef = useRef<Set<number>>(new Set());   // guards double clicks before React re-renders
  const qc = useQueryClient();
  const box = useRef<HTMLDivElement>(null);
  const chat = useMutation({
    mutationFn: (history: Msg[]) => send<{ reply: string; items: RecItem[]; remaining: number }>("POST", "/assistant/chat",
      { messages: history.filter((m) => !m.local).map(({ role, text }) => ({ role, text })) }),
    onSuccess: (r) => { setMsgs((m) => [...m, { role: "assistant", text: r.reply, items: r.items }]); status.refetch(); },
  });
  // Scroll only the chat's own list. scrollIntoView could also scroll the whole page.
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight; }, [msgs, chat.isPending, chat.isError]);
  const titleOf = (id: number) => msgs.flatMap((m) => m.items ?? []).find((i) => i.movie.id === id)?.movie.title ?? "That title";
  const markSaved = (id: number) =>
    setMsgs((all) => all.map((m) => (m.items?.some((i) => i.movie.id === id)
      ? { ...m, items: m.items.map((i) => (i.movie.id === id ? { ...i, user_state: { ...i.user_state, in_list: true } } : i)) } : m)));
  const setIn = (set: typeof setBusy, id: number, on: boolean) => set((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n; });

  /** Adds through PUT /api/list/{id}, the same call as every other My List button. Returns the titles that failed. */
  const addToList = async (ids: number[]): Promise<string[]> => {
    const todo = ids.filter((id) => !busyRef.current.has(id));
    todo.forEach((id) => { busyRef.current.add(id); setIn(setBusy, id, true); setIn(setFailed, id, false); });
    const results = await Promise.all(todo.map(async (id) => {
      try {
        await send("PUT", `/list/${id}`, { source: "assistant" });
        markSaved(id);
        return null;
      } catch {
        setIn(setFailed, id, true);
        return titleOf(id);
      } finally {
        busyRef.current.delete(id);
        setIn(setBusy, id, false);
      }
    }));
    if (results.some((r) => r === null)) for (const k of ["list", "home", "me", "movie", "collections"]) qc.invalidateQueries({ queryKey: [k] });
    return results.filter((r): r is string => r !== null);
  };

  const answerLocally = async (said: string, intent: AddIntent, cards: RecItem[]) => {
    const say = (text: string) => setMsgs((m) => [...m, { role: "assistant", text, local: true }]);
    setMsgs((m) => [...m, { role: "user", text: said, local: true }]);
    setDraft("");
    if (intent.kind === "which") return say(WHICH);
    if (intent.kind === "unknown") return say("I can only add titles I showed you in my last answer. To save something else, open its page and use + My List.");
    if (intent.kind === "saved") return say(`${fmtList(intent.titles)} ${intent.titles.length > 1 ? "are" : "is"} already in your list.`);
    const names = intent.ids.map((id) => cards.find((c) => c.movie.id === id)?.movie.title ?? "");
    const bad = await addToList(intent.ids);
    const ok = names.filter((n) => !bad.includes(n));
    if (ok.length) say(`Added ${fmtList(ok)} to your list.${bad.length ? ` I could not add ${fmtList(bad)}; tap Retry add to try again.` : ""}`);
    else say(`I could not add ${fmtList(bad)} right now. Tap Retry add to try again.`);
  };

  if (!status.data?.enabled) return null;
  const submit = (text: string) => {
    const t = text.trim();
    if (!t || chat.isPending) return;
    // A short "yes, add it" / "add the second one" right after a reply with cards is handled here, without Gemini.
    // Cards come only from the latest real reply, and only if nothing new was asked since.
    const lastReal = [...msgs].reverse().find((m) => !m.local);
    const reply = lastReal?.role === "assistant" ? lastReal : undefined;
    const cards = reply?.items ?? [];
    const intent = readAddIntent(t, cards.map((i) => ({ id: i.movie.id, title: i.movie.title, inList: i.user_state.in_list })),
      !!reply && parseReply(reply.text).some((p) => p.kind === "text" && p.text.includes("?")), msgs.at(-1)?.text === WHICH);
    if (intent) { void answerLocally(t, intent, cards); return; }
    const next: Msg[] = [...msgs, { role: "user", text: t }];
    setMsgs(next);
    setDraft("");
    chat.mutate(next);
  };
  const retry = () => { if (!chat.isPending && msgs.at(-1)?.role === "user") chat.mutate(msgs); };
  return (
    <>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="Ask FlickRaven"
        className="glass-btn fixed bottom-24 right-4 z-40 h-[54px] rounded-full px-0 md:bottom-6 md:right-6 md:h-auto md:px-5 md:py-3">
        <SparkIcon className="h-5 w-5 shrink-0 max-md:mx-4" /><span className="hidden text-sm font-semibold md:inline">Ask FlickRaven</span>
      </button>
      {open && (
        <section role="dialog" aria-label="Ask FlickRaven" className="chat-panel fixed bottom-40 right-3 z-50 flex max-h-[70vh] w-[min(380px,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-3xl md:bottom-20 md:right-6">
          <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <b>Ask FlickRaven</b>
            <span className="text-xs text-white/50">{status.data.remaining} of {status.data.cap} messages left today</span>
            <button onClick={() => setOpen(false)} aria-label="Close" className="glass-btn h-8 w-8 rounded-full">✕</button>
          </header>
          <div ref={box} className="flex-1 space-y-2.5 overflow-y-auto overscroll-contain p-4 text-[13.5px]">
            {!msgs.length && (
              <div>
                <p className="text-white/70">Ask for a recommendation, a plot, an ending or anything else about films and series. Spoilers stay hidden until you tap.</p>
                <div className="mt-3 flex flex-wrap gap-2">{CHIPS.map((c) => <button key={c} onClick={() => submit(c)} className="glass-btn rounded-full px-3 py-1.5 text-left text-xs">{c}</button>)}</div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`max-w-[92%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 ${m.role === "user" ? "ml-auto bg-white text-black" : "border border-white/10 bg-white/[0.06]"}`}>
                {m.role === "user" ? m.text : <Reply msg={m} />}
                {m.role === "assistant" && !!m.items?.length && <ReplyCards items={m.items} busy={busy} failed={failed} onAdd={(ids) => void addToList(ids)} />}
              </div>
            ))}
            {chat.isPending && <div className="w-16 animate-pulse rounded-2xl bg-white/10 px-3.5 py-2.5">…</div>}
            {chat.isError && (
              <p role="alert" className="text-red-300">
                {(chat.error as Error).message || "Something went wrong."}{" "}
                <button type="button" onClick={retry} className="underline">Try again</button>
              </p>
            )}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); submit(draft); }} className="flex gap-2 border-t border-white/10 p-3">
            <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={1000} placeholder="Ask anything about films or series" aria-label="Message"
              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm placeholder:text-white/45 focus:border-white/30 focus:outline-none" />
            <button type="submit" disabled={chat.isPending} className="glass-btn solid rounded-xl px-4 text-sm font-semibold disabled:opacity-60">Send</button>
          </form>
          <p className="px-4 pb-3 text-[11px] text-white/40">AI can be wrong. Answers come from Google Gemini; see the privacy page for what is sent.</p>
        </section>
      )}
    </>
  );
}

/** If anything inside the chat throws while rendering, only the chat disappears. The rest of the site keeps working. */
class ChatBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: unknown) { console.error("assistant crashed", e); }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export default function Assistant() {
  return <ChatBoundary><AssistantInner /></ChatBoundary>;
}
