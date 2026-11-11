import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, send } from "./client";
import type { FranchiseSection, HomePayload, Me, Mode, MovieDetail, RecItem } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me"), staleTime: 30_000 });

export const useHome = (mode?: Mode) =>
  useQuery({ queryKey: ["home", mode ?? "saved"], queryFn: () => api<HomePayload>(`/recs/home${mode ? `?mode=${mode}` : ""}`) });

export const useMovie = (id: number) => useQuery({ queryKey: ["movie", id], queryFn: () => api<MovieDetail>(`/movies/${id}`) });

export type SimilarPage = { items: RecItem[]; total: number; offset: number; cross_kind?: { title: string; items: RecItem[] } };

/** More Like This, first `limit` titles (same type as the title, with reasons). */
export const useSimilar = (id: number, limit = 8) =>
  useQuery({ queryKey: ["similar", id, limit], queryFn: () => api<SimilarPage>(`/movies/${id}/similar?limit=${limit}`) });

export const useFranchise = (id: number) =>
  useQuery({ queryKey: ["franchise", id], queryFn: () => api<{ sections: FranchiseSection[] }>(`/movies/${id}/franchise`) });

export type CollectionRail = { key: string; title: string; count: number; items: RecItem[] };

export const useCollections = () =>
  useQuery({ queryKey: ["collections"], queryFn: () => api<{ collections: CollectionRail[] }>("/collections"), staleTime: 60_000 });

/** Series or anime for this user: content similarity to their taste plus popularity (no ratings exist for them). */
export const useKindRail = (kind: "series" | "anime") =>
  useQuery({ queryKey: ["kind", kind], queryFn: () => api<{ items: RecItem[]; total: number }>(`/recs/kind/${kind}?limit=24`), staleTime: 60_000 });

export type SeriesRail = { key: string; title: string; subtitle: string; items: RecItem[] };

/** Themed series rows (Korean, Japanese, Indian, Anglo and international dramas for you, quick comedy, because you liked ..., a films-and-series mix). */
export const useSeriesRails = () =>
  useQuery({ queryKey: ["series-rails"], queryFn: () => api<{ rails: SeriesRail[]; engaged_series?: number }>("/recs/series-rails"), staleTime: 60_000 });

/** The Anime page: anime series and anime films only (see api/app/services/anime_rows.py). */
export const useAnimeRails = () =>
  useQuery({ queryKey: ["anime-rails"], queryFn: () => api<{ rails: SeriesRail[]; counts?: { series: number; films: number } }>("/recs/anime"), staleTime: 60_000 });

type FeedbackAction =
  | { kind: "rate"; rating: number | null }
  | { kind: "react"; value: 1 | -1 | 0 }
  | { kind: "list"; on: boolean }
  | { kind: "watched"; on: boolean };

type State = { rating: number | null; reaction: number; in_list: boolean; watched: boolean };

/** Walk any cached payload: give this film's cards the new user state, and (when `drop`) take the film out of
 *  lists entirely. Works for every shape we cache (home rails, collections, pages, film detail). */
export function patchFilm(data: unknown, id: number, change: Partial<State>, drop: boolean): unknown {
  if (Array.isArray(data)) {
    const out = drop ? data.filter((x) => !(x && typeof x === "object" && (x as RecItem).movie?.id === id)) : data;
    return out.map((x) => patchFilm(x, id, change, drop));
  }
  if (data && typeof data === "object") {
    const o = data as Record<string, unknown>;
    const isFilm = (o.movie as { id?: number } | undefined)?.id === id || (o.id === id && "user_state" in o);
    const next: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(o)) next[k] = k === "user_state" && isFilm ? { ...(v as State), ...change } : patchFilm(v, id, change, drop);
    return next;
  }
  return data;
}

/** Like / dislike / list / watched / rate with an immediate refresh of everything personal (spec 6.12).
 *  Every cached list is updated at once (optimistic), and a disliked or watched film leaves Home and the
 *  collection rows straight away, before the server's fresh lists arrive. */
export function useFeedback(movieId: number, source?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: FeedbackAction) => {
      switch (a.kind) {
        case "rate":
          return a.rating ? send("PUT", `/ratings/${movieId}`, { rating: a.rating, source }) : send("DELETE", `/ratings/${movieId}`);
        case "react":
          return a.value ? send("PUT", `/reactions/${movieId}`, { value: a.value, source }) : send("DELETE", `/reactions/${movieId}`);
        case "list":
          return a.on ? send("PUT", `/list/${movieId}`, { source }) : send("DELETE", `/list/${movieId}`);
        case "watched":
          return a.on ? send("PUT", `/watched/${movieId}`) : send("DELETE", `/watched/${movieId}`);
      }
    },
    onMutate: (a: FeedbackAction) => {
      const change: Partial<State> =
        a.kind === "rate" ? { rating: a.rating } : a.kind === "react" ? { reaction: a.value }
          : a.kind === "list" ? { in_list: a.on } : { watched: a.on };
      const leaves = (a.kind === "react" && a.value === -1) || (a.kind === "watched" && a.on);
      for (const key of ["home", "collections", "genre", "discover", "franchise", "person-movies", "search", "similar", "movie", "list"]) {
        qc.setQueriesData({ queryKey: [key] }, (d: unknown) =>
          d === undefined ? d : patchFilm(d, movieId, change, leaves && (key === "home" || key === "collections")));
      }
    },
    onSettled: () => {
      for (const key of ["home", "movie", "me", "list", "activity", "genre", "taste", "franchise", "collections"]) qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

/** "Not interested": the title leaves every recommendation row at once (before the server answers) and stays out
 *  for 90 days. It is not a dislike and does not change the taste profile. */
export function useNotInterested(movieId: number, source?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (undo: boolean) =>
      undo ? send("DELETE", `/feedback/not-interested/${movieId}`) : send("PUT", `/feedback/not-interested/${movieId}`, { source }),
    onMutate: (undo: boolean) => {
      for (const key of ["home", "collections", "kind", "series-rails"]) {
        qc.setQueriesData({ queryKey: [key] }, (d: unknown) => (d === undefined || undo ? d : patchFilm(d, movieId, {}, true)));
      }
    },
    onSettled: () => {
      for (const key of ["home", "collections", "kind", "series-rails", "movie", "activity", "activity-titles", "not-interested"]) qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

/** Hide a Home row for 30 days, or bring every hidden row back. */
export function useHideRow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (source: string | null) => (source ? send("PUT", "/feedback/rows", { source }) : send("DELETE", "/feedback/rows")),
    onSettled: () => qc.invalidateQueries({ queryKey: ["home"] }),
  });
}

export function useLogEvent() {
  return (event_type: "detail_view" | "quick_view" | "search_click" | "hero_view", movie_id: number, source?: string, position?: number) =>
    send("POST", "/events", { event_type, movie_id, source, position }).catch(() => undefined);
}

export function useSetMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: Mode) => send("PUT", "/me/preferences", { discovery_mode: mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["home"] });
    },
  });
}