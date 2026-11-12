"""Per-person content preference model (design v2, section 2 and 3). Pure functions: no database, no web request.

Nothing here is connected to the ranker. Step C of the plan builds and tests the maths; shadow logging and any ranking
change come later, and a ranking change only after the offline replay passes.

What it learns: a weight per feature (genre, language, era, length), from the films a person has clearly liked or
disliked. Taste DNA traits and genre x trait crosses were removed on 2026-11-12: on 500 fresh users they added no
measurable gain over genre alone (full minus genre-only: +0.0001 NDCG at warming, -0.0006 at established, intervals
include zero) and raised genre repetition.

Rules that matter (all from design v2):
- One label per person and film. The latest explicit opinion (rating, like, dislike) wins. A My List add counts as
  weak "interest" only when there is no explicit opinion. Watched, Not interested and page views are never taste.
- Evidence is counted in DISTINCT films, never in events. A feature has no effect below MIN_FILMS films.
- Context rejections (wrong mood, language, length, already seen) are not examples. Only "wrong genre" (genre
  features only) and "not my taste" (weak) reach the weights.
- Only feedback after `reset_at` counts, and nothing counts while learning is off.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

MIN_FILMS = 3            # distinct films behind a feature before it can have any effect
SHRINK_K = 3.0           # effect multiplier n / (n + SHRINK_K)
FULL_AT = 20             # distinct labelled films at which the adjustment reaches its full size
MIN_SCALE = 0.2          # floor on a feature's catalogue spread, so one rare tag cannot dominate
MIN_KNOWN = 30           # a feature needs this many titles with known values to be in the model
BASE_LAMBDA = 2.0        # regularisation; larger = slower to move. Tuned in the offline replay, not by hand.
RARE_LAMBDA = 2.0        # extra for features present on under 2% of titles
CAP_SHARE = 0.25         # adjustment cap as a share of the pool's score spread (90th minus 10th percentile)

# explicit signals -> (label, reliability)
RATING_HIGH, RATING_MID, RATING_LOW = 8, 7, 4
ALPHA_STRONG, ALPHA_MID, ALPHA_INTEREST = 1.0, 0.4, 0.5
ALPHA_WRONG_GENRE, ALPHA_NOT_MY_TASTE = 0.5, 0.3


# ---------------------------------------------------------------- features
@dataclass
class Title:
    """What the model needs to know about one title."""
    id: int
    genres: list[str] = field(default_factory=list)
    language: str | None = None
    year: int | None = None
    runtime: int | None = None


def runtime_bucket(minutes: int | None) -> str | None:
    if not minutes:
        return None
    return "short" if minutes < 90 else "medium" if minutes <= 135 else "long"


def raw_features(t: Title) -> dict[str, float]:
    """Raw value of every feature we KNOW for this title. A feature missing from the result is unknown."""
    f: dict[str, float] = {f"g:{g}": 1.0 for g in t.genres}
    if t.language:
        f[f"lang:{t.language}"] = 1.0
    if t.year:
        f[f"era:{t.year // 10 * 10}"] = 1.0
    rb = runtime_bucket(t.runtime)
    if rb:
        f[f"rt:{rb}"] = 1.0
    return f


@dataclass
class Space:
    """The catalogue-wide frame: which features exist and their average and spread (for centring)."""
    names: list[str]
    mean: np.ndarray
    scale: np.ndarray
    prevalence: np.ndarray
    index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.index = {n: i for i, n in enumerate(self.names)}

    @property
    def d(self) -> int:
        return len(self.names)


def _known_families(titles: list[Title]) -> tuple[dict[str, list[float]], dict[str, int]]:
    """For each feature: values over the titles where it is KNOWN (a binary feature that is absent counts as 0,
    but only for titles whose genre/language/year/length are known at all)."""
    values: dict[str, list[float]] = {}
    for t in titles:
        raw = raw_features(t)
        for k, v in raw.items():
            values.setdefault(k, []).append(v)
    # absent binary features are known zeros for every title
    n_all = len(titles)
    known_n: dict[str, int] = {}
    for k in values:
        if k.startswith("g:"):
            known_n[k] = n_all
        elif k.startswith("lang:"):
            known_n[k] = sum(1 for t in titles if t.language)
        elif k.startswith("era:"):
            known_n[k] = sum(1 for t in titles if t.year)
        else:
            known_n[k] = sum(1 for t in titles if runtime_bucket(t.runtime))
    return values, known_n


def fit_space(titles: list[Title]) -> Space:
    """Catalogue statistics. mean and spread are taken over the titles where a feature is known."""
    values, known_n = _known_families(titles)
    names, means, scales, prev = [], [], [], []
    for k in sorted(values):
        n = known_n[k]
        if n < MIN_KNOWN:
            continue
        arr = np.zeros(n)
        vs = np.asarray(values[k], dtype=float)
        arr[: len(vs)] = vs                      # the rest of the known titles have the feature absent (0)
        names.append(k)
        means.append(float(arr.mean()))
        scales.append(max(float(arr.std()), MIN_SCALE))
        prev.append(float((arr > 0).mean()))
    return Space(names, np.asarray(means), np.asarray(scales), np.asarray(prev))


def centre(raw: dict[str, float], space: Space) -> np.ndarray:
    """Centred, scaled vector. Unknown features are 0 (no information). A genre, language, era or length feature that
    is simply absent from a title whose other values in that family are known is a real zero, centred like any value."""
    x = np.zeros(space.d)
    families = {k.split(":", 1)[0] for k in raw}
    for i, name in enumerate(space.names):
        if name in raw:
            x[i] = (raw[name] - space.mean[i]) / space.scale[i]
        elif name.split(":", 1)[0] in ("g", "lang", "era", "rt") and name.split(":", 1)[0] in families:
            x[i] = (0.0 - space.mean[i]) / space.scale[i]
    return x


def encode(t: Title, space: Space) -> tuple[np.ndarray, dict[str, float]]:
    raw = raw_features(t)
    return centre(raw, space), raw


def _present(name: str, value: float) -> bool:
    return value > 0


# ---------------------------------------------------------------- labels
@dataclass
class State:
    """A person's current standing on one title (from the ratings, reactions and list tables)."""
    movie_id: int
    rating: float | None = None
    rating_at: datetime | None = None
    reaction: str | None = None            # "like" | "dislike" | None
    reaction_at: datetime | None = None
    in_list: bool = False
    list_at: datetime | None = None
    watched: bool = False                  # exclusion and history only, never taste


@dataclass
class Label:
    movie_id: int
    y: int                 # +1 or -1
    alpha: float           # reliability 0..1
    kind: str              # "rating" | "like" | "dislike" | "interest" | "wrong_genre" | "not_my_taste"
    genre_only: bool = False


def _after(at: datetime | None, reset_at: datetime | None) -> bool:
    return reset_at is None or (at is not None and at > reset_at)


def explicit_label(s: State, reset_at: datetime | None = None) -> tuple[Label | None, bool]:
    """(label, has_explicit_opinion). The latest of rating / like / dislike wins; a 5 or 6 is an opinion that says
    nothing either way, so it wins over an older like without adding a label."""
    cands: list[tuple[datetime, str, float | str]] = []
    if s.rating is not None and _after(s.rating_at, reset_at):
        cands.append((s.rating_at or datetime.min, "rating", s.rating))
    if s.reaction and _after(s.reaction_at, reset_at):
        cands.append((s.reaction_at or datetime.min, s.reaction, s.reaction))
    if not cands:
        return None, False
    _, kind, val = max(cands, key=lambda c: c[0])
    if kind == "like":
        return Label(s.movie_id, 1, ALPHA_STRONG, "like"), True
    if kind == "dislike":
        return Label(s.movie_id, -1, ALPHA_STRONG, "dislike"), True
    r = float(val)
    if r >= RATING_HIGH:
        return Label(s.movie_id, 1, ALPHA_STRONG, "rating"), True
    if r >= RATING_MID:
        return Label(s.movie_id, 1, ALPHA_MID, "rating"), True
    if r <= RATING_LOW:
        return Label(s.movie_id, -1, ALPHA_STRONG, "rating"), True
    return None, True


def effective_labels(states: list[State], reset_at: datetime | None = None, learning: bool = True) -> dict[int, Label]:
    """One label per film. Nothing at all while learning is off."""
    if not learning:
        return {}
    out: dict[int, Label] = {}
    for s in states:
        label, explicit = explicit_label(s, reset_at)
        if label is None and not explicit and s.in_list and _after(s.list_at, reset_at):
            label = Label(s.movie_id, 1, ALPHA_INTEREST, "interest")
        if label:
            out[s.movie_id] = label
    return out


def pick_labels(rejections: list[dict], have: dict[int, Label], reset_at: datetime | None = None,
                learning: bool = True) -> dict[int, Label]:
    """Perfect Pick rejections that may reach the weights, for films with no label already. A rejection is a dict with
    movie_id, kind, reasons, created_at. Mood, language, length and already-seen reasons, a rejection with no reason and
    a re-roll are request context only and produce nothing here."""
    out: dict[int, Label] = {}
    if not learning:
        return out
    for r in rejections:
        mid = r["movie_id"]
        if mid in have or mid in out or r.get("kind") != "perfect_pick_reject":
            continue
        if not _after(r.get("created_at"), reset_at):
            continue
        reasons = set(r.get("reasons") or [])
        if "genre" in reasons:
            out[mid] = Label(mid, -1, ALPHA_WRONG_GENRE, "wrong_genre", genre_only=True)
        elif "taste" in reasons:
            out[mid] = Label(mid, -1, ALPHA_NOT_MY_TASTE, "not_my_taste")
    return out


# ---------------------------------------------------------------- the fit
@dataclass
class Profile:
    """One person's learned weights. n[k] = distinct labelled films showing feature k."""
    space: Space
    theta: np.ndarray
    n: np.ndarray
    films: int                                       # distinct labelled films
    zeroed: set[str] = field(default_factory=set)   # "that's not me" overrides


def _lambdas(space: Space) -> np.ndarray:
    lam = np.full(space.d, BASE_LAMBDA)
    for i, name in enumerate(space.names):
        if space.prevalence[i] < 0.02:
            lam[i] += RARE_LAMBDA
    return lam


def fit(labels: dict[int, Label], titles: dict[int, Title], space: Space, zeroed: set[str] | None = None) -> Profile:
    """Regularised weighted logistic fit with a few Newton steps. Deterministic. Labels for titles we have no data on
    are skipped. A genre-only label sees only the genre features."""
    rows, ys, alphas = [], [], []
    present = np.zeros(space.d)
    genre_cols = np.array([n.startswith("g:") for n in space.names])
    used = 0
    for mid, lab in labels.items():
        t = titles.get(mid)
        if t is None:
            continue
        x, raw = encode(t, space)
        if lab.genre_only:
            x = np.where(genre_cols, x, 0.0)
        rows.append(x)
        ys.append(lab.y)
        alphas.append(lab.alpha)
        used += 1
        for i, name in enumerate(space.names):
            if name in raw and _present(name, raw[name]) and not (lab.genre_only and not genre_cols[i]):
                present[i] += 1
    theta = np.zeros(space.d)
    if rows:
        X, y, a = np.vstack(rows), np.asarray(ys, float), np.asarray(alphas, float)
        lam = _lambdas(space)
        for _ in range(30):
            z = np.clip(y * (X @ theta), -30, 30)
            p = 1.0 / (1.0 + np.exp(z))                      # = sigmoid(-z)
            grad = -(X * (a * y * p)[:, None]).sum(axis=0) + 2 * lam * theta
            w = a * p * (1 - p)
            hess = (X * w[:, None]).T @ X + np.diag(2 * lam)
            step = np.linalg.solve(hess, grad)
            theta = theta - step
            if float(np.abs(step).max()) < 1e-6:
                break
    prof = Profile(space, theta, present, used, set(zeroed or ()))
    return prof


def effect(profile: Profile) -> np.ndarray:
    """Per-feature multiplier: 0 below MIN_FILMS films, then n / (n + SHRINK_K); 0 for "that's not me" overrides."""
    n = profile.n
    m = np.where(n >= MIN_FILMS, n / (n + SHRINK_K), 0.0)
    for name in profile.zeroed:
        i = profile.space.index.get(name)
        if i is not None:
            m[i] = 0.0
    return m


def score(profile: Profile, t: Title) -> float:
    """s_pref for one title: sum of effect * weight * centred value. Unknown features contribute nothing."""
    x, _ = encode(t, profile.space)
    return float((effect(profile) * profile.theta * x).sum())


def cap_for(pool_scores: list[float]) -> float:
    """Adjustment cap = CAP_SHARE of the spread of the pool's hybrid scores (90th minus 10th percentile)."""
    if len(pool_scores) < 5:
        return 0.0
    lo, hi = np.percentile(pool_scores, [10, 90])
    return CAP_SHARE * float(hi - lo)


def adjustment(s_pref: float, films: int, cap: float, scale: float = 1.0) -> float:
    """What would be added to the hybrid score: cap * tanh(s / scale) * min(1, films / FULL_AT). Always within +-cap."""
    return cap * math.tanh(s_pref / scale) * min(1.0, films / FULL_AT)


def strength_word(n: int) -> str:
    """Words for the page, never a score: how much evidence stands behind a feature."""
    return "not enough" if n < MIN_FILMS else "some" if n < 8 else "strong"


def top_features(profile: Profile, limit: int = 8) -> list[dict]:
    """Features with real evidence, strongest first, for the "What FlickRaven learned" page."""
    eff = effect(profile) * profile.theta
    order = np.argsort(-np.abs(eff))
    out = []
    for i in order:
        if eff[i] == 0.0:
            continue
        out.append({"feature": profile.space.names[i], "direction": "more" if eff[i] > 0 else "less",
                    "films": int(profile.n[i]), "evidence": strength_word(int(profile.n[i]))})
        if len(out) >= limit:
            break
    return out
