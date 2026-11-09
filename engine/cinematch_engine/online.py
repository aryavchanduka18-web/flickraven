"""The live engine: one user, the whole product catalog (spec sections 6 and 7).

Catalog space = every film in the product catalog (parts A-D). Content and popularity score every
film; item CF, user CF, SVD and ALS only know the MovieLens films (the evaluation universe) and give
no score elsewhere, so they never propose parts B, C or D. Everything else (candidate pool, percentile
normalization, stage blend, Match %, MMR, explanations) is the same code that was evaluated offline.
"""
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from sklearn.preprocessing import normalize

from cinematch_engine.blend import candidate_pool, contributions
from cinematch_engine.config import event_weights
from cinematch_engine.explain import explain
from cinematch_engine.profile import stage_of
from cinematch_engine.rerank import MODES, TOP_N, mmr
from cinematch_engine.sources import SOURCES, Profiles, SourceModels
from cinematch_engine.surprise import REASON as SURPRISE_REASON
from cinematch_engine.tonight import Request, recommend as tonight_recommend

POPCORN_GENRES = {"Action", "Adventure", "Comedy", "Animation", "Science Fiction"}
# "Indian and English" end of the International tuning slider.
LOCAL_LANGUAGES = {"en", "hi", "ta", "te", "ml", "kn", "bn", "mr"}
# Popularity points (1-10 scale) added to films in the user's onboarding languages, by stage (language_lift).
LANGUAGE_LIFT = {"cold": 1.2, "warming": 0.6, "established": 0.0}


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

    # ------------------------------------------------------------------ profile -> source scores
    def implicit_strength(self, st: UserState) -> dict[int, float]:
        w: dict[int, float] = {}
        for kind, row in st.events:
            if kind in self.event_weights and kind != "rate":
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
        content = self.scores(st)["content"][rows]
        if len(rows) and np.isfinite(content).any():
            c = np.where(np.isfinite(content), content, np.nanmin(content[np.isfinite(content)]))
            score = 0.65 * pct(c) + 0.35 * score
            learned = self.learned_series(st, rows)
            if learned is not None:
                covered = learned > 0
                blended = 0.45 * pct(np.where(covered, learned, 0.0)) + 0.30 * pct(c) + 0.25 * pct(cat.popularity[rows])
                score = np.where(covered, blended, score)
        order = np.argsort(-score, kind="stable")
        return rows[order], score[order].astype(float)

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
        # Picking uses language-lifted scores; Match % below still comes from the unlifted scores.
        pool, norm = candidate_pool({s: v[None, :] for s, v in self.language_lift(st, scores).items()}, [excl])
        valid = pool[0] >= 0
        pool, norm = pool[0][valid], norm[:, 0, valid]
        w = self.weights[st.stage]
        final = np.tensordot(np.array([w.get(s, 0) for s in SOURCES], dtype=np.float32), norm, axes=1)
        order = np.argsort(-final)
        pool, norm, final = pool[order], norm[:, order], final[order]
        top = slice(0, TOP_N)
        items, rel = pool[top], final[top]
        x = self.cat.content[items]
        sim = (x @ x.T).toarray().astype(np.float32)
        boost = self._explore_boost(st, items) if mode == "discover" else None
        cfg = MODES[mode]
        lam, beta = cfg["lambda"], cfg["beta"]
        if tuning is not None and not tuning.neutral:
            lam = float(np.clip(lam - 0.2 * tuning.shift("adventurous"), 0.3, 0.98))
            beta = max(0.0, beta + 0.15 * tuning.shift("hidden"))
            boost = (boost if boost is not None else 0) + self._tuning_boost(items, tuning)
        local = mmr(np.arange(len(items)), rel, sim, self.cat.novelty[items], k, lam, beta, boost)
        picked = items[local]
        shares = contributions(norm[:, :TOP_N][:, local], w)
        blend_rank = {int(i): j for j, i in enumerate(items)}
        # Match % comes from the catalog-wide hybrid score, as on the film page, Why, lists and genre pages,
        # so a film shows the same number everywhere (the pool score above only decides what is picked).
        catalog = self.rail_scores(st, scores)
        out = []
        for pos, (row, sc) in enumerate(zip(picked, rel[local])):
            share = {s: float(shares[si, pos]) for si, s in enumerate(SOURCES)}
            out.append({"row": int(row), "score": float(sc), "match_pct": int(self.match(st.stage, float(catalog[row]))),
                        "shares": share, "reranked": blend_rank[int(row)] > pos + 3})
        return out

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
        total[self.excluded(st)] = -np.inf
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
             tuning: Tuning | None = None, recent_rows: list[int] | None = None) -> dict:
        cat = self.cat
        scores = self.scores(st)
        rail = self.rail_scores(st, scores)
        used: set[int] = set()
        picks = self.top_picks(st, mode, k=5 + rail_size, scores=scores, tuning=tuning)
        hero = picks[:5]
        used |= {p["row"] for p in hero}
        rails = []

        def take(key, title, rows, source, reason=None, scored=None):
            rows = [int(r) for r in rows if int(r) not in used and np.isfinite(rail[int(r)])][:rail_size]
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
        take("new_notable", "New & Notable", self._new_notable(st, scores), "content")
        gems = (cat.popularity >= 7.5) & (cat.fame_pct < 50)
        take("hidden_gems", "Hidden Gems", ranked(gems), "hybrid")
        take("awards", "Award Winners & Nominees", ranked(cat.has_award), "hybrid")
        rt = np.nan_to_num(cat.runtime, nan=0)
        popcorn = np.array([bool(set(g) & POPCORN_GENRES) for g in cat.genres]) & (rt >= 90) & (rt <= 130) & (cat.popularity >= 6.5)
        take("popcorn", "Perfect Popcorn Films", ranked(popcorn), "tonight_preset")
        take("international", "International Cinema", ranked(~in_lang), "hybrid")
        loved = np.nonzero(in_lang)[0] if in_lang.any() else np.arange(cat.n)
        loved = loved[np.argsort(-cat.popularity[loved])]
        take("most_loved", "Most Loved", [r for r in loved if np.isfinite(rail[r])], "popularity")
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

    # More Like This weights (similarity only, nothing personal): the tuned content cosine, plus genre
    # overlap (Jaccard), same original language, and release years close together (12-year scale).
    SIMILAR_GENRE_W, SIMILAR_LANGUAGE_W, SIMILAR_ERA_W, SIMILAR_ERA_SCALE = 0.3, 0.2, 0.1, 12.0

    def similar(self, row: int, k: int = 20) -> list[int]:
        """More Like This: the films most similar to this one, by content alone (no user, no co-ratings).
        Score = content cosine + 0.3 genre Jaccard + 0.2 same language + 0.1 exp(-|year gap| / 12)."""
        cat = self.cat
        cos = np.asarray((cat.content @ cat.content[row].T).todense()).ravel()
        g = self._genre_matrix()
        shared = np.asarray((g @ g[row].T).todense()).ravel()
        sizes = np.asarray(g.sum(axis=1)).ravel()
        union = sizes + sizes[row] - shared
        jac = np.divide(shared, union, out=np.zeros_like(shared, dtype=np.float64), where=union > 0)
        same_lang = np.array([l == cat.language[row] and l != "" for l in cat.language], dtype=np.float64)
        gap = np.abs(cat.year - cat.year[row])
        era = np.where(np.isfinite(gap), np.exp(-np.nan_to_num(gap, nan=0.0) / self.SIMILAR_ERA_SCALE), 0.0)
        score = cos + self.SIMILAR_GENRE_W * jac + self.SIMILAR_LANGUAGE_W * same_lang + self.SIMILAR_ERA_W * era
        score[row] = -np.inf
        top = np.argpartition(-score, k)[:k]
        return [int(r) for r in top[np.argsort(-score[top])]]

    def _genre_matrix(self) -> sp.csr_matrix:
        """Films x genres, 1 where the film has the genre (built once, for More Like This)."""
        if getattr(self, "_genres_mh", None) is None:
            names = sorted({x for gs in self.cat.genres for x in gs})
            col = {n: i for i, n in enumerate(names)}
            rows = [r for r, gs in enumerate(self.cat.genres) for _ in gs]
            cols = [col[x] for gs in self.cat.genres for x in gs]
            self._genres_mh = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(self.cat.n, len(names)))
        return self._genres_mh