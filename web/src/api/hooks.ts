import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, send } from "./client";
import type { FranchiseSection, HomePayload, Me, Mode, MovieDetail, RecItem } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me"), staleTime: 30_000 });

export const useHome = (mode?: Mode) =>
  useQuery({ queryKey: ["home", mode ?? "saved"], queryFn: () => api<HomePayload>(`/recs/home${mode ? `?mode=${mode}` : ""}`) });

export const useMovie = (id: number) => useQuery({ queryKey: ["movie", id], queryFn: () => api<MovieDetail>(`/movies/${id}`) });

export const useSimilar = (id: number) =>
  useQuery({ queryKey: ["similar", id], queryFn: () => api<{ items: RecItem[] }>(`/movies/${id}/similar`) });

export const useFranchise = (id: number) =>
  useQuery({ queryKey: ["franchise", id], queryFn: () => api<{ sections: FranchiseSection[] }>(`/movies/${id}/franchise`) });

export type CollectionRail = { key: string; title: string; count: number; items: RecItem[] };

export const useCollections = () =>
  useQuery({ queryKey: ["collections"], queryFn: () => api<{ collections: CollectionRail[] }>("/collections"), staleTime: 60_000 });

/** Series or anime for this user: content similarity to their taste plus popularity (no ratings exist for them). */
export const useKindRail = (kind: "series" | "anime") =>
  useQuery({ queryKey: ["kind", kind], queryFn: () => api<{ items: RecItem[]; total: number }>(`/recs/kind/${kind}?limit=24`), staleTime: 60_000 });

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

export function useLogEvent() {
  return (event_type: "detail_view" | "quick_view" | "search_click" | "hero_view", movie_id: number, source?: string, position?: number) =>
    send("POST", "/events", { event_type, movie_id, source, position }).catch(() => undefined);
}

/** Anime rows, tabs and onboarding picks are optional (off by default); anime stays searchable either way. */
export function useSetShowAnime() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) => send("PUT", "/me/preferences", { show_anime: on }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["kind"] });
    },
  });
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