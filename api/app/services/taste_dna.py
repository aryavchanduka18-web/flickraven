"""Taste DNA: storytelling traits of titles, and how a user leans on each one.

Where the trait values come from (provenance, shown on the page):
- "keywords": TMDB keywords and genres, matched by the hand-written rules in RULES below. TMDB has no pacing,
  complexity or atmosphere fields; these are our own rule-based reading of its keywords, never TMDB's data.
- "viewers": what FlickRaven users tagged after rating a title. A trait counts for a title only once
  VIEWER_MIN different users tagged it (one person's tag is their opinion, not a fact about the title).
A title with fewer than MIN_KEYWORDS keywords and no viewer tags has no trait values ("unknown"), never zero.

Title trait value: v = 1 - exp(-evidence), in [0, 1). Evidence is the sum of matched rule weights.

User profile (all from stored activity; nothing is invented):
- liked titles: rated 7+ (weight (rating-6)/4), liked (1), onboarding picks (0.5), watched (0.3)
- disliked titles: rated 4 or less (weight (5-rating)/4), disliked (1)
- explicit tags on titles the user rated: each counts as TAG_WEIGHT titles with the trait fully present.
For each trait: liking = (sum of w * v + K * mean) / (sum of w + K), the catalog mean as a prior worth K titles, so
one title never dominates. The same for dislikes, kept separate. The "lean" is liking - catalog mean.

Title fit for a user (the separate, measurable "Taste DNA score"):
    fit = sum over known traits of  pref_a * (v_a - mean_a) / n_known,   pref_a = c_a * (lean_a - aversion_a)
where c_a = n_a / (n_a + 3) grows with the number of titles behind the trait. Refine My Taste settings override pref.
It is NOT part of the hybrid score; it orders the Taste DNA row only, until an offline test shows it helps.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

MIN_KEYWORDS = 3
VIEWER_MIN = 3
VIEWER_WEIGHT = 1.5
PRIOR_K = 4.0
TAG_WEIGHT = 2.0
MIN_EVIDENCE = 3          # titles (or tags) behind a trait before it is called a preference
MIN_LEAN = 0.05           # how far above the catalog average a trait must be to be called a preference


@dataclass(frozen=True)
class Trait:
    key: str
    label: str            # "Plot complexity"
    phrase: str           # used in sentences: "complex, layered plots"


TRAITS = [
    Trait("complexity", "Plot complexity", "complex, layered plots"),
    Trait("fast", "Fast pacing", "fast-moving stories"),
    Trait("slow_burn", "Slow burn", "slow-burn storytelling"),
    Trait("psychological", "Psychological tension", "psychological tension"),
    Trait("emotional", "Emotional depth", "emotional depth"),
    Trait("dark", "Dark atmosphere", "dark, atmospheric tone"),
    Trait("character", "Character focus", "character-driven stories"),
    Trait("mystery", "Mystery and suspense", "mystery and suspense"),
    Trait("twists", "Unexpected twists", "unexpected twists"),
    Trait("humour", "Humour", "humour"),
    Trait("romance", "Romance", "romance"),
    Trait("world", "World-building", "rich world-building"),
    Trait("realism", "Realism", "realistic, true-to-life stories"),
    Trait("dialogue", "Strong dialogue", "sharp dialogue"),
    Trait("violence", "Violence", "graphic violence"),
]
TRAIT = {t.key: t for t in TRAITS}
RADAR = ["complexity", "fast", "psychological", "emotional", "dark", "character", "mystery", "humour"]

# keyword or "genre:<name>" -> (trait, weight). Lower case, as TMDB stores keywords.
RULES: dict[str, list[tuple[str, float]]] = {}


def _rule(trait: str, weights: dict[str, float]) -> None:
    for name, w in weights.items():
        RULES.setdefault(name, []).append((trait, w))


_rule("complexity", {"complex": 1.5, "cerebral": 1.5, "mind-bending": 1.5, "nonlinear timeline": 1.5,
                     "nonlinear narrative": 1.5, "unreliable narrator": 1.5, "time loop": 1.0, "philosophical": 1.0,
                     "philosophy": 0.8, "surrealism": 0.8, "surreal": 0.8, "puzzle": 1.0, "multiple storylines": 1.0,
                     "alternate timeline": 0.8, "parallel world": 0.6, "time travel": 0.6, "conspiracy": 0.5,
                     "complicated": 0.8, "thought-provoking": 1.2, "intellectual": 0.8, "dream": 0.5, "dreams": 0.5})
_rule("fast", {"genre:Action": 0.8, "chase": 0.6, "car chase": 0.8, "shootout": 0.6, "explosion": 0.5, "heist": 0.6,
               "action hero": 0.8, "martial arts": 0.6, "race against time": 1.0, "fast-paced": 1.5, "adrenaline": 1.0,
               "adrenaline rush": 1.0, "gunfight": 0.6, "exhilarated": 0.6, "on the run": 0.5, "escape": 0.4,
               "one man army": 0.8, "kung fu": 0.6, "car race": 0.6})
_rule("slow_burn", {"slow burn": 1.5, "slow cinema": 1.5, "slow-burn suspense": 1.5, "slow‑burn suspense": 1.5,
                    "slow burn romance": 1.0, "character study": 0.8, "melancholy": 0.6, "contemplative": 1.0,
                    "meditative": 1.0, "thoughtful": 0.5, "minimalism": 0.8, "quiet": 0.5})
_rule("psychological", {"psychological thriller": 1.5, "psychological": 1.2, "psychological horror": 1.2,
                        "psychological drama": 1.2, "paranoia": 1.0, "obsession": 0.8, "mental illness": 0.8,
                        "psychopath": 0.8, "hallucination": 0.8, "intense": 0.8, "tense": 0.8, "anxious": 0.6,
                        "trauma": 0.6, "gaslighting": 1.0, "manipulation": 0.8, "mind game": 1.0, "cat and mouse": 0.8})
_rule("emotional", {"tearjerker": 1.5, "emotional": 1.0, "grief": 1.0, "loss of loved one": 1.0, "tragedy": 1.0,
                    "tragic": 1.0, "dying and death": 0.8, "terminal illness": 1.0, "heartbreak": 0.8, "melancholy": 0.8,
                    "sentimental": 0.6, "coming of age": 0.5, "depressing": 0.6, "compassionate": 0.5,
                    "empathetic": 0.5, "moving": 0.6, "heartwarming": 0.8, "genre:Drama": 0.4})
_rule("dark", {"dark": 1.0, "neo-noir": 1.2, "film noir": 1.2, "grim": 1.0, "grimdark": 1.2, "bleak": 1.0,
               "ominous": 1.0, "dark atmosphere": 1.5, "atmospheric": 1.0, "dark fantasy": 1.0, "gritty": 1.0,
               "dread": 1.0, "depressing": 0.5, "nightmare": 0.5, "genre:Horror": 0.6, "noir": 1.2})
_rule("character", {"character study": 1.5, "character-driven": 1.5, "slice of life": 0.8, "biography": 0.6,
                    "coming of age": 0.6, "loneliness": 0.6, "midlife crisis": 0.8, "identity": 0.5,
                    "family relationships": 0.4, "dysfunctional family": 0.5, "self-discovery": 0.8})
_rule("mystery", {"mystery": 1.0, "murder mystery": 1.2, "whodunit": 1.5, "suspenseful": 1.2, "suspense": 1.0,
                  "investigation": 0.8, "detective": 0.8, "murder investigation": 0.8, "missing person": 0.6,
                  "disappearance": 0.6, "genre:Mystery": 1.0, "genre:Thriller": 0.6, "private detective": 0.8})
_rule("twists", {"plot twist": 1.5, "twist ending": 1.5, "twist": 1.2, "surprise ending": 1.5,
                 "unexpected twists": 1.5, "plot twists": 1.5, "twist reveal": 1.5, "unreliable narrator": 1.0,
                 "shocking": 0.6, "double cross": 1.0, "whodunit": 0.5, "betrayal": 0.4})
_rule("humour", {"genre:Comedy": 1.0, "hilarious": 1.2, "witty": 1.0, "absurd": 0.8, "satire": 0.8, "parody": 0.8,
                 "spoof": 0.8, "slapstick comedy": 1.0, "dark comedy": 1.0, "romcom": 0.8, "sitcom": 1.0,
                 "playful": 0.6, "whimsical": 0.6, "lighthearted": 0.6, "campy": 0.5, "buddy comedy": 1.0,
                 "black humor": 1.0, "crude humor": 0.8, "amused": 0.5})
_rule("romance", {"genre:Romance": 1.0, "romance": 1.0, "love": 0.6, "romantic": 0.8, "love triangle": 0.8,
                  "falling in love": 0.8, "first love": 0.8, "romcom": 1.0, "forbidden love": 0.8,
                  "unrequited love": 0.8, "love affair": 0.6, "slow burn romance": 1.0, "love at first sight": 0.8})
_rule("world", {"fantasy world": 1.5, "high fantasy": 1.5, "dark fantasy": 0.8, "parallel world": 1.0,
                "alternate universe": 1.0, "alternate dimension": 1.0, "isekai": 1.0, "dystopia": 0.8,
                "post-apocalyptic future": 0.8, "cyberpunk": 1.0, "space opera": 1.2, "magic": 0.5,
                "mythology": 0.6, "genre:Fantasy": 0.8, "genre:Science Fiction": 0.6, "alternate history": 0.8})
_rule("realism", {"based on true story": 1.2, "biography": 1.0, "docudrama": 1.2, "social realism": 1.5,
                  "neo realism": 1.5, "neorealism": 1.5, "italian neo realism": 1.5, "kitchen sink realism": 1.5,
                  "realism": 1.5, "historical": 0.6, "genre:History": 0.8, "genre:Documentary": 1.2,
                  "based on real person": 1.0})
_rule("violence", {"violence": 1.0, "gore": 1.2, "brutality": 1.0, "torture": 1.0, "slasher": 1.0, "sadism": 1.0,
                   "massacre": 1.0, "splatter": 1.2, "blood": 0.8, "gunfight": 0.4, "shootout": 0.4,
                   "extreme violence": 1.5, "graphic violence": 1.5, "genre:War": 0.5})
# "dialogue" has no keyword rules: TMDB keywords say nothing reliable about it, so only viewer tags give it values.

# Tags a user can attach after rating. Positive tags say the trait was present and enjoyed.
LIKED_TAGS: dict[str, tuple[str, str]] = {          # tag -> (label, trait)
    "mind_bending": ("Mind-bending plot", "complexity"),
    "slow_burn": ("Slow burn", "slow_burn"),
    "twists": ("Unexpected twists", "twists"),
    "dark_atmosphere": ("Dark atmosphere", "dark"),
    "complex_characters": ("Complex characters", "character"),
    "emotional_depth": ("Emotional depth", "emotional"),
    "fast_paced": ("Fast-paced", "fast"),
    "strong_dialogue": ("Strong dialogue", "dialogue"),
    "psychological_tension": ("Psychological tension", "psychological"),
    "world_building": ("Great world-building", "world"),
    "humour": ("Humour", "humour"),
    "realistic": ("Realistic storytelling", "realism"),
}
# Tags for what did not work: (label, trait, sign). sign -1: the trait was there and unwanted (it goes to the
# user's dislikes, and counts as presence for the title). sign +1: the trait was missing and wanted (the user
# wants more of it; says nothing about the title). None: recorded, no trait.
DISLIKED_TAGS: dict[str, tuple[str, str | None, int]] = {
    "too_predictable": ("Too predictable", "twists", 1),
    "too_slow": ("Too slow", "slow_burn", -1),
    "weak_characters": ("Weak characters", "character", 1),
    "excessive_violence": ("Excessive violence", "violence", -1),
    "too_much_comedy": ("Too much comedy", "humour", -1),
    "poor_storytelling": ("Poor storytelling", None, 0),
}
OVERRIDES = ("more", "less")


def trait_evidence(names: list[str], genres: list[str]) -> dict[str, float]:
    """Summed rule weights per trait for one title's keywords and genres."""
    ev: dict[str, float] = {}
    for n in [*(k.lower() for k in names), *(f"genre:{g}" for g in genres)]:
        for trait, w in RULES.get(n, ()):
            ev[trait] = ev.get(trait, 0.0) + w
    return ev


def vector(names: list[str], genres: list[str], viewer: dict[str, int] | None = None) -> dict[str, float] | None:
    """Trait values 0..1 for one title, or None when there is too little to go on (unknown, not zero).
    viewer: trait -> number of different users who tagged the title with it."""
    viewer = {t: n for t, n in (viewer or {}).items() if n >= VIEWER_MIN}
    if len(names) < MIN_KEYWORDS and not viewer:
        return None
    ev = trait_evidence(names, genres) if len(names) >= MIN_KEYWORDS else {}
    for t in viewer:
        ev[t] = ev.get(t, 0.0) + VIEWER_WEIGHT
    known = [t.key for t in TRAITS if t.key != "dialogue" or "dialogue" in viewer]
    return {k: round(1 - math.exp(-ev.get(k, 0.0)), 4) for k in known}


@dataclass
class Signals:
    """One user's stored activity, as plain data."""
    weights: dict[int, float] = field(default_factory=dict)          # title id -> + liked / - disliked
    tags: list[tuple[int, str]] = field(default_factory=list)       # (title id, tag)
    overrides: dict[str, str] = field(default_factory=dict)         # trait -> "more" / "less"


@dataclass
class Profile:
    liking: dict[str, float]
    aversion: dict[str, float]
    n_like: dict[str, float]
    n_dislike: dict[str, float]
    mean: dict[str, float]
    overrides: dict[str, str]
    titles: int                     # liked titles with known traits

    def lean(self, k: str) -> float:
        return self.liking[k] - self.mean[k]

    def avoid(self, k: str) -> float:
        return self.aversion[k] - self.mean[k]

    def pref(self, k: str) -> float:
        o = self.overrides.get(k)
        if o == "more":
            return 1.0
        if o == "less":
            return -1.0
        c_l = self.n_like[k] / (self.n_like[k] + 3)
        c_d = self.n_dislike[k] / (self.n_dislike[k] + 3)
        return c_l * self.lean(k) - c_d * max(self.avoid(k), 0.0)

    def preferred(self) -> list[str]:
        """Traits the user clearly leans towards, strongest first (or set to "more")."""
        keys = [k for k in self.mean if self.overrides.get(k) == "more"
                or (self.overrides.get(k) != "less" and self.n_like[k] >= MIN_EVIDENCE and self.lean(k) >= MIN_LEAN)]
        return sorted(keys, key=lambda k: (self.overrides.get(k) != "more", -self.lean(k)))

    def avoided(self) -> list[str]:
        keys = [k for k in self.mean if self.overrides.get(k) == "less"
                or (self.overrides.get(k) != "more" and self.n_dislike[k] >= 2 and self.avoid(k) >= MIN_LEAN)]
        return sorted(keys, key=lambda k: (self.overrides.get(k) != "less", -self.avoid(k)))


def build_profile(sig: Signals, vectors: dict[int, dict[str, float] | None], mean: dict[str, float]) -> Profile:
    keys = list(mean)
    ps, pw, ns, nw = ({k: 0.0 for k in keys} for _ in range(4))
    n_like, n_dis = {k: 0.0 for k in keys}, {k: 0.0 for k in keys}
    titles = 0
    for tid, w in sig.weights.items():
        v = vectors.get(tid)
        if not v or not w:
            continue
        titles += w > 0
        for k, x in v.items():
            if k not in mean:
                continue
            if w > 0:
                ps[k] += w * x; pw[k] += w; n_like[k] += x >= 0.5
            else:
                ns[k] += -w * x; nw[k] += -w; n_dis[k] += x >= 0.5
    for _, tag in sig.tags:
        if tag in LIKED_TAGS:
            k = LIKED_TAGS[tag][1]
            ps[k] += TAG_WEIGHT; pw[k] += TAG_WEIGHT; n_like[k] += 1
        elif tag in DISLIKED_TAGS and DISLIKED_TAGS[tag][1]:
            _, k, sign = DISLIKED_TAGS[tag]
            if sign > 0:
                ps[k] += TAG_WEIGHT; pw[k] += TAG_WEIGHT; n_like[k] += 1
            else:
                ns[k] += TAG_WEIGHT; nw[k] += TAG_WEIGHT; n_dis[k] += 1
    liking = {k: (ps[k] + PRIOR_K * mean[k]) / (pw[k] + PRIOR_K) for k in keys}
    aversion = {k: (ns[k] + PRIOR_K * mean[k]) / (nw[k] + PRIOR_K) for k in keys}
    over = {k: v for k, v in sig.overrides.items() if k in mean and v in OVERRIDES}
    return Profile(liking, aversion, n_like, n_dis, mean, over, titles)


def fit(profile: Profile, v: dict[str, float] | None) -> tuple[float | None, list[str]]:
    """(Taste DNA score, traits that support it) for one title; (None, []) when the title's traits are unknown."""
    if not v:
        return None, []
    keys = [k for k in v if k in profile.mean]
    if not keys:
        return None, []
    s = sum(profile.pref(k) * (v[k] - profile.mean[k]) for k in keys) / len(keys)
    preferred = set(profile.preferred())
    because = sorted((k for k in keys if k in preferred and v[k] >= 0.5), key=lambda k: -v[k] * profile.pref(k))
    return s, because[:3]


def title_explanation(profile: Profile, v: dict[str, float] | None) -> tuple[list[str], list[str], list[str]]:
    """Return supporting, avoided, and mixed traits for one title without contradictory labels."""
    if not v:
        return [], [], []
    _, because = fit(profile, v)
    preferred_on_title = {k for k in profile.preferred() if v.get(k, 0.0) >= 0.5}
    clash = [k for k in profile.avoided() if v.get(k, 0.0) >= 0.5]
    mixed_set = preferred_on_title.intersection(clash)
    mixed = [k for k in profile.preferred() if k in mixed_set]
    return ([k for k in because if k not in mixed_set],
            [k for k in clash if k not in mixed_set], mixed)


def reason(because: list[str], source: str = "keywords") -> str | None:
    """A sentence backed by stored evidence, or None."""
    if not because:
        return None
    phrases = [TRAIT[k].phrase for k in because]
    joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]
    return f"Recommended because you consistently enjoy {joined}."


def personality(profile: Profile, top_genres: list[str], top_languages: list[str]) -> str | None:
    """'Your Cinematic Personality': only sentences the stored data supports. None below 5 liked titles."""
    if profile.titles < 5:
        return None
    out = []
    pref = profile.preferred()
    if pref:
        phrases = [TRAIT[k].phrase for k in pref[:3]]
        joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]
        out.append(f"You are drawn to {joined}, more than most of the catalog offers.")
    fast, slow = profile.lean("fast"), profile.lean("slow_burn")
    if "fast" in pref and "slow_burn" not in pref:
        out.append("You like a story that keeps moving.")
    elif "slow_burn" in pref and "fast" not in pref:
        out.append("You are happy to let a story take its time.")
    elif max(fast, slow) < MIN_LEAN:
        out.append("Pace does not decide much for you: you enjoy both quick and patient storytelling.")
    if top_genres:
        g = top_genres[:2]
        out.append(f"Your favourites are mostly {g[0]}" + (f" and {g[1]}" if len(g) > 1 else "") + " titles"
                   + (f", often in {top_languages[0]}" if top_languages else "") + ".")
    avoided = profile.avoided()
    if avoided:
        out.append(f"You tend to turn away from {TRAIT[avoided[0]].phrase}.")
    return " ".join(out) or None


# ------------------------------------------------------------------ database access (kept thin and in one place)
_SQL_EVIDENCE = """
    SELECT mk.movie_id, array_agg(k.name) AS kw
    FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id
    WHERE mk.movie_id = ANY(:ids) GROUP BY mk.movie_id"""


def title_vectors(db, ids: list[int]) -> dict[int, dict[str, float] | None]:
    """Trait vectors for the given titles (keywords, genres and viewer tags)."""
    from sqlalchemy import text
    ids = list({int(i) for i in ids})
    if not ids:
        return {}
    kw = {r[0]: list(r[1]) for r in db.execute(text(_SQL_EVIDENCE), {"ids": ids})}
    genres = {r[0]: list(r[1]) for r in db.execute(text("""SELECT mg.movie_id, array_agg(g.name) FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = ANY(:ids) GROUP BY mg.movie_id"""), {"ids": ids})}
    viewer: dict[int, dict[str, int]] = {}
    for mid, trait, n in viewer_counts(db, ids):
        viewer.setdefault(mid, {})[trait] = n
    return {i: vector(kw.get(i, []), genres.get(i, []), viewer.get(i)) for i in ids}


def viewer_counts(db, ids: list[int]) -> list[tuple[int, str, int]]:
    """(title, trait, different users) from tags that say a trait was present."""
    from sqlalchemy import text
    present = {tag: trait for tag, (_, trait) in LIKED_TAGS.items()}
    present.update({tag: trait for tag, (_, trait, sign) in DISLIKED_TAGS.items() if trait and sign < 0})
    rows = db.execute(text("""SELECT movie_id, tag, count(DISTINCT user_id) FROM title_feedback_tags
        WHERE movie_id = ANY(:ids) AND tag = ANY(:tags) GROUP BY movie_id, tag"""),
                      {"ids": ids, "tags": list(present)}).all()
    agg: dict[tuple[int, str], int] = {}
    for mid, tag, n in rows:
        key = (mid, present[tag])
        agg[key] = max(agg.get(key, 0), n)
    return [(m, t, n) for (m, t), n in agg.items()]


_MEAN_CACHE: dict = {"at": 0.0, "mean": None, "coverage": None}
MEAN_TTL = 6 * 3600


def catalog_mean(db) -> tuple[dict[str, float], dict[str, float]]:
    """(mean trait value, share of titles with the trait >= 0.5) over every title with known traits. Computed in the
    database (one row per trait), cached for MEAN_TTL seconds; viewer tags are left out of the average."""
    if _MEAN_CACHE["mean"] is not None and time.time() - _MEAN_CACHE["at"] < MEAN_TTL:
        return _MEAN_CACHE["mean"], _MEAN_CACHE["coverage"]
    from sqlalchemy import text
    rules = [(name, trait, w) for name, lst in RULES.items() for trait, w in lst]
    values = ", ".join(f"(:n{i}, :t{i}, :w{i})" for i in range(len(rules)))
    p = {}
    for i, (n, t, w) in enumerate(rules):
        p[f"n{i}"], p[f"t{i}"], p[f"w{i}"] = n, t, w
    rows = db.execute(text(f"""
        WITH r(name, trait, w) AS (VALUES {values}),
        eligible AS (SELECT movie_id FROM movie_keywords GROUP BY movie_id HAVING count(*) >= {MIN_KEYWORDS}),
        hits AS (
            SELECT mk.movie_id, r.trait, r.w FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id
              JOIN r ON r.name = lower(k.name) WHERE mk.movie_id IN (SELECT movie_id FROM eligible)
            UNION ALL
            SELECT mg.movie_id, r.trait, r.w FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
              JOIN r ON r.name = 'genre:' || g.name WHERE mg.movie_id IN (SELECT movie_id FROM eligible)),
        ev AS (SELECT movie_id, trait, 1 - exp(-sum(CAST(w AS float))) AS v FROM hits GROUP BY movie_id, trait)
        SELECT trait, sum(v), sum(CASE WHEN v >= 0.5 THEN 1 ELSE 0 END), (SELECT count(*) FROM eligible)
        FROM ev GROUP BY trait"""), p).all()
    n = rows[0][3] if rows else 0
    got = {t: (float(s), int(c)) for t, s, c, _ in rows}
    keys = [t.key for t in TRAITS if t.key != "dialogue"]
    mean = {k: (got[k][0] / n if n and k in got else 0.0) for k in keys}
    coverage = {k: (got[k][1] / n if n and k in got else 0.0) for k in keys}
    mean["dialogue"], coverage["dialogue"] = 0.0, 0.0
    _MEAN_CACHE.update(at=time.time(), mean=mean, coverage=coverage)
    return mean, coverage
