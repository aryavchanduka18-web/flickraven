"""Shared title classes for themed rows and mood chips: "romantic" and "feel-good".

One definition used by Home's "Romantic series" and "Feel-good series", Home's "Romantic anime" and "Feel-good anime",
the Anime page's romance and feel-good rows, and the Feel-good / Romantic mood chip on genre pages and Discover.
Perfect Pick keeps its own mood rules (perfect_pick.py), which were tuned and checked separately.

Why (2026-11-12, Aryav): Home's "Romantic series" showed Hannibal and Presumed Innocent. The old rule looked for the
letters "romance" or "love" anywhere in the joined keyword text, with no genre check, so "female lover", "bromance",
"lovecraftian", "loved one" and "necromancer" all counted, and one weak tag ("gothic romance") made a crime show romantic.

Romantic, by points over EXACT TMDB keywords (never letters inside other words):
- a real Romance or Soap genre is enough (films have Romance; TMDB TV has no Romance genre);
- a strong romance keyword ("romance", "love triangle", "office romance", ...) = 2 points;
  a weak hint ("love", "dating", "gothic romance", "slight romance", ...) = 1 point;
- a live-action title also needs Drama, Comedy or Family (a reality show or a documentary is not a romance); anime skips
  this, since TMDB gives almost every anime the coarse Sci-Fi & Fantasy / Action & Adventure genres;
- needs 2 points, or 4 when the title is Crime, Mystery or Horror: a crime show with a real romance thread (two strong
  tags) still counts, one with a single stray tag does not.
Checked on the catalogue (laptop movies_clean.parquet): against MyAnimeList's Romance genre for 648 matched anime,
precision 0.63 -> 0.74 at recall 0.76 (unchanged); live-action series with 300+ votes 180 -> 144 (Hannibal, Presumed
Innocent, Lovecraft Country, Better Call Saul, WandaVision out; Bridgerton, Heartstopper, Crash Landing on You,
Queen Charlotte, Sex and the City in). Known losses: shows with sparse tags and a Mystery genre (e.g. Pushing Daisies).

Feel-good: on top of each surface's own genre rule, no dark keyword (dark comedy, gore, horror, serial killer, ...),
unless the title is a clear romance.
"""
from __future__ import annotations

ROMANCE_GENRES = {"Romance", "Soap"}
ROMANCE_SUPPORT = {"Drama", "Comedy", "Family"}           # live action needs one of these
ROMANCE_CONFLICT = {"Crime", "Mystery", "Horror"}          # these need more evidence
ROMANCE_POINTS = 2
ROMANCE_POINTS_CONFLICT = 4
STRONG_POINTS, WEAK_POINTS = 2, 1

ROMANCE_STRONG = frozenset({
    "romance", "romantic", "romcom", "romantic comedy", "romantic drama", "romantic fantasy", "love story", "true love",
    "love triangle", "love polygon", "love square", "first love", "first love reunion", "young love", "teenage love",
    "teenage romance", "high school romance", "school love", "slow burn romance", "enemies to lovers", "friends to lovers",
    "hate to love", "love-hate relationship", "workplace romance", "office romance", "second chance romance",
    "unrequited love", "one-sided love", "forbidden love", "forbidden romance", "love at first sight",
    "star crossed lovers", "interspecies romance", "interracial romance", "contract relationship", "contract marriage",
    "fake marriage", "marriage of convenience", "pretend relationship", "love affair", "lovers reunited",
    "friends in love", "searching for love", "enduring love", "tragic love", "gay romance", "lgbt romance",
    "step-sibling romance", "unlikely romance", "adult romance", "healing romance", "horror romance", "period romance",
    "historical romance", "boys' love (bl)", "girls' love (gl)",
})
ROMANCE_WEAK = frozenset({"love", "dating", "gothic romance", "slight romance", "psychological romance", "lovesickness"})

FEELGOOD_DARK_KEYWORDS = frozenset({
    "dark comedy", "black comedy", "gore", "horror", "slasher", "serial killer", "massacre", "psychopath",
})    # not "death", "suicide", "zombie" or "torture": they drop Angel Beats!, Zombie Land Saga and The Good Place


def _kws(keywords) -> set[str]:
    return {k.lower() for k in keywords} if keywords is not None else set()     # list or numpy array


def romance_points(keywords) -> int:
    k = _kws(keywords)
    return STRONG_POINTS * len(k & ROMANCE_STRONG) + WEAK_POINTS * len(k & ROMANCE_WEAK)


def romance_strength(genres, keywords, anime: bool = False) -> int:
    """0 = not romantic. Otherwise the evidence: 4+ is clear (Romance/Soap genre, or two strong tags), 2-3 is enough."""
    g = set(genres) if genres is not None else set()
    if g & ROMANCE_GENRES:
        return ROMANCE_POINTS_CONFLICT + 1
    if not anime and not g & ROMANCE_SUPPORT:
        return 0
    pts = romance_points(keywords)
    need = ROMANCE_POINTS_CONFLICT if g & ROMANCE_CONFLICT else ROMANCE_POINTS
    return pts if pts >= need else 0


def is_romantic(genres, keywords, anime: bool = False) -> bool:
    return romance_strength(genres, keywords, anime) > 0


def clear_romance(genres, keywords, anime: bool = False) -> bool:
    """Strong evidence: rows put these first, so a borderline title never leads a romance row."""
    return romance_strength(genres, keywords, anime) >= ROMANCE_POINTS_CONFLICT


def dark_in_tone(keywords, genres=None) -> bool:
    """A dark keyword: never in a feel-good row. A clear romance tagged "dark comedy" (Queen of Tears) stays."""
    if not _kws(keywords) & FEELGOOD_DARK_KEYWORDS:
        return False
    return genres is None or not clear_romance(genres, keywords, anime=True)


def evidence_first(ids: list[int], clear: set[int]) -> list[int]:
    """Clear romances first, each group keeping the given (personal) order."""
    return [i for i in ids if i in clear] + [i for i in ids if i not in clear]


def romance_sql(alias: str = "m") -> tuple[str, dict]:
    """The same romantic rule as SQL on a movies alias (genre pages and Discover)."""
    genres = (f"SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = {alias}.id "
              "AND g.name = ANY(:{key})")
    points = (f"(SELECT COALESCE(SUM(CASE WHEN lower(k.name) = ANY(:rom_strong) THEN {STRONG_POINTS} "
              f"WHEN lower(k.name) = ANY(:rom_weak) THEN {WEAK_POINTS} ELSE 0 END), 0) "
              f"FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id WHERE mk.movie_id = {alias}.id)")
    sql = (f"(EXISTS ({genres.format(key='rom_genres')}) OR ("
           f"({alias}.title_type = 'anime' OR EXISTS ({genres.format(key='rom_support')})) AND "
           f"{points} >= CASE WHEN EXISTS ({genres.format(key='rom_conflict')}) THEN {ROMANCE_POINTS_CONFLICT} "
           f"ELSE {ROMANCE_POINTS} END))")
    return sql, {"rom_genres": sorted(ROMANCE_GENRES), "rom_support": sorted(ROMANCE_SUPPORT),
                 "rom_conflict": sorted(ROMANCE_CONFLICT), "rom_strong": sorted(ROMANCE_STRONG),
                 "rom_weak": sorted(ROMANCE_WEAK)}


def dark_keyword_sql(alias: str = "m") -> tuple[str, dict]:
    """SQL: the title has a dark keyword (used as NOT ... in the feel-good chip)."""
    return (f"EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id "
            f"WHERE mk.movie_id = {alias}.id AND lower(k.name) = ANY(:fg_dark))", {"fg_dark": sorted(FEELGOOD_DARK_KEYWORDS)})
