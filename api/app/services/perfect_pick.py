"""The Perfect Pick: three titles from three answers (mood, time, familiar or adventurous).

The recommender does the ranking (hybrid score for films, series ranking for series); the answers only narrow the
list and decide how much novelty counts. Nothing here invents a title or a number.
"""
from dataclasses import dataclass, field

TIMES = {"short": "Under 90 minutes", "medium": "About 2 hours", "long": "Plenty of time", "series": "A series"}
ADVENTURES = ("familiar", "balanced", "adventurous")
SERIES_MAX_HOURS = 25          # "a series I can finish": 25 hours or less in total
FLOOR = {"familiar": 0.0, "balanced": 0.3, "adventurous": 0.35}       # lowest recommender percentile each style accepts


@dataclass
class Cand:
    id: int
    pct: float            # percentile of the user's score among the candidates, 0..1 (1 = best)
    novelty: float        # 0..1, higher = less well known
    role: str = "close"   # close | step_out | surprise


def _top(pool: list[Cand], k: int, key, genres: dict[int, set[str]] | None) -> list[Cand]:
    """The k best by `key`. With genres given, each next pick loses a quarter of its score for every bit of genre overlap
    with what is already chosen (greedy MMR), so three picks are not three of the same thing."""
    left = sorted(pool, key=lambda c: (-key(c), c.id))
    if not genres:
        return left[:k]
    out: list[Cand] = []
    while left and len(out) < k:
        def adj(c: Cand) -> float:
            g = genres.get(c.id, set())
            overlap = max((len(g & genres.get(o.id, set())) / max(len(g | genres.get(o.id, set())), 1) for o in out), default=0.0)
            return key(c) - 0.25 * overlap
        best = max(left, key=lambda c: (adj(c), -c.id))
        out.append(best)
        left.remove(best)
    return out


def choose(cands: list[Cand], adventure: str, k: int = 3, genres: dict[int, set[str]] | None = None) -> list[Cand]:
    """Familiar: the best by recommender score. Adventurous: score and novelty together (never below the floor).
    Balanced: the best two by score and one surprise (the most novel title that still scores well)."""
    if adventure not in ADVENTURES:
        raise ValueError(adventure)
    pool = sorted(cands, key=lambda c: (-c.pct, c.id))
    if adventure == "familiar":
        return [Cand(c.id, c.pct, c.novelty, "close") for c in _top(pool, k, lambda c: c.pct, genres)]
    if adventure == "adventurous":
        eligible = [c for c in pool if c.pct >= FLOOR["adventurous"]] or pool
        best = _top(eligible, k, lambda c: 0.55 * c.pct + 0.45 * c.novelty, genres)
        return [Cand(c.id, c.pct, c.novelty, "step_out") for c in best]
    top = _top(pool, k - 1, lambda c: c.pct, genres)
    others = [c for c in pool if c not in top]
    rest = [c for c in others if c.pct >= FLOOR["balanced"]] or others
    surprise = sorted(rest, key=lambda c: (-c.novelty, -c.pct, c.id))[:1]
    return [Cand(c.id, c.pct, c.novelty, "close") for c in top] + [Cand(c.id, c.pct, c.novelty, "surprise") for c in surprise]


def pct_of(values: list[float]) -> list[float]:
    """Percentile of each value within the list (the largest is 1.0)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    for rank, i in enumerate(order, 1):
        out[i] = rank / n
    return out


def reasons(role: str, mood: str, mood_exact: bool, time_text: str, match_pct: int | None) -> list[dict]:
    """Plain sentences, each one something the code actually checked."""
    def r(code: str, text: str) -> dict:
        return {"code": code, "source": "perfect_pick", "text": text, "share": 0.0, "anchor_movie_id": None}
    out = [r("pp_mood", f"Fits \"{mood.lower()}\"" if mood_exact else f"Not a perfect fit for \"{mood.lower()}\": the closest we found"),
           r("pp_time", time_text)]
    if role == "surprise":
        out.append(r("pp_surprise", "The one surprise: less well known, still scores well for you"))
    elif role == "step_out":
        out.append(r("pp_step_out", "A step outside your usual picks: less well known, still on your taste"))
    elif match_pct is not None:
        out.append(r("pp_taste", f"{match_pct}% match with your taste"))
    else:
        out.append(r("pp_taste", "High in your own ranking of series"))
    return out


# ---------------------------------------------------------------- the questionnaire (v2)

MOVIE_TIMES = {"lt90": (0, 89), "90_120": (90, 120), "120_180": (121, 180), "any": (0, 10**6)}      # minutes
SERIES_TIMES = {"season": None, "h10": (0, 600), "h20": (601, 1200), "h30": (1201, 1800), "any": (0, 10**6)}   # total minutes
EITHER_TIMES = {"e120": (0, 120), "e180": (0, 180), "e600": (0, 600), "any": (0, 10**6)}              # total minutes, films and series
TIME_TEXT = {"lt90": "under 90 minutes", "90_120": "90 to 120 minutes", "120_180": "2 to 3 hours", "season": "one season",
             "h10": "under 10 hours", "h20": "10 to 20 hours", "h30": "20 to 30 hours", "e120": "under 2 hours",
             "e180": "under 3 hours", "e600": "under 10 hours", "any": "any length"}
STATUS = {"completed": {"Ended", "Canceled"}, "airing": {"Returning Series"}}
KNOWN_LANGS = {"en", "hi", "ko", "ja", "ta", "te", "ml"}
LANG_NAMES = {"en": "English", "hi": "Hindi", "ko": "Korean", "ja": "Japanese", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam"}
# score = relevance to this person + how many of the picked genres it has + whether it fits the mood
W_REL, W_GENRE, W_MOOD = 0.55, 0.25, 0.20


@dataclass
class Item:
    id: int
    kind: str                 # movie | series
    genres: list[str]
    keywords: list[str]
    lang: str
    minutes: float | None     # film runtime, or total minutes of a series (episodes x episode length)
    seasons: int | None
    status: str | None
    rec: float                # the recommender's raw score (hybrid for films, series ranking for series)
    novelty: float
    episodes: int | None = None


@dataclass
class Prefs:
    kind: str = "movie"                       # movie | series | either
    mood: str | None = None
    genres: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)      # codes, "other" = any not in KNOWN_LANGS; empty = any
    time: str = "any"
    status: str = "any"                       # any | completed | airing (series only)
    adventure: str = "balanced"


def time_ok(it: Item, pf: Prefs) -> bool:
    if pf.time == "any":
        return True
    if it.kind == "series" and pf.kind == "series" and pf.time == "season":
        return it.seasons == 1
    table = MOVIE_TIMES if pf.kind == "movie" else SERIES_TIMES if pf.kind == "series" else EITHER_TIMES
    band = table.get(pf.time)
    if band is None or it.minutes is None:
        return False
    return band[0] <= it.minutes <= band[1]


def lang_ok(it: Item, langs: list[str]) -> bool:
    return not langs or it.lang in langs or ("other" in langs and it.lang not in KNOWN_LANGS)


def status_ok(it: Item, pf: Prefs) -> bool:
    return it.kind != "series" or pf.status == "any" or it.status in STATUS.get(pf.status, set())


def select(items: list[Item], pf: Prefs, mood_rule: dict | None, matches) -> tuple[list[Item], list[str]]:
    """Hard limits first (kind, time, finished or airing), then the soft ones, relaxed in a fixed order until at
    least three titles remain: mood, then the picked genres, then language. Returns the titles and what was relaxed."""
    base = [i for i in items if (pf.kind == "either" or i.kind == pf.kind) and time_ok(i, pf) and status_ok(i, pf)]
    gset = set(pf.genres)
    tiers = [(True, True, True), (False, True, True), (False, False, True), (False, False, False)]
    for use_mood, use_genre, use_lang in tiers:
        got = [i for i in base
               if (not use_mood or not mood_rule or matches({"genres": i.genres, "keywords": i.keywords}, mood_rule))
               and (not use_genre or not gset or gset & set(i.genres))
               and (not use_lang or lang_ok(i, pf.languages))]
        if len(got) >= 3 or (use_mood, use_genre, use_lang) == tiers[-1]:
            relaxed = []
            if not use_mood and pf.mood:
                relaxed.append("mood")
            if not use_genre and gset:
                relaxed.append("genres")
            if not use_lang and pf.languages:
                relaxed.append("languages")
            return got, relaxed
    return [], []


def rank(items: list[Item], pf: Prefs, mood_rule: dict | None, matches) -> list[Cand]:
    """S = 0.55 relevance + 0.25 genre fit + 0.20 mood fit, relevance as a percentile within films or within series."""
    by_kind: dict[str, dict[int, float]] = {}
    for kind in {i.kind for i in items}:
        grp = [i for i in items if i.kind == kind]
        by_kind[kind] = dict(zip((i.id for i in grp), pct_of([i.rec for i in grp])))
    gset = set(pf.genres)
    raw = []
    for i in items:
        g = len(gset & set(i.genres)) / len(gset) if gset else 1.0
        m = 1.0 if not (pf.mood and mood_rule) else float(matches({"genres": i.genres, "keywords": i.keywords}, mood_rule))
        raw.append(W_REL * by_kind[i.kind][i.id] + W_GENRE * g + W_MOOD * m)
    return [Cand(i.id, p, i.novelty) for i, p in zip(items, pct_of(raw))]


RELAX_TEXT = {"mood": "the mood", "genres": "your picked genres", "languages": "your language choice"}


def relax_note(relaxed: list[str]) -> str | None:
    if not relaxed:
        return None
    return "Not enough exact matches, so I relaxed " + ", then ".join(RELAX_TEXT[r] for r in relaxed) + "."


def reasons_v2(it: Item, role: str, pf: Prefs, relaxed: list[str], matches, mood_rule: dict | None, match_pct: int | None) -> list[dict]:
    """Only things that were actually checked for this title."""
    def r(code: str, text: str) -> dict:
        return {"code": code, "source": "perfect_pick", "text": text, "share": 0.0, "anchor_movie_id": None}
    out = []
    if pf.mood and mood_rule:
        fits_mood = matches({"genres": it.genres, "keywords": it.keywords}, mood_rule)
        out.append(r("pp_mood", f'Fits "{pf.mood.lower()}"' if fits_mood else f'Not a perfect fit for "{pf.mood.lower()}": the closest we found'))
    hit = [g for g in pf.genres if g in it.genres]
    if pf.genres:
        out.append(r("pp_genre", f"Has {', '.join(hit)}, which you picked" if hit else "Outside the genres you picked: the closest we found"))
    if pf.languages and lang_ok(it, pf.languages):
        out.append(r("pp_lang", f"In {LANG_NAMES.get(it.lang, 'a language you chose')}" if it.lang in LANG_NAMES else "In one of the languages you chose"))
    if it.kind == "series":
        h = (it.minutes or 0) / 60
        bits = [f"About {h:g} hours in total" + (f" ({it.episodes} episodes)" if it.episodes else "") if it.minutes else "Length not known"]
        if it.status in STATUS["completed"]:
            bits.append("finished")
        elif it.status in STATUS["airing"]:
            bits.append("still airing")
        out.append(r("pp_time", ", ".join(bits)))
    elif it.minutes:
        out.append(r("pp_time", f"{int(it.minutes) // 60}h {int(it.minutes) % 60}m" + ("" if pf.time == "any" else f", {TIME_TEXT.get(pf.time, 'fits your time')}")))
    if role == "surprise":
        out.append(r("pp_surprise", "The one surprise: less well known, still scores well for you"))
    elif role == "step_out":
        out.append(r("pp_step_out", "A step outside your usual picks: less well known, still on your taste"))
    elif match_pct is not None:
        out.append(r("pp_taste", f"{match_pct}% match with your taste"))
    else:
        out.append(r("pp_taste", "High in your own ranking of series"))
    return out[:5]
