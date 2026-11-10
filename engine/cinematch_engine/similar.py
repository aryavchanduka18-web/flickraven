"""Title-to-title similarity for More Like This (built offline, served as a neighbour list).

Why a separate model: the content matrix used for user profiles weights cast and director double and
gives genre, language and country a block each, so the plot text is about 1/13 of a film's vector. That
was tuned for "what will this user rate highly", not for "what is like this one title": every US English
rom-com got the same similarity and the release year decided the order (docs/decisions-log.md, 2026-11-10).

Here each signal is computed on its own and mixed with weights tuned on held-out MovieLens users
(pipeline/similar_titles.py):

    keywords  cosine of TMDB keyword sets, rare keywords count more (IDF); the specific themes and tropes
    plot      TF-IDF cosine of overview + tagline
    topic     cosine of a 128-dimension LSA (truncated SVD) of overview + tagline + keywords: words that
              tend to appear together, so "assistant" and "boss" stories meet without sharing a word
    genre     genre Jaccard (fit, not identity)
    people    cosine of director + top-5 cast, rare names count more
    language  same original language (0/1)
    era       exp(-|year gap| / 15)
    quality   fame percentile of the candidate (TMDB votes), so barely-known films do not fill the list

Only titles of the same type are compared (film to film, series to series, anime to anime).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MultiLabelBinarizer, normalize

SIGNALS = ("keywords", "plot", "topic", "genre", "people", "language", "era", "quality")
# Stored per neighbour (0-255) so reasons and the debug view can show what made the match.
STORED = ("keywords", "plot", "topic", "genre", "people")
# Not story: TMDB tags about credits scenes, who directed, the source medium.
NOISE_KEYWORDS = {"duringcreditsstinger", "aftercreditsstinger", "woman director", "based on novel or book",
                  "based on comic", "based on manga", "based on true story", "remake", "sequel", "anime",
                  "live action remake", "based on young adult novel", "short film"}
TOP_CAST = 5
ERA_SCALE = 15.0
TOPIC_DIM = 128

# Chosen by pipeline/similar_titles.py (2026-11-10): the best of 400 random weight settings on the "tune" half
# of the hand-written test set, among those that did not do worse than the old formula on held-out MovieLens
# validation users. The "test" half and the MovieLens test users were only used for the final report.
DEFAULT_WEIGHTS = {"keywords": 0.5, "plot": 0.25, "topic": 0.25, "genre": 0.1, "people": 0.25,
                   "language": 0.5, "era": 0.2, "quality": 0.4}
K_STORED = 40


@dataclass
class SimilarFeatures:
    tmdb_ids: np.ndarray
    kind: np.ndarray
    keywords: sp.csr_matrix      # L2-normalized IDF keyword rows
    plot: sp.csr_matrix          # L2-normalized TF-IDF rows
    topic: np.ndarray            # L2-normalized LSA rows (float32)
    genres: sp.csr_matrix        # 0/1
    genre_count: np.ndarray
    people: sp.csr_matrix        # L2-normalized IDF rows
    language: np.ndarray         # code per title
    year: np.ndarray             # float, nan unknown
    fame: np.ndarray             # 0..1 percentile of TMDB votes within the title's type
    keyword_lists: list[list[str]]

    @property
    def n(self) -> int:
        return len(self.tmdb_ids)


def _idf_rows(labels: list[list[str]]) -> sp.csr_matrix:
    mlb = MultiLabelBinarizer(sparse_output=True)
    x = sp.csr_matrix(mlb.fit_transform(labels), dtype=np.float32)
    if x.shape[1] == 0:
        return x
    df = np.asarray((x > 0).sum(axis=0)).ravel()
    idf = np.log((1 + x.shape[0]) / (1 + df)) + 1
    idf[df < 2] = 0.0                 # a keyword only one title has cannot match anything
    return normalize(x @ sp.diags(idf.astype(np.float32)), norm="l2").tocsr()


def story_keywords(ks) -> list[str]:
    return [k for k in (list(ks) if ks is not None else []) if k not in NOISE_KEYWORDS]


def build_features(movies: pd.DataFrame, credits: pd.DataFrame, seed: int = 0) -> SimilarFeatures:
    """movies: tmdb_id, title_type, overview, tagline, keywords, genres, original_language, year, tmdb_vote_count."""
    movies = movies.reset_index(drop=True)
    kw = [story_keywords(k) for k in movies["keywords"]]
    text = (movies["overview"].fillna("") + " " + movies["tagline"].fillna("")).str.strip()
    big = len(movies) >= 50            # tiny corpora (tests): no document-frequency cut-offs
    plot_vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, max_df=0.3 if big else 1.0,
                               min_df=2 if big else 1, ngram_range=(1, 2), dtype=np.float32)
    plot = normalize(plot_vec.fit_transform(text), norm="l2").tocsr()
    topic_text = text + " " + pd.Series([" ".join(k) for k in kw])
    topic_vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, max_df=0.3 if big else 1.0,
                                min_df=3 if big else 1, dtype=np.float32)
    t = topic_vec.fit_transform(topic_text)
    svd = TruncatedSVD(n_components=min(TOPIC_DIM, max(t.shape[1] - 1, 1)), random_state=seed)
    topic = normalize(svd.fit_transform(t)).astype(np.float32)
    ids = movies["tmdb_id"].tolist()
    directors = credits[credits["role"] == "director"].groupby("tmdb_id")["name"].apply(list)
    cast = (credits[credits["role"] == "cast"].sort_values("credit_order")
            .groupby("tmdb_id")["name"].apply(lambda s: list(s)[:TOP_CAST]))
    people = _idf_rows([directors.get(i, []) + cast.get(i, []) for i in ids])
    g_mlb = MultiLabelBinarizer(sparse_output=True)
    genres = sp.csr_matrix(g_mlb.fit_transform([list(g) for g in movies["genres"]]), dtype=np.float32)
    kind = movies["title_type"].fillna("movie").to_numpy(dtype=object)
    votes = movies["tmdb_vote_count"].fillna(0).to_numpy(dtype=float)
    fame = np.zeros(len(movies), dtype=np.float32)
    for k in np.unique(kind):
        idx = np.nonzero(kind == k)[0]
        fame[idx] = (np.argsort(np.argsort(votes[idx])) + 1) / len(idx)
    return SimilarFeatures(
        tmdb_ids=movies["tmdb_id"].to_numpy(), kind=kind, keywords=_idf_rows(kw), plot=plot, topic=topic,
        genres=genres, genre_count=np.asarray(genres.sum(axis=1)).ravel(), people=people,
        language=movies["original_language"].fillna("").to_numpy(dtype=object),
        year=movies["year"].astype(float).to_numpy(), fame=fame, keyword_lists=kw)


def signals(f: SimilarFeatures, row: int, cand: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Every signal between title `row` and the candidate rows (all titles when cand is None)."""
    cand = np.arange(f.n) if cand is None else np.asarray(cand)
    dense = lambda m: np.asarray((m[cand] @ m[row].T).todense()).ravel()
    shared = dense(f.genres)
    union = f.genre_count[cand] + f.genre_count[row] - shared
    gap = np.abs(f.year[cand] - f.year[row])
    return {
        "keywords": dense(f.keywords), "plot": dense(f.plot), "topic": np.clip(f.topic[cand] @ f.topic[row], 0, 1),
        "genre": np.divide(shared, union, out=np.zeros_like(shared), where=union > 0),
        "people": dense(f.people),
        "language": ((f.language[cand] == f.language[row]) & (f.language[cand] != "")).astype(np.float32),
        "era": np.where(np.isfinite(gap), np.exp(-np.nan_to_num(gap) / ERA_SCALE), 0.0),
        "quality": f.fame[cand],
    }


def combine(sig: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    return sum(weights.get(s, 0.0) * sig[s] for s in SIGNALS)


def neighbours(f: SimilarFeatures, row: int, weights: dict[str, float], k: int,
               cand: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Top-k titles of the same type as `row` (never itself): rows, scores, per-signal values."""
    cand = np.nonzero(f.kind == f.kind[row])[0] if cand is None else np.asarray(cand)
    cand = cand[cand != row]
    sig = signals(f, row, cand)
    score = combine(sig, weights)
    k = min(k, len(cand))
    top = np.argpartition(-score, k - 1)[:k] if k < len(cand) else np.arange(len(cand))
    # deterministic: score, then more votes (fame), then lower row
    order = np.lexsort((cand[top], -f.fame[cand[top]], -np.round(score[top], 6)))
    top = top[order]
    return cand[top], score[top].astype(np.float32), {s: v[top] for s, v in sig.items()}


def shared_keywords(f_kw: list[list[str]], idf_rank: dict[str, float], a: int, b: int, n: int = 3) -> list[str]:
    """Up to n keywords both titles have, rarest first (the specific ones say most)."""
    both = set(f_kw[a]) & set(f_kw[b])
    return sorted(both, key=lambda k: (idf_rank.get(k, 0), k))[:n]


def build_table(f: SimilarFeatures, weights: dict[str, float] | None = None, k: int = K_STORED,
                block: int = 256) -> dict[str, np.ndarray]:
    """The top-k same-type neighbours of every title, for serving: rows (int32, -1 = none), scores (float16)
    and the STORED signals scaled to 0..255 (uint8). Deterministic (ties: more votes first, then lower row)."""
    weights = weights or DEFAULT_WEIGHTS
    rows = np.full((f.n, k), -1, dtype=np.int32)
    scores = np.zeros((f.n, k), dtype=np.float16)
    comps = np.zeros((len(STORED), f.n, k), dtype=np.uint8)
    for kind in np.unique(f.kind):
        cand = np.nonzero(f.kind == kind)[0]
        for lo in range(0, len(cand), block):
            anchors = cand[lo:lo + block]
            sig = _block_signals(f, anchors, cand)
            total = sum(weights.get(s, 0.0) * sig[s] for s in SIGNALS)
            total[np.arange(len(anchors)), lo + np.arange(len(anchors))] = -np.inf   # never itself
            kk = min(k, len(cand) - 1)
            if kk <= 0:
                continue
            part = np.argpartition(-total, kk - 1, axis=1)[:, :kk]
            for i, a in enumerate(anchors):
                p = part[i]
                order = np.lexsort((cand[p], -f.fame[cand[p]], -np.round(total[i, p], 6)))
                p = p[order]
                rows[a, :kk] = cand[p]
                scores[a, :kk] = total[i, p]
                for j, s in enumerate(STORED):
                    comps[j, a, :kk] = np.clip(np.round(sig[s][i, p] * 255), 0, 255)
    return {"tmdb_ids": f.tmdb_ids.astype(np.int64), "rows": rows, "scores": scores, "comps": comps,
            "stored": np.array(STORED), "weights": np.array([weights.get(s, 0.0) for s in SIGNALS], dtype=np.float32),
            "signals": np.array(SIGNALS)}


def _block_signals(f: SimilarFeatures, anchors: np.ndarray, cand: np.ndarray) -> dict[str, np.ndarray]:
    """signals() for many anchors at once: (len(anchors) x len(cand)) arrays."""
    d = lambda m: (m[anchors] @ m[cand].T).toarray()
    shared = d(f.genres)
    union = f.genre_count[anchors][:, None] + f.genre_count[cand][None, :] - shared
    gap = np.abs(f.year[anchors][:, None] - f.year[cand][None, :])
    lang_a, lang_c = f.language[anchors][:, None], f.language[cand][None, :]
    return {
        "keywords": d(f.keywords), "plot": d(f.plot), "topic": np.clip(f.topic[anchors] @ f.topic[cand].T, 0, 1),
        "genre": np.divide(shared, union, out=np.zeros_like(shared), where=union > 0),
        "people": d(f.people),
        "language": ((lang_a == lang_c) & (lang_c != "")).astype(np.float32),
        "era": np.where(np.isfinite(gap), np.exp(-np.nan_to_num(gap) / ERA_SCALE), 0.0),
        "quality": np.broadcast_to(f.fame[cand][None, :], shared.shape),
    }
