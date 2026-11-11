/** Reads a short typed answer to the chat's "Want me to add this to your list?" line, entirely in the browser.
 *  Nothing here goes to Gemini or to the chat endpoint: a match is turned into a normal My List add for a card
 *  FlickRaven itself showed in the latest reply. Anything that is not clearly an add answer returns null and is sent
 *  to the assistant as an ordinary message. */
export type ListCard = { id: number; title: string; inList: boolean };

export type AddIntent =
  | { kind: "add"; ids: number[] }       // add these (never empty, never already saved)
  | { kind: "saved"; titles: string[] }  // everything they asked for is already in the list
  | { kind: "which" }                    // "yes" with several unsaved cards: ask which one
  | { kind: "unknown" };                 // an explicit "add X to my list" for something not shown in the latest reply

const YES = new Set(["yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please", "pls", "plz", "go", "ahead", "do", "it",
  "add", "save", "put", "that", "this", "one", "the", "to", "in", "into", "my", "list", "watchlist", "watch", "later",
  "and", "thanks", "thank", "you", "a", "for", "me", "too", "also", "great", "nice", "cool", "sounds", "good", "perfect"]);
const ALL = new Set(["all", "them", "both", "everything", "each", "every", "those", "these", "of"]);
const ORDINALS: Record<string, number> = {
  first: 0, "1st": 0, "1": 0, second: 1, "2nd": 1, "2": 1, third: 2, "3rd": 2, "3": 2,
  fourth: 3, "4th": 3, "4": 3, fifth: 4, "5th": 4, "5": 4, sixth: 5, "6th": 5, "6": 5,
};
const ACTION = /\b(add|save|put)\b/;
const AGREE = /^(yes|yeah|yep|yup|sure|ok|okay|please|pls|plz|go ahead|do it)\b/;

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();

/** `replyAsked`: the latest reply's own text asked a question ("Want something darker?"). A bare "yes" then answers
 *  that question, so it goes to the assistant; only an explicit "add ..." or a pick ("the second one") adds. */
/** `picking`: the chat just asked "Which one?", so a bare "the first one" is an answer too. */
export function readAddIntent(message: string, cards: ListCard[], replyAsked = false, picking = false): AddIntent | null {
  const t = norm(message);
  if (!t || !cards.length || message.includes("?") || t.split(" ").length > 14) return null;
  const explicit = ACTION.test(t);
  if (!explicit && !picking && !AGREE.test(t)) return null;

  const words = t.split(" ");
  const ordinal = words.filter((w) => w in ORDINALS).map((w) => ORDINALS[w]);
  const last = words.includes("last");
  const all = words.some((w) => ALL.has(w));
  const rest = words.filter((w) => !YES.has(w) && !ALL.has(w) && !(w in ORDINALS) && w !== "last").join(" ");

  let picked: ListCard[];
  if (rest) {
    // Leftover words must name one of the shown cards ("add heat", "yes, the dark knight"); otherwise this is a new
    // request ("yes but something lighter") and goes to the assistant as usual.
    const hits = cards.filter((c) => { const n = norm(c.title); return n === rest || ` ${n} `.includes(` ${rest} `); });
    if (hits.length !== 1) return explicit && /\b(list|watchlist)\b/.test(t) && !ordinal.length && !all ? { kind: "unknown" } : null;
    picked = hits;
  } else if (ordinal.length || last) {
    const idx = [...ordinal, ...(last ? [cards.length - 1] : [])];
    if (idx.some((i) => i >= cards.length)) return explicit ? { kind: "unknown" } : null;
    picked = [...new Set(idx)].map((i) => cards[i]);
  } else if (all) {
    picked = cards;
  } else {
    if (!explicit && replyAsked) return null;
    const open = cards.filter((c) => !c.inList);
    if (!open.length) return { kind: "saved", titles: cards.map((c) => c.title) };
    if (open.length > 1) return { kind: "which" };
    picked = open;
  }
  const ids = picked.filter((c) => !c.inList).map((c) => c.id);
  return ids.length ? { kind: "add", ids } : { kind: "saved", titles: picked.map((c) => c.title) };
}
