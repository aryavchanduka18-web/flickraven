import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { RecItem } from "../../api/types";
import { SimilarGrid } from "./PosterCard";

const mk = (id: number, match: number | null): RecItem => ({
  movie: { id, title: `Film ${id}`, year: 2000 + id, poster: "/p.jpg", backdrop: null, logo: null, genres: [], language: "en", runtime: 100,
    community_rating: null, imdb_rating: 7.1, imdb_votes: 5000, dominant_color: null, overview_short: null },
  score: null, match_pct: match, reasons: [{ code: "k", text: "Shares the keyword heist", share: 1 }],
  user_state: { rating: null, reaction: 0, in_list: false, watched: false },
});

describe("SimilarGrid", () => {
  it("is three columns wide, with the Match % badge only where the API sent one, and title, rating and year under the poster", () => {
    render(<MemoryRouter><SimilarGrid items={[mk(1, 84), mk(2, null), mk(3, 70)]} source="t" /></MemoryRouter>);
    const grid = screen.getByTestId("similar-grid");
    expect(grid.className).toContain("sm:grid-cols-3");
    expect(screen.getByText("84% match")).toBeTruthy();
    expect(screen.queryAllByText(/% match/).length).toBe(2);
    expect(screen.getByText("Film 2")).toBeTruthy();
    expect(screen.getByText("2002")).toBeTruthy();
  });
});
