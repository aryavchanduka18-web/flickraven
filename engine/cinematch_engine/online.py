"""The live engine: one user, the whole product catalog (spec sections 6 and 7).

Catalog space = every film in the product catalog (parts A-D). Content and popularity score every
film; item CF, user CF, SVD and ALS only know the MovieLens films (the evaluation universe) and give
no score elsewhere. Films they cannot score are scored by the sources that can, mapped onto the MovieLens scale
(availability.py), so parts B, C and D can compete. Everything else (candidate pool, percentile
normalization, stage blend, Match %, MMR, explanations) is the same code that was evaluated offline.
"""
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from sklearn.preprocessing import normalize

from cinematch_engine.availability import AvailabilityMap, renormalized
from cinematch_engine.blend import candidate_pool, contributions
from cinematch_engine.config import event_weights
from cinematch_engine.explain import explain
from cinematch_engine.profile import WEAK_EVENTS, stage_of
from cinematch_engine.rerank import refresh, MODES, TAIL_PCT, TOP_N, mmr, spread, tail_slots
from cinematch_engine.sources import SOURCES, Profiles, SourceModels
from cinematch_engine.surprise import REASON as SURPRISE_REASON
from cinematch_engine.tonight import Request, recommend as tonight_recommend

POPCORN_GENRES = {"Action", "Adventure", "Comedy", "Animation", "Science Fiction"}
FEEL_GOOD_GENRES = {"Comedy", "Romance", "Family", "Animation", "Music"}      # the For Tonight "Feel-good" rule
# "Indian and English" end of the International tuning slider.
LOCAL_LANGUAGES = {"en", "hi", "ta", "te", "ml", "kn", "bn", "mr"}
# Popularity points (1-10 scale) added to films in the user's onboarding languages, by stage (language_lift).
LANGUAGE_LIFT = {"cold": 1.2, "warming": 0.6, "established": 0.0}
# Explicit language preferences persist after onboarding. The candidate lift only helps retrieval;
# this small score term is the measured reranking signal for established users.
PERSISTENT_LANGUAGE_CANDIDATE_LIFT = 2.4
PERSISTENT_LANGUAGE_RERANK_BOOST = 0.24


@dataclass
class Tuning:
    """The user's Tune sliders, 0-100 with 50 neutral. Live re-ranking only (MMR and its extra term);
    all at 50 leaves every recommendation exactly as without tuning."""
    adventurous: int = 50     # MMR lambda: lower = more diverse lists
    hidden: int = 50          # novelty weight beta: higher = less popular films
    international: int = 50   # boost for films outside English and the Indian languages (or for them, below 50)
    length: int = 50          # soft runtime preference: above 50 longer films, below 50 shorter ones

    def shift(self, name: str) -> float:
        return (min(max(getattr(self, name), 0), 100) - 50) / 50

    @property
    def neutral(self) -> bool:
        return all(self.shift(n) == 0 for n in ("adventurous", "hidden", "international", "length"))
EXCLUDED_AWARDS = ("Golden Raspberry",)
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam",
                  "kn": "Kannada", "bn": "Bengali", "mr": "Marathi", "ko": "Korean", "ja": "Japanese",
                  "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "zh": "Mandarin",
                  "cn": "Cantonese", "pt": "Portuguese", "tr": "Turkish", "fa": "Persian"}


@dataclass
class Catalog:
    movie_ids: np.ndarray            # DB id per catalog row
    titles: list[str]
    genres: list[list[str]]
    keywords: list[list[str]]
    language: list[str]
    runtime: np.ndarray              # minutes, nan if unknown
    year: np.ndarray
    part: np.ndarray                 # 'A'..'D'
    popularity: np.ndarray           # popularity_score (Bayesian average, 1-10)
    votes: np.ndarray                # TMDB vote count (fame signal for every film)
    has_award: np.ndarray            # won or nominated (excluding anti-awards)
    content: sp.csr_matrix           # tuned content features, one L2-normalized row per film
    universe_rows: np.ndarray        # catalog row of each universe item
    recent: np.ndarray               # part C (released in the 18 months before the build date)
    kind: np.ndarray | None = None   # 'movie', 'series' or 'anime' per film (all 'movie' when not given)
    series_sim: sp.csr_matrix | None = None   # learned series-to-series similarity (n x n, mostly empty), see kind_rank

    def __post_init__(self):
        if self.kind is None:
            self.kind = np.full(len(self.movie_ids), "movie", dtype=object)
        # Series and anime have no ratings, so the movie rails never pick them; they get rails of their own.
        self.non_movie_rows = np.nonzero(np.asarray(self.kind) != "movie")[0].astype(np.int64)
        self.row_of = {int(m): r for r, m in enumerate(self.movie_ids)}
        self.n = len(self.movie_ids)
        self.universe_of_row = np.full(self.n, -1, dtype=np.int64)
        self.universe_of_row[self.universe_rows] = np.arange(len(self.universe_rows))
        v = np.log1p(np.maximum(self.votes, 0))
        self.novelty = (1 - (v - v.min()) / max(v.max() - v.min(), 1e-9)).astype(np.float32)
        self.fame_pct = (np.argsort(np.argsort(self.votes)) / max(self.n - 1, 1) * 100).astype(np.float32)


@dataclass
class UserState:
    ratings: dict[int, float] = field(default_factory=dict)     # catalog row -> 1..10
    likes: set[int] = field(default_factory=set)
    dislikes: set[int] = field(default_factory=set)
    picks: set[int] = field(default_factory=set)                # onboarding picks
    in_list: set[int] = field(default_factory=set)
    watched: set[int] = field(default_factory=set)
    events: list[tuple[str, int]] = field(default_factory=list)  # (event_type, row) for implicit strength
    behavioral_count: int = 0
    languages: list[str] = field(default_factory=list)
    liked_genres: list[str] = field(default_factory=list)
    disliked_genres: list[str] = field(default_factory=list)
    recent_views: list[int] = field(default_factory=list)       # newest first, last 14 days

    @property
    def stage(self) -> str:
        return stage_of(self.behavioral_count)

    def liked_rows(self) -> list[int]:
        return sorted(self.likes | self.picks | {r for r, v in self.ratings.items() if v >= 8})


class OnlineEngine:
    def __init__(self, catalog: Catalog, sources: SourceModels, weights: dict, calibrator,
                 item_neighbors: tuple[np.ndarray, np.ndarray], train: sp.csr_matrix):
        self.cat, self.src, self.weights, self.cal = catalog, sources, weights, calibrator
        self.nb_idx, self.nb_vals = item_neighbors
        self.train_csc = train.tocsc()
        self.event_weights = event_weights()
        self.availability: AvailabilityMap | None = None   # set by the API when availability_calibration.json exists

    # ------------------------------------------------------------------ profile -> source scores
    def implicit_strength(self, st: UserState) -> dict[int, float]:
        w: dict[int, float] = {}
        # Each kind of event counts once per title: opening the same page ten times is not ten times the interest.
        for kind, row in dict.fromkeys(st.events):
            if kind in self.event_weights and kind != "rate" and kind not in WEAK_EVENTS:
                w[row] = w.get(row, 0.0) + self.event_weights[kind]
        for row, r in st.ratings.items():
            w[row] = w.get(row, 0.0) + self.event_weights.get("rate", 1.0) + max(r - 6, 0)
        for row in st.picks | st.likes:
            w[row] = max(w.get(row, 0.0), 4.0)
        return {r: v for r, v in w.items() if v > 0 and r not in st.dislikes}

    def scores(self, st: UserState) -> dict[str, np.ndarray]:
        n, cat = self.cat.n, self.cat
        out = {s: np.full(n, -np.inf, dtype=np.float32) for s in SOURCES}
        out["popularity"] = cat.popularity.astype(np.float32).copy()
        # content: ratings, likes/picks as 10/10, dislikes as 1/10, over the whole catalog
        content_r = dict(st.ratings)
        content_r.update({r: 10.0 for r in st.likes | st.picks})
        content_r.update({r: 1.0 for r in st.dislikes})
        liked = [(r, v - 6) for r, v in content_r.items() if v >= 7]
        disliked = [(r, 6 - v) for r, v in content_r.items() if v <= 5]
        if liked or disliked:
            p = sp.csr_matrix((1, cat.content.shape[1]), dtype=np.float32)
            for group, sign in ((liked, 1.0), (disliked, -1.0)):
                if group:
                    rows, w = zip(*group)
                    w = np.asarray(w, dtype=np.float32) / np.sum(w)
                    p = p + sign * sp.csr_matrix(w[None, :]) @ cat.content[list(rows)]
            out["content"] = np.asarray((cat.content @ p.T).todense()).ravel().astype(np.float32)
        # universe models: explicit ratings and implicit strengths on MovieLens films only
        uni = lambda rows: [(cat.universe_of_row[r], r) for r in rows if cat.universe_of_row[r] >= 0]
        n_u = len(cat.universe_rows)
        r_items = uni(st.ratings)
        ratings = sp.csr_matrix(([st.ratings[r] for _, r in r_items], ([0] * len(r_items), [u for u, _ in r_items])),
                                shape=(1, n_u), dtype=np.float32)
        l_items = uni(st.likes | st.picks)
        likes = sp.csr_matrix((np.ones(len(l_items), dtype=np.float32), ([0] * len(l_items), [u for u, _ in l_items])),
                              shape=(1, n_u))
        strength = self.implicit_strength(st)
        s_items = uni(strength)
        strength_m = sp.csr_matrix(([strength[r] for _, r in s_items], ([0] * len(s_items), [u for u, _ in s_items])),
                                   shape=(1, n_u), dtype=np.float32)
        prof = Profiles(ratings, likes, strength=strength_m)
        for name, fn in (("item_cf", self.src.item_cf), ("user_cf", self.src.user_cf_scores),
                         ("svd", self.src.svd_scores), ("als", self.src.als_scores)):
            if name in ("item_cf", "user_cf", "svd") and ratings.nnz == 0:
                continue                                   # explicit models need explicit ratings
            if name == "als" and strength_m.nnz == 0:
                continue
            out[name][cat.universe_rows] = fn(prof)[0]
        return out

    def excluded(self, st: UserState) -> np.ndarray:
        rows = set(st.ratings) | st.watched | st.dislikes | st.picks | st.likes
        if st.disliked_genres:
            bad = set(st.disliked_genres)
            rows |= {r for r in range(self.cat.n) if bad & set(self.cat.genres[r])}
        return np.union1d(np.array(sorted(rows), dtype=np.int64), self.cat.non_movie_rows)

    def kind_rank(self, st: UserState, kind: str) -> tuple[np.ndarray, np.ndarray]:
        """Series or anime for this user, best first: (catalog rows, scores 0..1). They have no FlickRaven ratings, so
        the score is content similarity to what the user rated, liked or picked (0.65) plus TMDB popularity (0.35);
        popularity alone when the user has no taste signal yet. For series with learned similarities (real
        MyDramaList lists, see pipeline/drama_cf.py) the score is 0.45 learned + 0.30 content + 0.25 popularity,
        the learned part coming from the series the user rated 7+, liked or picked. Titles the user already acted
        on are left out."""
        cat = self.cat
        rows = np.nonzero(np.asarray(cat.kind) == kind)[0]
        gone = set(st.ratings) | st.watched | st.dislikes | st.picks | st.likes
        if st.disliked_genres:
            bad = set(st.disliked_genres)
            gone |= {int(r) for r in rows if bad & set(cat.genres[r])}
        rows = rows[~np.isin(rows, list(gone))] if gone else rows
        pct = lambda v: (np.argsort(np.argsort(v)) + 1) / max(len(v), 1)
        score = pct(cat.popularity[rows])
        # Anime is lifted by fame: the big names (Attack on Titan, Demon Slayer, Solo Leveling) are what most people want
        # to see first. Fame is the TMDB vote-count percentile; the quality score alone favoured obscure titles.
        fame = pct(cat.fame_pct[rows]) if kind == "anime" and len(rows) else None
        if fame is not None:
            score = 0.5 * score + 0.5 * fame
        content = self.scores(st)["content"][rows]
        if len(rows) and np.isfinite(content).any():
            c = np.where(np.isfinite(content), content, np.nanmin(content[np.isfinite(content)]))
            score = (0.5 if fame is not None else 0.65) * pct(c) + (0.5 if fame is not None else 0.35) * score
            learned = self.learned_series(st, rows)
            if learned is not None:
                covered = learned > 0
                blended = 0.45 * pct(np.where(covered, learned, 0.0)) + 0.30 * pct(c) + 0.25 * pct(cat.popularity[rows])
                score = np.where(covered, blended, score)
        order = np.argsort(-score, kind="stable")
        return rows[order], score[order].astype(float)

    def personal_fit(self, st: UserState, rows: list[int]) -> tuple[np.ndarray, np.ndarray, bool]:
        """How well each of `rows` suits this user: (keep mask, fit 0..1, has_taste_signal). Used to personalise
        candidate lists that come from outside the recommender (for example series that Gemini names as similar).
        Dropped: titles the user disliked or rated 4 or lower, titles in genres they dislike, and titles whose
        taste score is negative (closer to what they disliked than to what they liked) and in the weakest third of
        this list. Fit is the percentile of the content taste score within the list; 0.5 for everyone when the user
        has no taste signal yet. The thresholds are not tuned."""
        rows = np.asarray(rows, dtype=int)
        bad = set(st.disliked_genres)
        low = {r for r, v in st.ratings.items() if v <= 4}
        keep = np.array([int(r) not in st.dislikes and int(r) not in low and not (bad & set(self.cat.genres[r])) for r in rows], dtype=bool)
        content = self.scores(st)["content"][rows] if len(rows) else np.array([])
        finite = np.isfinite(content)
        if len(rows) == 0 or not finite.any():
            return keep, np.full(len(rows), 0.5), False
        c = np.where(finite, content, np.nanmin(content[finite]))
        fit = (np.argsort(np.argsort(c)) + 1) / len(c)
        keep &= ~((c < 0) & (fit < 0.34))
        return keep, fit, True

    def learned_series(self, st: UserState, rows: np.ndarray) -> np.ndarray | None:
        """Learned similarity of each of `rows` to the series the user rated 7+, liked or picked (weights 0.25..1),
        or None when there is no model or no such series. Zero for series the model has no data on."""
        sim = self.cat.series_sim
        if sim is None:
            return None
        weight = {r: (v - 6) / 4 for r, v in st.ratings.items() if v >= 7}
        weight.update({r: 1.0 for r in st.likes | st.picks})
        liked = [r for r in weight if sim[r].nnz]
        if not liked:
            return None
        v = sp.csr_matrix(([weight[r] for r in liked], ([0] * len(liked), liked)), shape=(1, self.cat.n))
        out = np.asarray((v @ sim[:, rows]).todense()).ravel()
        return out if out.max() > 0 else None

    # ------------------------------------------------------------------ top picks (pool, blend, Match %, MMR)
    def onboarding_constraint(self, st: UserState) -> np.ndarray:
        """Cold users: the genres chosen in onboarding feed the constraints (spec 6.1). Films outside
        those genres are left out of Top Picks, unless fewer than 200 films would remain (relaxed)."""
        if st.stage != "cold" or not st.liked_genres:
            return np.array([], dtype=np.int64)
        liked = set(st.liked_genres)
        outside = np.array([r for r in range(self.cat.n) if not liked & set(self.cat.genres[r])], dtype=np.int64)
        return outside if self.cat.n - len(outside) >= 200 else np.array([], dtype=np.int64)

    def top_picks(self, st: UserState, mode: str = "balanced", k: int = 20, extra_exclude=(), scores=None,
                  tuning: "Tuning | None" = None):
        scores = scores or self.scores(st)
        excl = np.union1d(self.excluded(st), np.asarray(list(extra_exclude), dtype=np.int64))
        excl = np.union1d(excl, self.onboarding_constraint(st))
        # Onboarding language lift is temporary. A saved preference also keeps matching titles in
        # candidate retrieval after a user becomes established; the final rerank signal is separate.
        candidate_scores = self.persistent_language_candidate_scores(st, self.language_lift(st, scores))
        pool, norm = candidate_pool({s: v[None, :] for s, v in candidate_scores.items()}, [excl])
        valid = pool[0] >= 0
        pool, norm = pool[0][valid], norm[:, 0, valid]
        w = self.weights[st.stage]
        final = np.tensordot(np.array([w.get(s, 0) for s in SOURCES], dtype=np.float32), norm, axes=1)
        if self.availability is not None:
            pool, norm, final = self._add_unavailable_candidates(st, scores, excl, pool, norm, final, w)
        cfg = MODES[mode]
        t = tail_slots(k, cfg.get("tail_share", 0.0))
        if t:
            pool, norm, final = self._add_unavailable_candidates(st, scores, excl, pool, norm, final, w,
                                                                 rows=self.tail_rows())
        language_bonus = self.persistent_language_bonus(st, pool)
        final = final + language_bonus
        order = np.argsort(-final)
        pool, norm, final, language_bonus = pool[order], norm[:, order], final[order], language_bonus[order]
        is_tail_all = self.cat.fame_pct[pool] < TAIL_PCT
        # The top 100 by blend score, plus (when a tail channel is on) the best 40 long-tail films, which may rank lower.
        keep = np.union1d(np.arange(min(TOP_N, len(pool))), np.nonzero(is_tail_all)[0][:40]) if t else np.arange(min(TOP_N, len(pool)))
        pool, norm, final, language_bonus = pool[keep], norm[:, keep], final[keep], language_bonus[keep]
        items, rel = pool, final
        is_tail = is_tail_all[keep]
        x = self.cat.content[items]
        sim = (x @ x.T).toarray().astype(np.float32)
        boost = self._explore_boost(st, items) if mode == "discover" else None
        lam, beta = cfg["lambda"], cfg["beta"]
        if tuning is not None and not tuning.neutral:
            lam = float(np.clip(lam - 0.2 * tuning.shift("adventurous"), 0.3, 0.98))
            beta = max(0.0, beta + 0.15 * tuning.shift("hidden"))
            boost = (boost if boost is not None else 0) + self._tuning_boost(items, tuning)
        everything = np.arange(len(items))
        if t:
            tail_local = mmr(everything, rel, sim, self.cat.novelty[items], t, lam, beta, boost, allowed=is_tail)
            head_local = mmr(everything, rel, sim, self.cat.novelty[items], k - len(tail_local), lam, beta, boost,
                             allowed=~is_tail, already=tail_local)
            local = spread(head_local, tail_local)
        else:
            local = mmr(everything, rel, sim, self.cat.novelty[items], k, lam, beta, boost)
        picked = items[local]
        shares = contributions(norm[:, local], w)
        preference_share = np.divide(language_bonus[local], final[local], out=np.zeros(len(local), dtype=np.float32),
                                     where=final[local] > 0)
        shares *= (1.0 - preference_share)[None, :]
        blend_rank = {int(i): j for j, i in enumerate(items)}
        # Match % comes from the catalog-wide hybrid score, as on the film page, Why, lists and genre pages,
        # so a film shows the same number everywhere (the pool score above only decides what is picked).
        catalog = self.rail_scores(st, scores)
        out = []
        for pos, (row, sc) in enumerate(zip(picked, rel[local])):
            share = {s: float(shares[si, pos]) for si, s in enumerate(SOURCES)}
            if preference_share[pos] > 0:
                share["language_preference"] = float(preference_share[pos])
            out.append({"row": int(row), "score": float(sc), "match_pct": int(self.match(st.stage, float(catalog[row]))),
                        "shares": share, "reranked": blend_rank[int(row)] > pos + 3})
        return out

    def tail_rows(self) -> np.ndarray:
        """Films outside the 20% most-voted films of the catalog (the long-tail channel's candidates)."""
        rows = getattr(self, "_tail_rows", None)
        if rows is None:
            cat = self.cat
            rows = np.nonzero((cat.fame_pct < TAIL_PCT) & (np.asarray(cat.kind) == "movie"))[0]
            self._tail_rows = rows
        return rows

    def _add_unavailable_candidates(self, st, scores, excl, pool, norm, final, w, per_source: int = 50, rows=None):
        """Films without collaborative factors can be proposed by no model but content and popularity, which the
        candidate pool then scored 0 for the rest. Add the best of them by their availability-aware score
        (rail_scores), on the pool's scale: the map from catalog-wide score to pool score is fitted (isotonic)
        on the MovieLens films already in the pool, so the two kinds are ranked against each other fairly."""
        from sklearn.isotonic import IsotonicRegression
        lifted = self.language_lift(st, scores)
        rail = self.rail_scores(st, lifted)
        rows = self.unavailable_rows() if rows is None else rows
        rows = rows[np.isfinite(rail[rows]) & ~np.isin(rows, excl) & ~np.isin(rows, pool)]
        if not len(rows):
            return pool, norm, final
        top = rows[np.argsort(-rail[rows], kind="stable")[:per_source]]
        known = np.isfinite(rail[pool]) & (self.cat.universe_of_row[pool] >= 0)
        if known.sum() >= 5 and np.ptp(rail[pool][known]) > 0:
            iso = IsotonicRegression(out_of_bounds="clip", increasing=True).fit(rail[pool][known], final[known])
            extra_final = iso.predict(rail[top]).astype(np.float32)
        else:
            extra_final = rail[top].astype(np.float32)
        extra_norm = np.zeros((len(SOURCES), len(top)), dtype=np.float32)
        for si, src in enumerate(SOURCES):
            v = lifted[src]
            ok = np.isfinite(v)
            if w.get(src, 0) and ok[top].all() and ok.any():
                extra_norm[si] = (np.argsort(np.argsort(v[ok]))[np.searchsorted(np.nonzero(ok)[0], top)] + 1) / ok.sum()
        return (np.concatenate([pool, top]), np.concatenate([norm, extra_norm], axis=1),
                np.concatenate([final, extra_final]))

    def language_lift(self, st: UserState, scores: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """New users: films in the languages picked at onboarding get a popularity lift, so someone who
        picked only Hindi does not open the site to a banner of Hollywood films. The lift fades as the user
        gives feedback (cold full, warming half, established none). When English is picked together with
        other languages, English gets half the lift: the catalog is mostly English already."""
        lift = LANGUAGE_LIFT.get(st.stage, 0.0)
        if not lift or not st.languages:
            return scores
        langs = set(st.languages)
        per_lang = {l: lift * (0.5 if l == "en" and len(langs) > 1 else 1.0) for l in langs}
        bonus = np.array([per_lang.get(l, 0.0) for l in self.cat.language], dtype=np.float32)
        out = dict(scores)
        out["popularity"] = scores["popularity"] + bonus
        return out

    def persistent_language_candidate_scores(self, st: UserState, scores: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Use saved languages to retrieve candidates for established users without changing source weights.

        The one-time onboarding lift remains governed by `language_lift`; this separate candidate-only lift
        addresses the established-stage popularity weight being zero. Final relevance is still ranked by the
        hybrid score plus the small, separately reported language-preference term.
        """
        if st.stage != "established" or not st.languages:
            return scores
        langs = set(st.languages)
        per_lang = {l: PERSISTENT_LANGUAGE_CANDIDATE_LIFT * (0.5 if l == "en" and len(langs) > 1 else 1.0)
                    for l in langs}
        bonus = np.array([per_lang.get(l, 0.0) for l in self.cat.language], dtype=np.float32)
        out = dict(scores)
        out["popularity"] = scores["popularity"] + bonus
        return out

    def persistent_language_bonus(self, st: UserState, rows: np.ndarray) -> np.ndarray:
        """Small final-ranking bonus for explicit saved languages; never infer a preference for users without one."""
        if st.stage != "established" or not st.languages:
            return np.zeros(len(rows), dtype=np.float32)
        return (PERSISTENT_LANGUAGE_RERANK_BOOST * np.isin(np.asarray(self.cat.language)[rows], st.languages)).astype(np.float32)

    def match(self, stage: str, score: float) -> int:
        return int(self.cal.match_pct(stage, np.array([score]))[0])

    def _tuning_boost(self, items: np.ndarray, tuning: Tuning) -> np.ndarray:
        """International: +/-0.08 for films outside / inside English and the Indian languages. Length: up to
        +/-0.05 by runtime (110 minutes is neutral, 40 minutes either way is the full effect)."""
        cat = self.cat
        intl = np.array([0 if cat.language[r] in LOCAL_LANGUAGES else 1 for r in items], dtype=np.float32)
        rt = np.nan_to_num(cat.runtime[items], nan=110.0)
        z = np.clip((rt - 110.0) / 40.0, -1, 1).astype(np.float32)
        return (0.08 * tuning.shift("international") * (2 * intl - 1) + 0.05 * tuning.shift("length") * z).astype(np.float32)

    def phase(self, st: UserState, recent_rows: list[int], k: int = 20, scores=None) -> dict | None:
        """Your Current Phase: films like the ones liked in the last weeks (recent_rows, newest first).
        Score = 0.6 x percentile of content similarity to those films + 0.4 x percentile of the usual hybrid
        score, so recent taste counts more than the whole history. None with fewer than 3 recent films."""
        recent = list(dict.fromkeys(recent_rows))
        if len(recent) < 3:
            return None
        cat = self.cat
        profile = sp.csr_matrix(cat.content[recent].mean(axis=0))
        sims = np.asarray((cat.content @ profile.T).todense()).ravel()
        rail = self.rail_scores(st, scores)
        ok = np.isfinite(rail)
        ok[self.excluded(st)] = False
        ok[recent] = False
        idx = np.nonzero(ok)[0]
        if len(idx) < k:
            return None
        pct = lambda v: (np.argsort(np.argsort(v)) + 1) / len(v)
        combined = 0.6 * pct(sims[idx]) + 0.4 * pct(rail[idx])
        counts: dict[str, int] = {}
        for r in recent:
            for g in cat.genres[r]:
                counts[g] = counts.get(g, 0) + 1
        genre = max(counts, key=lambda g: (counts[g], -min(i for i, r in enumerate(recent) if g in cat.genres[r]))) if counts else None
        return {"rows": idx[np.argsort(-combined)][:k].tolist(), "genre": genre, "based_on": len(recent)}

    def _explore_boost(self, st: UserState, items: np.ndarray) -> np.ndarray:
        """Discover mode: small boost for other languages and for genres rare in the user's history."""
        boost = np.zeros(len(items), dtype=np.float32)
        hist = {}
        for r in st.liked_rows():
            for g in self.cat.genres[r]:
                hist[g] = hist.get(g, 0) + 1
        common = {g for g, c in hist.items() if c >= 2}
        for j, r in enumerate(items):
            if st.languages and self.cat.language[r] not in st.languages:
                boost[j] += MODES["discover"]["explore_boost"]
            if self.cat.genres[r] and not set(self.cat.genres[r]) & common:
                boost[j] += MODES["discover"]["explore_boost"]
        return boost

    # ------------------------------------------------------------------ catalog-wide hybrid score (rails)
    def rail_scores(self, st: UserState, scores=None) -> np.ndarray:
        """Hybrid score for EVERY film: each source's percentile over the films it scores, blended
        with the stage weights. Used to rank rails that filter the catalog (genres, awards, ...)."""
        scores = scores or self.scores(st)
        w = self.weights[st.stage]
        total = np.zeros(self.cat.n, dtype=np.float32)
        for s in SOURCES:
            v = scores[s]
            ok = np.isfinite(v)
            if not ok.any() or w.get(s, 0) == 0:
                continue
            pct = np.zeros(self.cat.n, dtype=np.float32)
            pct[ok] = (np.argsort(np.argsort(v[ok])) + 1) / ok.sum()
            total += w[s] * pct
        if self.availability is not None:
            total = self._score_unavailable(st, scores, total)
        total[self.excluded(st)] = -np.inf
        return total

    def unavailable_rows(self) -> np.ndarray:
        """Films that MovieLens never rated (no item CF / user CF / SVD / ALS factors). Series and anime are
        handled by kind_rank, not here."""
        rows = getattr(self, "_unavailable_rows", None)
        if rows is None:
            cat = self.cat
            rows = np.nonzero((cat.universe_of_row < 0) & (np.asarray(cat.kind) == "movie"))[0]
            self._unavailable_rows = rows
        return rows

    def _score_unavailable(self, st: UserState, scores: dict, total: np.ndarray) -> np.ndarray:
        """Films without collaborative factors: average of the sources that can score them (not a sum with zeros),
        mapped onto the MovieLens films' scale (cinematch_engine/availability.py)."""
        w = self.weights[st.stage]
        pct = {}
        for s in SOURCES:
            v = scores[s]
            ok = np.isfinite(v)
            p = np.full(self.cat.n, np.nan, dtype=np.float32)
            if ok.any():
                p[ok] = (np.argsort(np.argsort(v[ok])) + 1) / ok.sum()
            pct[s] = p
        rows = self.unavailable_rows()
        total = total.copy()
        total[rows] = self.availability.map_unavailable(st.stage, renormalized(pct, w, rows))
        return total

    # ------------------------------------------------------------------ explanations
    def reasons(self, st: UserState, row: int, shares: dict, reranked: bool = False) -> list[dict]:
        cat = self.cat
        liked = np.array(st.liked_rows(), dtype=np.int64)
        liked = liked[liked != row]          # a film the user liked is not its own reason
        content_sim = None
        if len(liked):
            sims = np.asarray((cat.content[liked] @ cat.content[row].T).todense()).ravel()
            content_sim = {"rows": liked, "sims": sims}
        item_nb = None
        u = cat.universe_of_row[row]
        if u >= 0:
            item_nb = {int(cat.universe_rows[j]): float(v) for j, v in zip(self.nb_idx[u], self.nb_vals[u]) if v > 0}
        votes = self.neighbor_votes(u) if u >= 0 and shares.get("user_cf", 0) >= 0.2 else None
        top_genre = self.top_genre(st)
        prefs = None
        if st.stage == "cold" and cat.language[row] in st.languages and set(cat.genres[row]) & set(st.liked_genres):
            g = next(g for g in cat.genres[row] if g in st.liked_genres)
            prefs = f"{LANGUAGE_NAMES.get(cat.language[row], cat.language[row])} {g.lower()} films"
        # explain() works on indices into a similarity matrix: build a tiny one for this film
        index = {r: j for j, r in enumerate([row, *liked.tolist()])}
        small = np.zeros((len(index), len(index)), dtype=np.float32)
        if content_sim is not None:
            small[0, 1:] = content_sim["sims"]
        nb_local = {0: {index[r]: s for r, s in (item_nb or {}).items() if r in index}}
        out = explain(0, shares, np.arange(1, len(index)), small, nb_local if item_nb else None, votes, top_genre,
                      lambda j: cat.titles[[row, *liked.tolist()][j]], preferences=prefs, reranked=reranked,
                      added_genre=cat.genres[row][0] if cat.genres[row] else None)
        result = []
        for r in out:
            anchor = None
            if r.code == "because_you_liked":
                anchor = int(cat.movie_ids[[row, *liked.tolist()][r.evidence["film"]]])
            result.append({"code": r.code, "source": r.source, "text": r.text, "share": round(r.share, 2),
                           "anchor_movie_id": anchor})
        return result

    def neighbor_votes(self, u: int) -> int | None:
        nb = getattr(self.src, "last_neighbors", None)
        if nb is None:
            return None
        idx, vals = nb
        neigh = idx[0][vals[0] > 0]
        col = self.train_csc[:, u]
        raters = dict(zip(col.indices, col.data))
        return sum(1 for v in neigh if raters.get(int(v), 0) >= 8) or None

    def top_genre(self, st: UserState) -> str | None:
        counts = {}
        for r, v in st.ratings.items():
            if v >= 8:
                for g in self.cat.genres[r]:
                    counts[g] = counts.get(g, 0) + 1
        return max(counts, key=counts.get) if counts else None

    # ------------------------------------------------------------------ home page plan (spec 7)
    def home(self, st: UserState, mode: str = "balanced", rail_size: int = 20, min_rail: int = 8,
             tuning: Tuning | None = None, recent_rows: list[int] | None = None, scores: dict | None = None,
             seed: int | None = None) -> dict:
        """The Home plan. With a `seed` (the API passes one that changes every day per person) the page is refreshed:
        hero and rows are drawn from a wider top of the same ranking, and the order of the themed rows is shuffled.
        Without a seed the plan is fully deterministic (tests, evaluation)."""
        cat = self.cat
        scores = scores or self.scores(st)           # callers that already scored this user pass them in
        rail = self.rail_scores(st, scores)
        rng = np.random.default_rng(seed) if seed is not None else None
        used: set[int] = set()
        picks = self.top_picks(st, mode, k=5 + rail_size * (3 if rng is not None else 1), scores=scores, tuning=tuning)
        hero = refresh(picks[:12], 5, rng, pool_mult=2, keep=2) if rng is not None else picks[:5]
        picks = [p for p in picks if p not in hero]
        picks = hero + picks
        used |= {p["row"] for p in hero}
        rails = []

        def take(key, title, rows, source, reason=None, scored=None):
            rows = [int(r) for r in rows if int(r) not in used and np.isfinite(rail[int(r)])]
            rows = refresh(rows, rail_size, rng) if rng is not None else rows[:rail_size]
            if len(rows) < min_rail:
                return
            used.update(rows)
            rails.append({"key": key, "title": title, "source": source, "rows": rows, "reason": reason,
                          "scored": scored or {}})

        def ranked(mask):
            idx = np.nonzero(mask & np.isfinite(rail))[0]
            return idx[np.argsort(-rail[idx])]

        tp = [p for p in picks[5:] if p["row"] not in used]
        take("top_picks", "Top Picks For You", [p["row"] for p in tp], "hybrid", scored={p["row"]: p for p in tp})

        ph = self.phase(st, recent_rows or [], k=60, scores=scores)
        if ph:
            take("current_phase", "Your Current Phase", ph["rows"], "recent_content",
                 reason={"code": "current_phase", "source": "recent_content", "share": 0, "genre": ph["genre"],
                         "text": "Close to the films you liked in the last three weeks"})

        anchors = [r for r in self._recent_likes(st)][:2]
        for a in anchors:
            u = cat.universe_of_row[a]
            if u >= 0:
                neigh = [int(cat.universe_rows[j]) for j, v in zip(self.nb_idx[u], self.nb_vals[u]) if v > 0]
                src = "item_cf"
            else:
                sims = np.asarray((cat.content @ cat.content[a].T).todense()).ravel()
                sims[a] = -1
                neigh = np.argsort(-sims)[:60].tolist()
                src = "content"
            take(f"because_you_liked:{int(cat.movie_ids[a])}", f'Because You Liked "{cat.titles[a]}"', neigh, src,
                 reason={"code": "because_you_liked", "anchor_movie_id": int(cat.movie_ids[a])})

        acted = set(self.excluded(st).tolist()) | st.in_list   # rated, liked, disliked, watched, picked or saved
        cont = [r for r in st.recent_views if r not in acted]
        if cont:
            rows = [r for r in cont if r not in used][:rail_size]
            if rows:
                used.update(rows)
                rails.append({"key": "continue", "title": "Continue Exploring", "source": "recent_views",
                              "rows": rows, "reason": None, "scored": {}})

        n_ratings = len(st.ratings)
        if n_ratings >= 5:
            v = scores["svd"].copy()
            v[self.excluded(st)] = -np.inf
            idx = np.nonzero(np.isfinite(v))[0]
            take("based_on_ratings", "Based On Your Ratings", idx[np.argsort(-v[idx])], "svd")
        if n_ratings >= 10:
            nb = getattr(self.src, "last_neighbors", None)
            usable = int((nb[1][0] > 0).sum()) if nb is not None else 0
            if usable >= 20:
                v = scores["user_cf"].copy()
                v[self.excluded(st)] = -np.inf
                idx = np.nonzero(np.isfinite(v))[0]
                take("people_like_you", "People With Your Taste Loved", idx[np.argsort(-v[idx])], "user_cf")
        langs = st.languages or ["en"]
        in_lang = np.array([l in langs for l in cat.language])
        take("your_languages", "Movies In Your Languages", ranked(in_lang), "hybrid")
        gems = (cat.popularity >= 7.5) & (cat.fame_pct < 50)
        rt = np.nan_to_num(cat.runtime, nan=0)
        popcorn = np.array([bool(set(g) & POPCORN_GENRES) for g in cat.genres]) & (rt >= 90) & (rt <= 130) & (cat.popularity >= 6.5)
        # Feel-good and Romance get their own rows next to the others (the For Tonight mood rules, with a quality floor and no
        # horror, war or crime).
        dark = {"Horror", "War", "Crime", "Thriller"}
        light = np.array([bool(set(g) & FEEL_GOOD_GENRES) and not (set(g) & dark) for g in cat.genres]) & (cat.popularity >= 6.5)
        romance = np.array(["Romance" in g for g in cat.genres]) & (cat.popularity >= 6.5)
        loved = np.nonzero(in_lang)[0] if in_lang.any() else np.arange(cat.n)
        loved = loved[np.argsort(-cat.popularity[loved])]
        themed = [
            lambda: take("feel_good", "Feel-Good Films For You", ranked(light & (np.asarray(cat.kind) == "movie")), "hybrid"),
            lambda: take("romance", "Romance For You", ranked(romance & (np.asarray(cat.kind) == "movie")), "hybrid"),
            lambda: take("new_notable", "New & Notable", self._new_notable(st, scores), "content"),
            lambda: take("hidden_gems", "Hidden Gems", ranked(gems), "hybrid"),
            lambda: take("awards", "Award Winners & Nominees", ranked(cat.has_award), "hybrid"),
            lambda: take("popcorn", "Perfect Popcorn Films", ranked(popcorn), "tonight_preset"),
            lambda: take("international", "International Cinema", ranked(~in_lang), "hybrid"),
            lambda: take("most_loved", "Most Loved", [r for r in loved if np.isfinite(rail[r])], "popularity"),
        ]
        if rng is not None:
            rng.shuffle(themed)             # the themed rows come in a different order each day
        for add in themed:
            add()
        disc = self.top_picks(st, "discover", k=rail_size + len(used), scores=scores, extra_exclude=used, tuning=tuning)
        take("different", "Discover Something Different", [p["row"] for p in disc], "discover_mmr",
             scored={p["row"]: p for p in disc})
        return {"stage": st.stage, "hero": hero, "rails": rails, "rail_scores": rail}

    def _recent_likes(self, st: UserState) -> list[int]:
        order = [row for kind, row in reversed(st.events) if kind in ("like", "rate", "onboarding_pick")]
        cand = [r for r in order if r in st.likes or r in st.picks or st.ratings.get(r, 0) >= 8]
        cand += [r for r in st.liked_rows() if r not in cand]
        return list(dict.fromkeys(cand))

    def _new_notable(self, st: UserState, scores) -> list[int]:
        cat = self.cat
        idx = np.nonzero(cat.recent)[0]
        content = scores["content"][idx]
        content = np.where(np.isfinite(content), content, 0)
        c = (np.argsort(np.argsort(content)) + 1) / len(idx)
        p = (np.argsort(np.argsort(cat.votes[idx])) + 1) / len(idx)
        return idx[np.argsort(-(c * p))].tolist()

    # ------------------------------------------------------------------ For Tonight and Surprise Me
    def tonight(self, st: UserState, req: Request, k: int = 10):
        cat = self.cat
        rail = self.rail_scores(st)
        ok = np.nonzero(np.isfinite(rail))[0]
        films = [{"genres": cat.genres[r], "keywords": cat.keywords[r],
                  "runtime_min": None if np.isnan(cat.runtime[r]) else cat.runtime[r],
                  "original_language": cat.language[r]} for r in ok]
        chosen, relaxed, note = tonight_recommend(films, rail[ok], req, k)
        return [int(ok[i]) for i in chosen], relaxed, note

    def surprise(self, st: UserState, rng: np.random.Generator):
        picks = self.top_picks(st, "balanced", k=60)
        top3 = {g for g, _ in sorted(self._genre_counts(st).items(), key=lambda kv: -kv[1])[:3]}
        keep = [p for p in picks if p["match_pct"] >= 60 and self.cat.popularity[p["row"]] >= 6.5
                and self.cat.genres[p["row"]] and self.cat.genres[p["row"]][0] not in top3
                and self.cat.fame_pct[p["row"]] < 70]
        if not keep:
            return None
        w = np.array([p["match_pct"] for p in keep], dtype=float)
        pick = keep[int(rng.choice(len(keep), p=w / w.sum()))]
        return {**pick, "reasons": [{"code": "surprise_me", "source": "surprise_me", "text": SURPRISE_REASON,
                                     "share": 0.0, "anchor_movie_id": None}]}

    def _genre_counts(self, st: UserState) -> dict:
        counts = {}
        for r in st.liked_rows():
            for g in self.cat.genres[r]:
                counts[g] = counts.get(g, 0) + 1
        return counts

    # Fallback More Like This (titles added after similar_titles.npz was built): the tuned content cosine plus
    # genre overlap, same language and year closeness. The main path is the offline neighbour table
    # (cinematch_engine/similar.py, pipeline/similar_titles.py), measured to be closer to what people call similar.
    SIMILAR_GENRE_W, SIMILAR_LANGUAGE_W, SIMILAR_ERA_W, SIMILAR_ERA_SCALE = 0.3, 0.2, 0.1, 12.0

    def similar(self, row: int, k: int = 20) -> list[int]:
        """More Like This rows (same type as `row`), most similar first."""
        return [d["row"] for d in self.similar_items(row, k)]

    def similar_items(self, row: int, k: int = 20) -> list[dict]:
        """More Like This with evidence: [{row, score, signals, method}], same type only (film to film, series to
        series, anime to anime), never the title itself. Uses the offline neighbour table when it has this title,
        otherwise the fallback formula. Nothing personal: every user sees the same list for a title."""
        table = getattr(self, "similar_table", None)
        if table is not None and table["rows"][row, 0] >= 0:
            nb = table["rows"][row]
            keep = nb >= 0
            keep[keep] = np.asarray(self.cat.kind)[nb[keep]] == self.cat.kind[row]
            idx = np.nonzero(keep)[0][:k]
            return [{"row": int(nb[j]), "score": float(table["scores"][row, j]), "method": "neighbours",
                     "signals": {s: float(table["comps"][i, row, j]) / 255 for i, s in enumerate(table["stored"])}}
                    for j in idx]
        return self._similar_fallback(row, k)

    def _similar_fallback(self, row: int, k: int) -> list[dict]:
        cat = self.cat
        same = np.nonzero(np.asarray(cat.kind) == cat.kind[row])[0]
        same = same[same != row]
        if not len(same):
            return []
        cos = np.asarray((cat.content[same] @ cat.content[row].T).todense()).ravel()
        g = self._genre_matrix()
        shared = np.asarray((g[same] @ g[row].T).todense()).ravel()
        sizes = np.asarray(g[same].sum(axis=1)).ravel()
        union = sizes + g[row].sum() - shared
        jac = np.divide(shared, union, out=np.zeros_like(shared, dtype=np.float64), where=union > 0)
        same_lang = np.array([cat.language[r] == cat.language[row] and cat.language[r] != "" for r in same], dtype=np.float64)
        gap = np.abs(cat.year[same] - cat.year[row])
        era = np.where(np.isfinite(gap), np.exp(-np.nan_to_num(gap, nan=0.0) / self.SIMILAR_ERA_SCALE), 0.0)
        score = cos + self.SIMILAR_GENRE_W * jac + self.SIMILAR_LANGUAGE_W * same_lang + self.SIMILAR_ERA_W * era
        order = np.lexsort((same, -np.round(score, 6)))[:k]
        return [{"row": int(same[j]), "score": float(score[j]), "method": "fallback",
                 "signals": {"genre": float(jac[j])}} for j in order]

    def _genre_matrix(self) -> sp.csr_matrix:
        """Films x genres, 1 where the film has the genre (built once, for More Like This)."""
        if getattr(self, "_genres_mh", None) is None:
            names = sorted({x for gs in self.cat.genres for x in gs})
            col = {n: i for i, n in enumerate(names)}
            rows = [r for r, gs in enumerate(self.cat.genres) for _ in gs]
            cols = [col[x] for gs in self.cat.genres for x in gs]
            self._genres_mh = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(self.cat.n, len(names)))
        return self._genres_mh
