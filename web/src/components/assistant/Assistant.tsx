import { useMutation, useQuery } from "@tanstack/react-query";
import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, send } from "../../api/client";
import type { RecItem } from "../../api/types";
import { parseReply, titleKey } from "../../lib/assistantText";
import { SparkIcon } from "../layout/icons";

type Msg = { role: "user" | "assistant"; text: string; items?: RecItem[] };
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

/** A floating chat button and panel. Replies come from Gemini via our server; titles in a reply link only when
 *  they exist in our catalog. User text is shown as text, never as HTML. */
function AssistantInner() {
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api<Status>("/assistant/status"), staleTime: 60_000, retry: false });
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const chat = useMutation({
    mutationFn: (history: Msg[]) => send<{ reply: string; items: RecItem[]; remaining: number }>("POST", "/assistant/chat", { messages: history.map(({ role, text }) => ({ role, text })) }),
    onSuccess: (r) => { setMsgs((m) => [...m, { role: "assistant", text: r.reply, items: r.items }]); status.refetch(); },
  });
  // Scroll only the chat's own list. scrollIntoView could also scroll the whole page.
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight; }, [msgs, chat.isPending, chat.isError]);
  if (!status.data?.enabled) return null;
  const submit = (text: string) => {
    const t = text.trim();
    if (!t || chat.isPending) return;
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
