import { describe, expect, it } from "vitest";
import { readAddIntent, type ListCard } from "./assistantActions";

const cards: ListCard[] = [
  { id: 11, title: "Heat", inList: false },
  { id: 22, title: "The Dark Knight", inList: false },
  { id: 33, title: "Prisoners", inList: true },
];
const one: ListCard[] = [{ id: 11, title: "Heat", inList: false }];

describe("readAddIntent", () => {
  it("a bare yes adds the only card, and asks which one when there are several", () => {
    expect(readAddIntent("Yes, add it!", one)).toEqual({ kind: "add", ids: [11] });
    expect(readAddIntent("sure", one)).toEqual({ kind: "add", ids: [11] });
    expect(readAddIntent("yes please add it to my list", cards)).toEqual({ kind: "which" });
  });

  it("picks by position, by 'last' and by title", () => {
    expect(readAddIntent("add the second one", cards)).toEqual({ kind: "add", ids: [22] });
    expect(readAddIntent("Add #1 and 2", cards)).toEqual({ kind: "add", ids: [11, 22] });
    expect(readAddIntent("add the dark knight to my watchlist", cards)).toEqual({ kind: "add", ids: [22] });
    expect(readAddIntent("save heat", cards)).toEqual({ kind: "add", ids: [11] });
    expect(readAddIntent("yes add them all", cards)).toEqual({ kind: "add", ids: [11, 22] });
  });

  it("already saved titles are reported, not added again", () => {
    expect(readAddIntent("add the last one", cards)).toEqual({ kind: "saved", titles: ["Prisoners"] });
    expect(readAddIntent("yes", [cards[2]])).toEqual({ kind: "saved", titles: ["Prisoners"] });
  });

  it("only shown titles can be added; an add for anything else is refused", () => {
    expect(readAddIntent("add Inception to my list", cards)).toEqual({ kind: "unknown" });
    expect(readAddIntent("add the fifth one", cards)).toEqual({ kind: "unknown" });
    expect(readAddIntent("yes", [])).toBeNull();
  });

  it("ordinary messages still go to the assistant", () => {
    expect(readAddIntent("yes but something lighter", cards)).toBeNull();
    expect(readAddIntent("what is the second one about?", cards)).toBeNull();
    expect(readAddIntent("tell me about heat", cards)).toBeNull();
    expect(readAddIntent("the second one", cards)).toBeNull();
    expect(readAddIntent("I like the dark knight", cards)).toBeNull();
  });

  it("a bare yes answers the reply's own question; an explicit add or a pick still adds", () => {
    expect(readAddIntent("yes", one, true)).toBeNull();
    expect(readAddIntent("yes add it", one, true)).toEqual({ kind: "add", ids: [11] });
    expect(readAddIntent("the second one", cards, false, true)).toEqual({ kind: "add", ids: [22] });
  });
});
