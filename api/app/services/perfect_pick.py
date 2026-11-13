from cinematch_engine import taxonomy
"""The Perfect Pick: three titles from three answers (mood, time, familiar or adventurous).

The recommender does the ranking (hybrid score for films, series ranking for series); the answers only narrow the
list and decide how much novelty counts. Nothing here invents a title or a number.
"""
from dataclasses import dataclass, field

from app.services import title_class as tc

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
    inferred: frozenset = frozenset()     # genres a series got from TMDB keywords (see series_genres)
    anime: bool = False                   # TV anime, or a Japanese animated film (same rule as the Anime genre page)


ANIME = "Anime"     # a Perfect Pick genre choice, not a TMDB genre: picking it means "anime only" (a hard limit)


def is_anime_film(genres: list[str], lang: str) -> bool:
    return taxonomy.style("movie", genres, lang) == "anime"     # one rule for the whole site (cinematch_engine.taxonomy)


def soft_genres(pf: "Prefs") -> list[str]:
    """The picked genres that are scored softly. Anime is a hard limit (see select), so it is not one of them."""
    return [g for g in pf.genres if g != ANIME]


# Romance uses the shared rule in title_class.py (same as Home's Romantic rows, 2026-11-12): exact keywords with points,
# Drama/Comedy/Family support, and Crime or Horror without Comedy need a real romance thread. The Romance word set below
# is kept for reference only. The other keyword genres are unchanged.
# TMDB's TV genre list has no Romance, Horror, Thriller, Music or History (pipeline/series.py maps the rest), so no
# series could ever match those genres or the moods built on them (Romantic, Scary, Intense, Suspenseful). Perfect
# Pick adds them from TMDB's own keywords, by exact keyword, and says so on the card. ("bromance" and "slight romance"
# are deliberately not romance; "supernatural" and "ghost" alone are not horror.)
SERIES_KEYWORD_GENRES = {
    "Romance": {"romance", "romantic", "love", "first love", "love triangle", "romantic comedy", "romantic drama",
                "slow burn romance", "enemies to lovers", "friends to lovers", "high school romance", "teenage romance",
                "workplace romance", "office romance", "second chance romance", "unrequited love", "forbidden love",
                "love at first sight", "star crossed lovers", "love polygon", "interspecies romance", "contract relationship",
                "fake marriage", "marriage of convenience", "pretend relationship", "love affair", "dating",
                "lovers reunited", "friends in love", "love-hate relationship"},
    "Horror": {"horror", "slasher", "zombie", "zombie apocalypse", "haunted house", "survival horror", "psychological horror",
               "supernatural horror", "body horror", "folk horror", "exorcism", "demonic possession"},
    "Thriller": {"thriller", "psychological thriller", "crime thriller", "political thriller", "suspense", "serial killer",
                 "conspiracy thriller", "legal thriller", "mystery thriller", "spy thriller"},
    "Music": {"music", "musical", "musician", "singer", "band", "idol", "k-pop", "rock band", "pop star", "singing"},
    "History": {"historical", "history", "period drama", "historical drama", "historical fiction", "costume drama"},
}


# A keyword shows a genre only next to a real TMDB genre that can carry it (a Romance keyword on a Drama or Comedy, a
# Thriller keyword on a Crime, Mystery, Drama or Action series). A keyword alone never makes a genre: a reality show
# with a "romance" keyword, or a sitcom with a "serial killer" keyword, gets nothing.
KEYWORD_GENRE_SUPPORT = {
    "Romance": {"Drama", "Comedy"},
    "Horror": {"Mystery", "Drama", "Science Fiction", "Fantasy", "Crime"},
    "Thriller": {"Crime", "Mystery", "Drama", "Action", "Science Fiction"},
    "Music": {"Drama", "Comedy", "Documentary", "Animation", "Family"},
    "History": {"Drama", "War", "Documentary", "Animation"},
}
KEYWORD_STRENGTH = 0.6      # a keyword-shown genre counts this much of a real TMDB genre when ranking


def series_genres(genres: list[str], keywords: list[str]) -> tuple[list[str], frozenset]:
    """A series' genres plus the ones its TMDB keywords show (only genres TMDB TV lacks, and only with a supporting real
    genre, see KEYWORD_GENRE_SUPPORT). Returns (all, added)."""
    kws = {k.lower() for k in keywords}
    have = set(genres)
    added = frozenset(g for g, words in SERIES_KEYWORD_GENRES.items()
                      if g not in have and (tc.is_romantic(genres, keywords) if g == "Romance"
                                            else kws & words and have & KEYWORD_GENRE_SUPPORT[g]))
    return list(genres) + sorted(added), added


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


@dataclass
class Selection:
    exact: list[Item]                                  # every answer met
    near: list[tuple[Item, list[str]]]                 # hard limits and languages met; misses "mood" and/or "genres"
    other_languages: int = 0                           # when nothing in the chosen languages fits: how many would elsewhere
    exact_elsewhere: int = 0                           # when under three exact: exact matches in other languages


# ---- tone: what a mood does NOT want. Mood-specific, never universal: Horror is a fine Intense pick, a bad Feel-good one.
# The For Tonight rules (moods.yaml) only list what fits a mood, so a crime sitcom fits "Intense" there; Perfect Pick adds
# the other half. A rule applies to a title unless the person picked the genre it fires on (asking for Comedy waives
# the Comedy clash).
LIGHT_KEYWORDS = {"sitcom", "parody", "spoof", "mockumentary", "slapstick", "sketch comedy", "stand-up comedy", "workplace comedy", "cringe comedy"}
DARK_KEYWORDS = {"serial killer", "gore", "slasher", "torture", "massacre", "psychopath"}      # not "murder": most series have a plot murder
SERIOUS_REAL_GENRES = {"Drama", "Thriller", "Action", "War", "Horror"}      # real genres that make a comedy a serious one too
MOOD_EXTRA_FITS = {"Intense": {"Horror"}, "Suspenseful": {"Horror"}}        # on top of moods.yaml, Perfect Pick only
LIGHT_MOODS = {"Intense", "Suspenseful", "Mysterious", "Emotional"}


def _real(it: Item) -> set[str]:
    return set(it.genres) - set(it.inferred)


def tone_clash(it: Item, pf: Prefs) -> str | None:
    """Why this title's tone clashes with the picked mood, or None. Uses real TMDB genres plus keywords; genres that
    were only shown by keywords never decide a clash."""
    mood = pf.mood
    if not mood:
        return None
    real, kws, picked = _real(it), {k.lower() for k in it.keywords}, set(pf.genres)
    light_kw = kws & LIGHT_KEYWORDS
    if mood in LIGHT_MOODS:
        if "Comedy" in real and "Comedy" not in picked and not real & SERIOUS_REAL_GENRES:
            return "a comedy"
        if light_kw and "Comedy" not in picked and "Drama" not in real:
            return "played for laughs"
        if mood != "Emotional" and real & {"Family"} and not real & SERIOUS_REAL_GENRES and "Family" not in picked:
            return "a family show"
    elif mood == "Mind-bending":
        if light_kw and "Comedy" not in picked and not real & {"Science Fiction", "Mystery"}:
            return "played for laughs"
    elif mood == "Scary":
        if "Comedy" in real and "Horror" not in real and "Comedy" not in picked:
            return "a comedy"
        if light_kw and "Comedy" not in picked:
            return "played for laughs"
    elif mood == "Feel-good":
        if real & {"Horror", "War", "Thriller"} - picked or kws & DARK_KEYWORDS:
            return "dark in tone"
        if "Crime" in real and "Crime" not in picked and not real & {"Comedy", "Family"}:
            return "a crime drama"
    elif mood == "Romantic":
        if real & {"Horror", "War"} - picked:
            return "dark in tone"
    elif mood == "Relaxed":
        if real & {"Horror", "Thriller", "War", "Crime"} - picked:
            return "tense, not relaxed"
    return None


def mood_strength(it: Item, pf: Prefs, mood_rule: dict | None, matches) -> float:
    """1 if the mood fits (on any genre, real or keyword-shown), else 0. Keyword-shown genres count less for the PICKED
    genres (genre_strength), not here: for a mood like Scary or Romantic, TV titles can only fit through them."""
    if not (pf.mood and mood_rule):
        return 1.0
    extra = MOOD_EXTRA_FITS.get(pf.mood, set())
    return 1.0 if matches({"genres": it.genres, "keywords": it.keywords}, mood_rule) or set(it.genres) & extra else 0.0


def fits_mood(it: Item, pf: Prefs, mood_rule: dict | None, matches) -> bool:
    return mood_strength(it, pf, mood_rule, matches) > 0


def fits_genres(it: Item, pf: Prefs) -> bool:
    """At least ONE of the picked genres (more matches only rank higher)."""
    soft = soft_genres(pf)
    return not soft or bool(set(soft) & set(it.genres))


def genre_strength(it: Item, pf: Prefs) -> float:
    """Share of the picked genres met; a real TMDB genre counts 1, a keyword-shown one KEYWORD_STRENGTH."""
    soft = soft_genres(pf)
    if not soft:
        return 1.0
    return sum((KEYWORD_STRENGTH if g in it.inferred else 1.0) for g in soft if g in it.genres) / len(soft)


def select(items: list[Item], pf: Prefs, mood_rule: dict | None, matches) -> Selection:
    """Hard limits are never relaxed: kind, time, finished or airing, and the chosen languages (the person widens
    languages themselves with "Include other languages"). Inside them, titles that meet mood and genres are exact
    matches; the rest are kept apart as broader alternatives, each with the answers it misses."""
    anime_only = ANIME in pf.genres
    base = [i for i in items if (pf.kind == "either" or i.kind == pf.kind) and time_ok(i, pf) and status_ok(i, pf)
            and (i.anime or not anime_only)]
    in_lang = [i for i in base if lang_ok(i, pf.languages)]
    exact, near = [], []
    for i in in_lang:
        mood_ok = fits_mood(i, pf, mood_rule, matches)
        # a tone clash is only named when the mood otherwise fits (a title that misses the mood already says so)
        misses = [m for m, ok in (("mood", mood_ok), ("genres", fits_genres(i, pf)),
                                  ("tone", not mood_ok or tone_clash(i, pf) is None)) if not ok]
        (near.append((i, misses)) if misses else exact.append(i))
    outside = len(base) if not in_lang and pf.languages else 0
    elsewhere = 0
    if pf.languages and in_lang and len(exact) < 3:
        elsewhere = sum(1 for i in base if not lang_ok(i, pf.languages) and fits_mood(i, pf, mood_rule, matches) and fits_genres(i, pf)
                        and tone_clash(i, pf) is None)
    return Selection(exact, near, outside, elsewhere)


def rank(items: list[Item], pf: Prefs, mood_rule: dict | None, matches) -> list[Cand]:
    """S = 0.55 relevance + 0.25 genre fit + 0.20 mood fit, relevance as a percentile within films or within series."""
    by_kind: dict[str, dict[int, float]] = {}
    for kind in {i.kind for i in items}:
        grp = [i for i in items if i.kind == kind]
        by_kind[kind] = dict(zip((i.id for i in grp), pct_of([i.rec for i in grp])))
    raw = []
    for i in items:
        g = genre_strength(i, pf)
        m = mood_strength(i, pf, mood_rule, matches)
        raw.append(W_REL * by_kind[i.kind][i.id] + W_GENRE * g + W_MOOD * m)
    return [Cand(i.id, p, i.novelty) for i, p in zip(items, pct_of(raw))]


MISS_TEXT = {"mood": "your mood", "genres": "your picked genres", "tone": "the tone you asked for"}


def pick_alternatives(near: list[tuple[Item, list[str]]], pf: Prefs, mood_rule: dict | None, matches, k: int) -> list[tuple[Cand, list[str]]]:
    """Up to k broader alternatives. Titles that miss one answer come before titles that miss both; inside each group
    the usual score decides (relevance, genre fit, mood fit, then the familiar/new answer for a full set of three)."""
    out: list[tuple[Cand, list[str]]] = []
    misses = {i.id: m for i, m in near}
    for n_missed in (1, 2):
        need = k - len(out)
        group = [i for i, m in near if len(m) == n_missed]
        if need <= 0 or not group:
            continue
        cands = rank(group, pf, mood_rule, matches)
        style = pf.adventure if need >= 3 else "familiar"
        out += [(c, misses[c.id]) for c in choose(cands, style, k=need, genres={i.id: set(i.genres) for i in group})]
    return out


def message(n_exact: int, n_alt: int, pf: Prefs, other_languages: int, exact_elsewhere: int = 0, more: bool = False) -> str | None:
    """What the page says above the picks: how many met every answer, and what the alternatives are. Languages are only
    ever widened by the person, so the text says what turning them on would add. `more` = a "Show more" batch, where
    earlier batches already showed some exact matches."""
    text = _more_message(n_exact, n_alt, pf) if more else _message(n_exact, n_alt, pf, other_languages)
    if exact_elsewhere and n_exact < 3:
        text = ((text + " ") if text else "") + (f"{exact_elsewhere} title{'s' if exact_elsewhere != 1 else ''} in other languages "
                                                f"meet{'s' if exact_elsewhere == 1 else ''} every other answer: turn on \"Include other languages\" to see them.")
    return text


def kept(pf: Prefs) -> str:
    """The answers that are never relaxed, as text: "type, length and languages"."""
    parts = ["type", "length"] + (["anime"] if ANIME in pf.genres else []) + (["languages"] if pf.languages else [])
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _more_message(n_exact: int, n_alt: int, pf: Prefs) -> str | None:
    if n_exact >= 3:
        return None
    if not n_exact and not n_alt:
        return f"That is everything: no other title keeps your {kept(pf)}."
    if not n_alt:
        return "That is the last of the titles that meet every answer."
    lead = "No more titles meet every answer." if not n_exact else (
        f"Only {n_exact} more title{'s' if n_exact != 1 else ''} meet{'s' if n_exact == 1 else ''} every answer.")
    return f"{lead} From here on these are broader alternatives: they keep your {kept(pf)}, and each says which answer it misses."


def _message(n_exact: int, n_alt: int, pf: Prefs, other_languages: int) -> str | None:
    if other_languages:
        names = ", ".join(LANG_NAMES.get(c, "other languages") for c in pf.languages)
        return (f"Nothing in {names} fits your type and length. Turn on \"Include other languages\" to see "
                f"{other_languages} title{'s' if other_languages != 1 else ''} that do.")
    if n_exact >= 3 or not n_alt:
        return None
    if n_exact == 0:
        return f"Nothing meets every answer. Below are broader alternatives: they keep your {kept(pf)}, and each says which answer it misses."
    return (f"Only {n_exact} title{'s' if n_exact != 1 else ''} meet{'s' if n_exact == 1 else ''} every answer. "
            f"The broader alternatives below keep your {kept(pf)}, and each says which answer it misses.")


def reasons_v2(it: Item, role: str, pf: Prefs, misses: list[str], matches, mood_rule: dict | None, match_pct: int | None) -> list[dict]:
    """Only things that were actually checked for this title. `misses` are the answers a broader alternative does not meet."""
    def r(code: str, text: str) -> dict:
        return {"code": code, "source": "perfect_pick", "text": text, "share": 0.0, "anchor_movie_id": None}
    out = []
    if pf.mood and mood_rule:
        out.append(r("pp_mood", f'Does not match the "{pf.mood.lower()}" mood' if "mood" in misses
                     else f'Fits "{pf.mood.lower()}"'))
        if "tone" in misses:
            out.append(r("pp_tone", f'Tone clashes with "{pf.mood.lower()}": {tone_clash(it, pf) or "a different tone"}'))
    soft = soft_genres(pf)
    hit = [g for g in soft if g in it.genres]
    if ANIME in pf.genres and it.anime:
        out.append(r("pp_anime", "Anime, which you picked"))
    if soft:
        if "genres" in misses or not hit:
            out.append(r("pp_genre", f"Not {', '.join(soft)}: outside the genres you picked"))
        else:
            tagged = [g for g in hit if g in it.inferred]
            out.append(r("pp_genre", f"Has {', '.join(hit)}, which you picked"
                         + (f" ({', '.join(tagged)} from TMDB keywords)" if tagged else "")))
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
        out.append(r("pp_taste", f"High in your own ranking of {'series' if it.kind == 'series' else 'films'}"))
    return out[:5]
