"""Anime genre, theme and mature filters for the Anime genre page (/genres/anime).

TMDB has no anime genres, so every tag is a rule over real TMDB data: genre names and keyword names. Which tags exist
was decided by an audit of the catalog (docs/decisions-log.md, 2026-11-12): only tags with enough titles and good
agreement with the MyAnimeList genre lists are offered. TMDB's TV genres are coarse ("Action & Adventure" and
"Sci-Fi & Fantasy" are split into two genres each, so every TV anime carries both halves); for Adventure, Fantasy and
Sci-Fi the TV side therefore uses keywords only, while films (which have the real genres) use genre OR keyword.

A filter is a browse constraint only. It is never a taste signal and nothing here is stored.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_TITLES = 30      # a tag with fewer titles than this is not offered

# key: (label, group, genres for TV and films, genres for films only, keywords)
TAGS: dict[str, tuple[str, str, list[str], list[str], list[str]]] = {
    "action": ("Action", "genre", ["Action"], [], ["action", "fight", "fighting", "battle", "combat", "martial arts", "swordplay", "tournament"]),
    "adventure": ("Adventure", "genre", [], ["Adventure"], ["adventure", "journey", "adventurer", "travel", "quest", "pirate", "dungeon crawling"]),
    "comedy": ("Comedy", "genre", ["Comedy"], [], ["comedy", "romcom", "slapstick comedy", "teen comedy", "dark comedy", "absurdist"]),
    "fantasy": ("Fantasy", "genre", [], ["Fantasy"], ["fantasy", "magic", "fantasy world", "dark fantasy", "high fantasy", "urban fantasy", "witch", "wizard", "dragon", "elves", "magic school", "fairy"]),
    "sci-fi": ("Sci-Fi", "genre", [], ["Science Fiction"], ["science fiction", "alien", "robot", "android", "cyborg", "time travel", "dystopia", "artificial intelligence (a.i.)", "virtual reality", "post-apocalyptic future", "space", "space opera"]),
    "romance": ("Romance", "genre", ["Romance"], [], ["romance", "romcom", "romantic", "love triangle", "love polygon", "first love", "high school romance", "unrequited love"]),
    "slice-of-life": ("Slice of Life", "genre", [], [], ["slice of life", "iyashikei"]),
    "mystery": ("Mystery", "genre", ["Mystery"], [], ["mystery", "detective", "murder mystery"]),
    "horror": ("Horror", "genre", [], ["Horror"], ["horror", "gore", "zombie", "body horror", "psychological horror"]),
    "psychological": ("Psychological", "genre", [], [], ["psychological", "psychological thriller", "psychological horror", "philosophical"]),
    "supernatural": ("Supernatural", "genre", [], [], ["supernatural", "ghost", "youkai", "curse", "supernatural power"]),
    "sports": ("Sports", "genre", [], [], ["sports", "high school sports", "team sports", "sport competition", "basketball", "baseball", "boxing", "football (soccer)"]),
    "mecha": ("Mecha", "genre", [], [], ["mecha", "giant robot", "real robot", "super robot", "piloted robot", "gundam"]),
    "music": ("Music", "genre", [], ["Music"], ["music", "idol", "idol group", "band", "rock band", "girl band", "musician", "classical music"]),
    "magical-girl": ("Magical Girl", "genre", [], [], ["magical girl"]),
    # Themes: story types fans search for. Literal keywords only.
    "isekai": ("Isekai", "theme", [], [], ["isekai", "other world", "another world"]),
    "reincarnation": ("Reincarnation", "theme", [], [], ["reincarnation"]),
    "time-travel": ("Time Travel", "theme", [], [], ["time travel"]),
    "survival": ("Survival", "theme", [], [], ["survival", "death game", "battle royale"]),
    "post-apocalyptic": ("Post-Apocalyptic", "theme", [], [], ["post-apocalyptic", "post-apocalyptic future", "zombie apocalypse"]),
    "cyberpunk": ("Cyberpunk", "theme", [], [], ["cyberpunk"]),
    "school": ("School", "theme", [], [], ["school", "school life", "high school", "japanese high school", "high school student", "school club", "middle school"]),
    "martial-arts": ("Martial Arts", "theme", [], [], ["martial arts"]),
    "military": ("Military", "theme", ["War"], [], ["military", "military strategy", "war"]),
    "demons": ("Demons", "theme", [], [], ["demon", "demon lord"]),
    "historical": ("Historical", "theme", [], ["History"], ["historical", "historical fiction", "alternate history"]),
    "harem": ("Harem", "theme", [], [], ["harem"]),
    # Mature content: never in the normal chips.
    "ecchi": ("Ecchi", "mature", [], [], ["ecchi", "erotic"]),
}


def parse(value: str | None) -> list[str]:
    """Known tag keys from a comma-separated query value (unknown keys are ignored)."""
    return list(dict.fromkeys(k for k in (x.strip() for x in (value or "").split(",")) if k in TAGS))


def tag_sql(key: str, n: int) -> tuple[str, dict]:
    """SQL condition on table alias m for one tag, with its parameters (made unique by n)."""
    _, _, both, film_only, kws = TAGS[key]
    parts, p = [], {}
    if both:
        parts.append(f"EXISTS (SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id AND g.name = ANY(:tg{n}))")
        p[f"tg{n}"] = both
    if film_only:
        parts.append(f"(m.title_type = 'movie' AND EXISTS (SELECT 1 FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE mg.movie_id = m.id AND g.name = ANY(:tf{n})))")
        p[f"tf{n}"] = film_only
    if kws:
        parts.append(f"EXISTS (SELECT 1 FROM movie_keywords mk JOIN keywords k ON k.id = mk.keyword_id WHERE mk.movie_id = m.id AND k.name = ANY(:tk{n}))")
        p[f"tk{n}"] = kws
    return "(" + " OR ".join(parts) + ")", p


def where(include: list[str], avoid: list[str]) -> tuple[list[str], dict]:
    """Conditions for a request: any of `include` (OR), and none of `avoid`. A tag in both lists is only avoided."""
    conds, params = [], {}
    inc = [k for k in include if k not in avoid]
    if inc:
        sqls = []
        for n, k in enumerate(inc):
            s, p = tag_sql(k, n)
            sqls.append(s); params.update(p)
        conds.append("(" + " OR ".join(sqls) + ")")
    for n, k in enumerate(avoid):
        s, p = tag_sql(k, 100 + n)
        conds.append(f"NOT {s}"); params.update(p)
    return conds, params


ANIME_SET = "m.title_type IN ('movie', 'anime') AND m.original_language = 'ja' AND {animation}"   # same rule as the Anime genre


def counts(db: Session, animation_ids_sql: str) -> list[dict]:
    """Every tag with its live number of anime titles (TV anime and Japanese animated films); tags below MIN_TITLES
    are left out. `animation_ids_sql` is the catalog's Animation-genre condition on alias m."""
    base = ANIME_SET.format(animation=animation_ids_sql)
    out = []
    for n, k in enumerate(TAGS):
        s, p = tag_sql(k, 0)
        total = db.execute(text(f"SELECT count(*) FROM movies m WHERE {base} AND {s}"), p).scalar() or 0
        if total >= MIN_TITLES:
            label, group = TAGS[k][0], TAGS[k][1]
            out.append({"key": k, "label": label, "group": group, "titles": total})
    return out
