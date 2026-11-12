"""Shared title classes for themed rows and mood chips: "romantic" and "feel-good".

One definition used by Home's "Romantic series" and "Feel-good series", Home's "Romantic anime" and "Feel-good anime",
the Anime page's romance and feel-good rows, and the Feel-good / Romantic mood chip on genre pages and Discover.
Perfect Pick uses it for the Romance it adds to series from keywords; its other mood rules are its own.

Why (2026-11-12, Aryav): Home's "Romantic series" showed Hannibal and Presumed Innocent. The old rule looked for the
letters "romance" or "love" anywhere in the joined keyword text, with no genre check, so "female lover", "bromance",
"lovecraftian", "loved one" and "necromancer" all counted, and one weak tag ("gothic romance") made a crime show romantic.

Romantic, by points over EXACT TMDB keywords (never letters inside other words):
- a real Romance or Soap genre is enough (films have Romance; TMDB TV has no Romance genre);
- a strong romance keyword ("romance", "love triangle", "office romance", ...) = 2 points;
  a weak hint ("love", "dating", "gothic romance", "slight romance", ...) = 1 point;
- a live-action title also needs Drama, Comedy or Family (a reality show or a documentary is not a romance); anime skips
  this, since TMDB gives almost every anime the coarse Sci-Fi & Fantasy / Action & Adventure genres;
- needs 2 points; Crime or Horror without Comedy need 4 (a crime show with a real romance thread, two strong tags,
  still counts; one with a single stray tag does not); a film without the Romance genre needs 4.
Tiers (rows show them in this order, each in the person's order): LEAD = Romance/Soap genre or 4+ points; ROMANCE =
2-3 points and no conflicting genre; SUBPLOT = 2-3 points next to Mystery, Sci-Fi/Fantasy, Action, War, Thriller, or
Crime/Horror softened by Comedy (Healer, Moonlighting, Veronica Mars).
Checked on the catalogue (laptop movies_clean.parquet): against MyAnimeList's Romance genre for 648 matched anime,
precision 0.63 -> 0.72, recall 0.76 -> 0.80; live-action series with 300+ votes 180 -> 158 (Hannibal, Presumed
Innocent, Lovecraft Country, Better Call Saul, WandaVision out). Perfect Pick's keyword Romance for series uses this too.

Feel-good: on top of each surface's own genre rule, not dark in tone: no heavy keyword (gore, serial killer, child
abuse, ...) and under 3 tone points from keywords and genres together (one "dark comedy" tag is 1 point, never enough
alone; light keywords such as sitcom or friendship subtract). A lead romance is exempt unless it has a heavy keyword.
"""
from __future__ import annotations

ROMANCE_GENRES = {"Romance", "Soap"}
ROMANCE_SUPPORT = {"Drama", "Comedy", "Family"}           # live action needs one of these
ROMANCE_HARD_CONFLICT = {"Crime", "Horror"}                  # need 4 points unless there is also Comedy
ROMANCE_SOFT_CONFLICT = {"Crime", "Horror", "Mystery", "Science Fiction", "Fantasy", "Sci-Fi & Fantasy", "Action",
                         "Action & Adventure", "War", "War & Politics", "Thriller"}   # romance is then a subplot
ROMANCE_CONFLICT = ROMANCE_HARD_CONFLICT
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
    "historical romance", "rekindled romance", "boys' love (bl)", "girls' love (gl)",
})
ROMANCE_WEAK = frozenset({"love", "dating", "gothic romance", "slight romance", "psychological romance", "lovesickness"})

# Feel-good tone, from several signals together (2026-11-12, Aryav: "dark comedy" alone must not reject Arrested
# Development, Fleabag or Blackadder). A title is dark in tone when it has a heavy keyword, or when its tone points reach
# FEELGOOD_DARK_POINTS: violent keywords 2, other dark themes 1, each violent genre 1, +1 more for a dark comedy that is
# also violent (an action genre, a violent keyword or a murder: Peacemaker, Sweetpea), minus 1 for each light keyword
# (sitcom, friendship, slice of life, ...). So dark comedy as a genre never disqualifies on its own; a bleak tone (several
# dark themes) or disturbing content (a heavy keyword, or violence) does.
FEELGOOD_HEAVY = frozenset({
    "gore", "slasher", "serial killer", "massacre", "psychopath", "horror", "body horror", "supernatural horror",
    "folk horror", "survival horror", "splatter", "cannibalism", "child sexual abuse", "childhood sexual abuse",
    "rape and revenge", "mass murder",
})   # not "torture" (The Good Place), "child abuse" (Annie, Pinocchio, EverAfter: TMDB uses it for cruel stepparents),
     # "cannibal" (The BFG), "death", "suicide" or "zombie" alone (Angel Beats!, Zombie Land Saga): those are themes
FEELGOOD_VIOLENT = frozenset({"hitman", "assassin", "killing", "gun violence", "rape"})
FEELGOOD_MILD = frozenset({
    "dark comedy", "black comedy", "murder", "child abuse", "cannibal", "death", "grief", "suicide", "depression", "drugs", "drug dealer", "drug addiction",
    "addiction", "trauma", "post-traumatic stress disorder (ptsd)", "revenge", "zombie", "zombie apocalypse", "cynical",
    "cynicism", "violence", "prison", "organized crime", "dark fantasy", "nihilism", "war", "psychotic",
})
FEELGOOD_LIGHT = frozenset({
    "sitcom", "slice of life", "friendship", "found family", "heart warming", "heartwarming", "iyashikei", "healing",
    "family", "family relationships", "workplace comedy", "mockumentary", "feel-good", "wholesome", "cozy", "cosy",
    "coming of age", "best friend",
})
FEELGOOD_DARK_GENRES = frozenset({"Action", "Action & Adventure", "Horror", "Thriller", "Crime", "War", "War & Politics"})
FEELGOOD_DARK_POINTS = 3
FEELGOOD_DARK_KEYWORDS = FEELGOOD_HEAVY | FEELGOOD_VIOLENT | FEELGOOD_MILD      # every keyword that counts toward dark


def _kws(keywords) -> set[str]:
    return {k.lower() for k in keywords} if keywords is not None else set()     # list or numpy array


def romance_points(keywords) -> int:
    k = _kws(keywords)
    return STRONG_POINTS * len(k & ROMANCE_STRONG) + WEAK_POINTS * len(k & ROMANCE_WEAK)


LEAD, ROMANCE, SUBPLOT = 3, 2, 1      # romance_tier values (0 = not romantic)


def romance_tier(genres, keywords, anime: bool = False, film: bool = False) -> int:
    """How romantic a title is, from its genres and exact keywords:
    LEAD     a Romance/Soap genre or 4+ points (romance is the point of the show);
    ROMANCE  2-3 points on a title with no conflicting genre;
    SUBPLOT  2-3 points next to Mystery or Sci-Fi/Fantasy, or Crime/Horror softened by Comedy (Healer, Moonlighting,
             Pinocchio, Veronica Mars): romance matters, but it shares the show with something else;
    0        under 2 points; a live-action title without Drama, Comedy or Family; Crime or Horror without Comedy and
             under 4 points (Better Call Saul's single "romance" tag, Flower of Evil); a film without the Romance
             genre and under 4 points (films have a real Romance genre, so a stray "love" tag means little)."""
    g = set(genres) if genres is not None else set()
    if g & ROMANCE_GENRES:
        return LEAD
    if not anime and not g & ROMANCE_SUPPORT:
        return 0
    pts = romance_points(keywords)
    if pts >= ROMANCE_POINTS_CONFLICT:
        return LEAD
    if film:              # films have a real Romance genre, so keywords alone must be strong (Whiplash, Shrek stay out)
        return 0
    if pts < ROMANCE_POINTS:
        return 0
    if g & ROMANCE_HARD_CONFLICT and "Comedy" not in g:
        return 0
    return SUBPLOT if g & ROMANCE_SOFT_CONFLICT else ROMANCE


def romance_strength(genres, keywords, anime: bool = False) -> int:
    """Back-compat alias of romance_tier."""
    return romance_tier(genres, keywords, anime)


def is_romantic(genres, keywords, anime: bool = False, film: bool = False) -> bool:
    return romance_tier(genres, keywords, anime, film) > 0


def clear_romance(genres, keywords, anime: bool = False) -> bool:
    """Romance is the point of the title (LEAD)."""
    return romance_tier(genres, keywords, anime) == LEAD


def dark_points(keywords, genres=None) -> int:
    """Tone points (see FEELGOOD_*): higher = darker. Heavy keywords are counted separately by dark_in_tone."""
    k, g = _kws(keywords), set(genres) if genres is not None else set()
    violent_genre = len(g & FEELGOOD_DARK_GENRES)
    dark_comedy = bool(k & {"dark comedy", "black comedy"})
    violent = violent_genre or k & (FEELGOOD_VIOLENT | {"murder"})
    return (2 * len(k & FEELGOOD_VIOLENT) + len(k & FEELGOOD_MILD) + violent_genre
            + (1 if dark_comedy and violent else 0) - len(k & FEELGOOD_LIGHT))


def dark_in_tone(keywords, genres=None) -> bool:
    """Never in a feel-good row: a heavy keyword (gore, serial killer, child abuse...), or tone points of 3 or more
    from several signals together. One "dark comedy" tag is never enough on its own. A lead romance stays unless it
    has a heavy keyword (Queen of Tears)."""
    k = _kws(keywords)
    if k & FEELGOOD_HEAVY:
        return True
    if dark_points(keywords, genres) < FEELGOOD_DARK_POINTS:
        return False
    return genres is None or not clear_romance(genres, keywords, anime=True)


def evidence_first(ids: list[int], tier: dict[int, int]) -> list[int]:
    """Higher romance tier first (lead, then romance, then subplot); inside a tier the given personal order is kept."""
    return sorted(ids, key=lambda i: -tier.get(i, 0))          # sorted() is stable


def romance_sql(alias: str = "m") -> tuple[str, dict]:
    """The same romantic rule as SQL on a movies alias (genre pages and Discover)."""
    genres = (f"SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = {alias}.id "
              "AND g.name = ANY(:{key})")
    points = (f"(SELECT COALESCE(SUM(CASE WHEN lower(k.name) = ANY(:rom_strong) THEN {STRONG_POINTS} "
              f"WHEN lower(k.name) = ANY(:rom_weak) THEN {WEAK_POINTS} ELSE 0 END), 0) "
              f"FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id WHERE mk.movie_id = {alias}.id)")
    sql = (f"(EXISTS ({genres.format(key='rom_genres')}) OR ("
           f"({alias}.title_type = 'anime' OR EXISTS ({genres.format(key='rom_support')})) AND "
           f"{points} >= CASE WHEN {alias}.title_type = 'movie' THEN {ROMANCE_POINTS_CONFLICT} WHEN EXISTS ({genres.format(key='rom_conflict')}) AND NOT EXISTS ({genres.format(key='rom_comedy')}) "
           f"THEN {ROMANCE_POINTS_CONFLICT} ELSE {ROMANCE_POINTS} END))")
    return sql, {"rom_genres": sorted(ROMANCE_GENRES), "rom_support": sorted(ROMANCE_SUPPORT),
                 "rom_conflict": sorted(ROMANCE_HARD_CONFLICT), "rom_comedy": ["Comedy"], "rom_strong": sorted(ROMANCE_STRONG),
                 "rom_weak": sorted(ROMANCE_WEAK)}


def dark_keyword_sql(alias: str = "m") -> tuple[str, dict]:
    """SQL twin of dark_in_tone without the romance exemption (the chip adds that): a heavy keyword, or tone points of
    FEELGOOD_DARK_POINTS or more."""
    kw = (f"(SELECT COALESCE(SUM(CASE WHEN lower(k.name) = ANY(:fg_violent) THEN 2 WHEN lower(k.name) = ANY(:fg_mild) THEN 1 "
          f"WHEN lower(k.name) = ANY(:fg_light) THEN -1 ELSE 0 END), 0) "
          f"FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id WHERE mk.movie_id = {alias}.id)")
    gen = (f"(SELECT count(*) FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id "
           f"WHERE mg.movie_id = {alias}.id AND g.name = ANY(:fg_dgen))")
    dc = (f"EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id "
          f"WHERE mk.movie_id = {alias}.id AND lower(k.name) IN ('dark comedy', 'black comedy'))")
    heavy = (f"EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id "
             f"WHERE mk.movie_id = {alias}.id AND lower(k.name) = ANY(:fg_heavy))")
    vk = (f"EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id "
          f"WHERE mk.movie_id = {alias}.id AND (lower(k.name) = ANY(:fg_violent) OR lower(k.name) = 'murder'))")
    sql = (f"({heavy} OR ({kw} + {gen} + CASE WHEN {dc} AND ({gen} > 0 OR {vk}) THEN 1 ELSE 0 END) >= {FEELGOOD_DARK_POINTS})")
    return sql, {"fg_heavy": sorted(FEELGOOD_HEAVY), "fg_violent": sorted(FEELGOOD_VIOLENT), "fg_mild": sorted(FEELGOOD_MILD),
                 "fg_light": sorted(FEELGOOD_LIGHT), "fg_dgen": sorted(FEELGOOD_DARK_GENRES)}
