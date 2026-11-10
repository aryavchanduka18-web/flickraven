export type UserState = { rating: number | null; reaction: number; in_list: boolean; watched: boolean };

export type Reason = { code: string; source?: string; text: string; share: number; anchor_movie_id?: number | null };

export type MovieSummary = {
  id: number;
  title: string;
  year: number | null;
  poster: string | null;
  backdrop: string | null;
  logo: string | null;
  genres: string[];
  language: string | null;
  runtime: number | null;
  community_rating: number | null;
  imdb_rating?: number | null;
  imdb_votes?: number | null;
  dominant_color: string | null;
  overview_short: string | null;
  catalog_part?: string;
  title_type?: "movie" | "series" | "anime";
};

export type RecItem = {
  movie: MovieSummary;
  score: number | null;
  match_pct: number | null;
  reasons: Reason[];
  user_state: UserState;
  agreement?: number | null;
};

export type Rail = { key: string; title: string; subtitle?: string | null; source: string; items: RecItem[] };

export type HomePayload = { stage: string; mode: Mode; hero: RecItem[]; rails: Rail[]; page_id: string };

export type Mode = "familiar" | "balanced" | "discover";

export type Me = {
  id: number;
  email: string | null;
  display_name: string | null;
  is_guest: boolean;
  onboarded: boolean;
  discovery_mode: Mode;
  counts: Record<string, number | string>;
};

export type Person = { id: number; name: string; profile_path: string | null; character?: string | null };

export type MovieDetail = {
  id: number;
  tmdb_id: number;
  title: string;
  original_title: string | null;
  overview: string | null;
  tagline: string | null;
  release_date: string | null;
  year: number | null;
  runtime: number | null;
  language: string | null;
  countries: string[] | null;
  certification: string | null;
  poster: string | null;
  backdrop: string | null;
  logo: string | null;
  dominant_color: string | null;
  studios: string[] | null;
  genres: string[];
  keywords: string[];
  awards: { award: string; category: string | null; year: number | null; result: string }[];
  directors: Person[];
  writers: Person[];
  cast: Person[];
  community_rating: number | null;
  imdb_rating?: number | null;
  imdb_votes?: number | null;
  rating_count: number;
  title_type?: "movie" | "series" | "anime";
  seasons?: number | null;
  episodes?: number | null;
  series_status?: string | null;
  rating_hist: number[];
  watch?: import("../components/movie/WhereToWatch").Watch | null;
  user_state: UserState;
  match_pct?: number | null;
  why?: Reason[];
  collection: { id: number; name: string } | null;
  in_profile?: boolean;
  confidence?: import("../components/explain/ConfidenceCard").Confidence;
};

export type FranchiseSection = { key: string; kind: "collection" | "universe" | "director"; title: string; current?: number; items: RecItem[] };