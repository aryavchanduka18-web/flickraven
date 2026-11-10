/** Splits an assistant reply into plain text, spoilers (between || and ||) and title marks ([[Title (Year)]]).
 *  Everything stays text: the page renders these parts as React text, never as HTML. */
export type Part = { kind: "text" | "spoiler" | "title"; text: string };

export function parseReply(reply: string): Part[] {
  const parts: Part[] = [];
  const re = /\|\|([\s\S]+?)\|\||\[\[(.+?)\]\]/g;
  let last = 0;
  for (let m = re.exec(reply); m; m = re.exec(reply)) {
    if (m.index > last) parts.push({ kind: "text", text: reply.slice(last, m.index) });
    parts.push(m[1] !== undefined ? { kind: "spoiler", text: m[1] } : { kind: "title", text: m[2] });
    last = m.index + m[0].length;
  }
  if (last < reply.length) parts.push({ kind: "text", text: reply.slice(last) });
  return parts;
}

/** "Heat (1995)" -> "heat": how a title mark is matched to a catalog card. */
export const titleKey = (mark: string) => mark.replace(/\s*\(\d{4}\)\s*$/, "").trim().toLowerCase();
