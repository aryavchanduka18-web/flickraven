"""Content-based model (spec section 5, model 2).

Features: TF-IDF over overview + keywords + tagline, plus one-hot blocks for genres, language,
country, director, top-5 cast and studio. Each block is L2-normalized per film and multiplied by
its weight, then the whole row is L2-normalized, so the cosine similarity of two films is a
weighted mix of the block similarities.

User profile: weighted mean of liked films (rating >= 7, weight rating - 6) minus the weighted mean
of disliked films (rating <= 5, weight 6 - rating). A film's score is its similarity to the profile.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MultiLabelBinarizer, normalize

BLOCKS = ("text", "genres", "language", "country", "director", "cast", "studio")
DEFAULT_WEIGHTS = {b: 1.0 for b in BLOCKS}
TOP_CAST = 5
LIKE_MIN, DISLIKE_MAX, NEUTRAL = 7, 5, 6


@dataclass
class ContentFeatures:
    matrix: sp.csr_matrix
    tmdb_ids: np.ndarray
    vectorizer: TfidfVectorizer
    block_columns: dict[str, tuple[int, int]]
    block_vocab: dict[str, list[str]] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    fit_sizes: dict[str, int] = field(default_factory=dict)
    stage_sizes: dict[str, list[int]] = field(default_factory=dict)

    def fit_columns(self) -> np.ndarray:
        """Columns learned from the fit films (see build_blocks), in matrix order."""
        return np.concatenate([np.arange(lo, lo + self.fit_sizes.get(b, hi - lo))
                               for b, (lo, hi) in self.block_columns.items()])

    def columns_up_to(self, stage: int) -> np.ndarray:
        """Columns that exist once the films of stages 0..stage are in (see build_blocks `stage`)."""
        def size(b, lo, hi):
            sizes = self.stage_sizes.get(b)
            return (hi - lo) if not sizes else sizes[min(stage, len(sizes) - 1)]
        return np.concatenate([np.arange(lo, lo + size(b, lo, hi)) for b, (lo, hi) in self.block_columns.items()])


@dataclass
class ContentBlocks:
    """Raw (unweighted) feature blocks, built once and recombined cheaply while tuning."""
    blocks: dict[str, sp.csr_matrix]
    tmdb_ids: np.ndarray
    vectorizer: TfidfVectorizer
    vocab: dict[str, list[str]]
    fit_sizes: dict[str, int] = field(default_factory=dict)   # leading columns of each block learned from the fit films
    stage_sizes: dict[str, list[int]] = field(default_factory=dict)  # block width once stages 0..k are in


def film_text(movies: pd.DataFrame) -> pd.Series:
    kw = movies["keywords"].map(lambda ks: " ".join(ks) if ks is not None else "")
    return (movies["overview"].fillna("") + " " + kw + " " + movies["tagline"].fillna("")).str.strip()


def _labels(movies: pd.DataFrame, credits: pd.DataFrame) -> dict[str, list[list[str]]]:
    ids = movies["tmdb_id"].tolist()
    directors = credits[credits["role"] == "director"].groupby("tmdb_id")["name"].apply(list)
    cast = (credits[credits["role"] == "cast"].sort_values("credit_order")
            .groupby("tmdb_id")["name"].apply(lambda s: list(s)[:TOP_CAST]))
    return {
        "genres": [list(g) for g in movies["genres"]],
        "language": [[l] if l else [] for l in movies["original_language"]],
        "country": [list(c) for c in movies["countries"]],
        "director": [directors.get(i, []) for i in ids],
        "cast": [cast.get(i, []) for i in ids],
        "studio": [list(s) for s in movies["studios"]],
    }


def build_blocks(movies: pd.DataFrame, credits: pd.DataFrame, ngram_max: int = 2,
                 fit_mask: np.ndarray | None = None, stage: np.ndarray | None = None) -> ContentBlocks:
    """Feature blocks for every film. With `fit_mask`, the TF-IDF vocabulary and weights are learned from
    the masked films only (the other films' unseen words are ignored), and labels (genres, people, ...)
    that only the other films have get extra columns at the end of their block. Existing films have
    zeros there, so adding films leaves their feature values, and every similarity between them, unchanged.

    `stage` (optional, one int per film: 0 first build, 1, 2, ... later additions) orders the extra labels
    by the stage that first brought them in, so the columns of an earlier stage keep their positions when
    a later stage is added. Without it every extra label is stage 0 and they are simply sorted."""
    fit = movies if fit_mask is None else movies[np.asarray(fit_mask, dtype=bool)]
    # min_df=2 drops one-off words; skipped for tiny corpora (tests), where it would remove everything.
    min_df = 2 if len(fit) >= 50 else 1
    vectorizer = TfidfVectorizer(stop_words="english", sublinear_tf=True, max_df=0.5, min_df=min_df,
                                 ngram_range=(1, ngram_max), dtype=np.float32)
    vectorizer.fit(film_text(fit))
    blocks = {"text": sp.csr_matrix(vectorizer.transform(film_text(movies)))}
    vocab = {"text": vectorizer.get_feature_names_out().tolist()}
    fit_sizes = {"text": len(vocab["text"])}
    stage = np.zeros(len(movies), dtype=int) if stage is None else np.asarray(stage, dtype=int)
    n_stages = int(stage.max()) + 1 if len(stage) else 1
    fit_labels = _labels(fit, credits)
    stage_sizes = {}
    for name, labels in _labels(movies, credits).items():
        known = sorted({x for ls in fit_labels[name] for x in ls})
        known_set, first = set(known), {}
        for st, ls in zip(stage, labels):
            for x in ls:
                if x not in known_set:
                    first[x] = min(first.get(x, st), st)
        extra = sorted(first, key=lambda x: (first[x], x))
        mlb = MultiLabelBinarizer(classes=known + extra, sparse_output=True)
        blocks[name] = sp.csr_matrix(mlb.fit_transform(labels), dtype=np.float32)
        vocab[name] = [str(c) for c in mlb.classes_]
        fit_sizes[name] = len(known)
        stage_sizes[name] = [len(known) + sum(1 for x in extra if first[x] <= k) for k in range(n_stages)]
    return ContentBlocks(blocks, movies["tmdb_id"].to_numpy(), vectorizer, vocab, fit_sizes, stage_sizes)


def combine(cb: ContentBlocks, weights: dict[str, float] | None = None) -> ContentFeatures:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    parts, columns, start = [], {}, 0
    for name in BLOCKS:
        block = cb.blocks[name]
        if block.shape[1]:  # an empty block (no labels at all) has nothing to normalize
            block = normalize(block, norm="l2") * weights[name]
        parts.append(block)
        columns[name] = (start, start + block.shape[1])
        start += block.shape[1]
    matrix = normalize(sp.hstack(parts, format="csr"), norm="l2").astype(np.float32)
    return ContentFeatures(matrix, cb.tmdb_ids, cb.vectorizer, columns, cb.vocab, weights, cb.fit_sizes, cb.stage_sizes)


def build_content_features(movies: pd.DataFrame, credits: pd.DataFrame,
                           weights: dict[str, float] | None = None, ngram_max: int = 2,
                           fit_mask: np.ndarray | None = None) -> ContentFeatures:
    return combine(build_blocks(movies, credits, ngram_max, fit_mask), weights)


def profile_weights(ratings: sp.csr_matrix) -> sp.csr_matrix:
    """Per-user film weights: liked films sum to +1, disliked films sum to -1, neutral ones are 0."""
    r = ratings.tocsr().astype(np.float32)
    liked = r.copy()
    liked.data = np.where(liked.data >= LIKE_MIN, liked.data - NEUTRAL, 0).astype(np.float32)
    disliked = r.copy()
    disliked.data = np.where((disliked.data > 0) & (disliked.data <= DISLIKE_MAX), NEUTRAL - disliked.data, 0).astype(np.float32)
    liked.eliminate_zeros()
    disliked.eliminate_zeros()
    liked = normalize(liked, norm="l1")
    disliked = normalize(disliked, norm="l1")
    return (liked - disliked).tocsr()


class ContentModel:
    """Scores = profile weights x (film-film content similarity)."""

    def __init__(self, item_matrix: sp.csr_matrix):
        self.item_matrix = item_matrix                     # rows = universe films, L2-normalized
        self.sim = (item_matrix @ item_matrix.T).toarray().astype(np.float32)

    def fit(self, train: sp.csr_matrix) -> "ContentModel":
        self.weights = profile_weights(train)
        return self

    def score(self, users: np.ndarray) -> np.ndarray:
        return np.asarray(self.weights[users] @ self.sim, dtype=np.float32)