"""Search: what the query means (genre, language, year words) and the SQL that finds the films.

"horror" lists horror films, "hindi comedy" Hindi comedies, "90s action" action films of the 1990s,
"comedy 2019" comedies of 2019, most popular first. Words that are not genre, language or year words are
searched as text: titles (exact, starting with, a word starting with), cast, director, genre by name, and
typos ("horrible bossses"). "dar" finds The Dark Knight; "nol" finds Christopher Nolan's films.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.catalog import normalize_sql

SEARCH_LIMIT = 60
FUZZY_BELOW = 10          # fuzzy title matches are added only when the exact search finds fewer films
FUZZY_MIN_CHARS = 3       # shorter queries have too few trigrams to compare
FUZZY_THRESHOLD = 0.6     # pg_trgm word_similarity of the query to the closest part of a title

# Language names a person types -> TMDB original_language codes of the catalog.
LANGUAGES = {
    "english": "en", "hindi": "hi", "tamil": "ta", "telugu": "te", "malayalam": "ml", "kannada": "kn",
    "bengali": "bn", "bangla": "bn", "marathi": "mr", "korean": "ko", "japanese": "ja", "spanish": "es",
    "french": "fr", "german": "de", "italian": "it", "mandarin": "zh", "chinese": "zh", "cantonese": "cn",
    "portuguese": "pt", "turkish": "tr", "persian": "fa", "farsi": "fa", "russian": "ru", "swedish": "sv",
    "danish": "da", "norwegian": "no", "finnish": "fi", "polish": "pl", "dutch": "nl", "thai": "th",
    "arabic": "ar", "indonesian": "id", "punjabi": "pa", "urdu": "ur", "gujarati": "gu",
}
FILLER = {"movie", "movies", "film", "films", "cinema"}
# Spellings of genres that are not the stored name (stored: "Science Fiction", "TV Movie", ...).
GENRE_ALIASES = {
    "scifi": ["Science Fiction"], "sci-fi": ["Science Fiction"], "sci fi": ["Science Fiction"],
    "science fiction": ["Science Fiction"], "romcom": ["Romance", "Comedy"], "rom-com": ["Romance", "Comedy"],
    "rom com": ["Romance", "Comedy"], "comedies": ["Comedy"], "thrillers": ["Thriller"], "dramas": ["Drama"],
    "documentaries": ["Documentary"], "docs": ["Documentary"], "westerns": ["Western"], "horrors": ["Horror"],
    "romantic": ["Romance"], "animated": ["Animation"], "cartoon": ["Animation"], "cartoons": ["Animation"],
    "tv movie": ["TV Movie"],
}


@dataclass
class Parsed:
    genres: list[str] = field(default_factory=list)
    language: str | None = None
    year: int | None = None
    decade: tuple[int, int] | None = None
    text: str = ""

    @property
    def has_filters(self) -> bool:
        return bool(self.genres or self.language or self.year or self.decade)

    def understood(self) -> dict:
        return {"genres": self.genres, "language": self.language, "year": self.year,
                "decade": list(self.decade) if self.decade else None, "text": self.text}


def parse(q: str, genre_names: list[str]) -> Parsed:
    """Split a query into genre / language / year / decade filters and the remaining text words."""
    by_lower = {g.lower(): g for g in genre_names}
    words = re.findall(r"[\w'’-]+", q.lower())
    out, rest, i = Parsed(), [], 0
    while i < len(words):
        w, pair = words[i], " ".join(words[i:i + 2])
        decade = re.fullmatch(r"(?:(19|20))?(\d)0s", w)
        gs, step = None, 1
        if pair in GENRE_ALIASES:
            gs, step = GENRE_ALIASES[pair], 2
        elif w in GENRE_ALIASES:
            gs = GENRE_ALIASES[w]
        elif w in by_lower:
            gs = [by_lower[w]]
        if gs:
            out.genres += [g for g in gs if g in genre_names and g not in out.genres]
        elif w in LANGUAGES and not out.language:
            out.language = LANGUAGES[w]
        elif re.fullmatch(r"(19|20)\d\d", w) and not out.year and not out.decade:
            out.year = int(w)
        elif decade and not out.decade and not out.year:
            tens = int(decade.group(2)) * 10
            century = int(decade.group(1)) * 100 if decade.group(1) else (1900 if tens >= 30 else 2000)
            out.decade = (century + tens, century + tens + 9)
        elif w in FILLER and len(words) > 1:
            pass
        else:
            rest.append(w)
        i += step
    out.text = " ".join(rest)
    return out


def prefix_words(q: str) -> list[str]:
    """The query's words for a prefix tsquery, normalized like titles: lower case, dots and apostrophes
    dropped, anything that is not a letter or digit splits words."""
    q = re.sub(r"[.'’`]", "", q.lower())
    return [w for w in re.split(r"[\W_]+", q) if w][:8]


def like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def genre_names(db: Session) -> list[str]:
    return [r[0] for r in db.execute(text("SELECT name FROM genres ORDER BY name"))]


def _filters(p: Parsed) -> tuple[str, dict]:
    """SQL conditions (joined by AND, or '') for the genre, language and year words of the query."""
    sql, params = [], {}
    for k, g in enumerate(p.genres):
        sql.append(f"EXISTS (SELECT 1 FROM movie_genres fg{k} JOIN genres fgg{k} ON fgg{k}.id = fg{k}.genre_id "
                   f"WHERE fg{k}.movie_id = m.id AND fgg{k}.name = :fg{k})")
        params[f"fg{k}"] = g
    if p.language:
        sql.append("m.original_language = :flang")
        params["flang"] = p.language
    if p.year:
        sql.append("m.year = :fyear")
        params["fyear"] = p.year
    if p.decade:
        sql.append("m.year BETWEEN :fdec_lo AND :fdec_hi")
        params["fdec_lo"], params["fdec_hi"] = p.decade
    return " AND ".join(sql), params


POPULAR = "m.popularity_score DESC NULLS LAST, m.tmdb_vote_count DESC NULLS LAST, m.id"


def search_ids(db: Session, q: str, limit: int = SEARCH_LIMIT) -> tuple[list[int], Parsed]:
    """Film ids for a query, best first, and what the query was understood as."""
    q = q.strip()
    p = parse(q, genre_names(db))
    filt, fparams = _filters(p)
    # Filters only: the most popular films that match all of them.
    if p.has_filters and not p.text:
        rows = db.execute(text(f"SELECT m.id FROM movies m WHERE {filt} ORDER BY {POPULAR} LIMIT :limit"),
                          {**fparams, "limit": limit})
        return [r[0] for r in rows], p
    term = p.text if p.has_filters else q
    if not term:
        return [], p
    # text() would read ":alnum" in the regex as a bind parameter, so those colons are escaped.
    qn = "(" + normalize_sql(":q").replace("[:alnum:]", r"[\:alnum\:]") + ")"
    words = prefix_words(term)
    # 'dar':* & 'kni':* -- only letters and digits reach the tsquery, so nothing in it needs escaping.
    # A query of only punctuation gives an empty tsquery, which matches nothing (Postgres only notes it).
    tsq = " & ".join(f"'{w}':*" for w in words)
    extra = f" AND {filt}" if filt else ""
    # A genre named in the query is already a filter; otherwise a partial genre name ("horr") adds that genre's films.
    genre_or = "" if p.has_filters else (
        "OR m.id IN (SELECT mg.movie_id FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id WHERE g.name ILIKE :like ESCAPE '\\')")
    ids = [r[0] for r in db.execute(text(f"""
        WITH hits AS (
            SELECT m.id, m.tmdb_vote_count AS votes,
                   ts_rank(m.search_vector, to_tsquery('simple', :tsq)) AS rank,
                   CASE WHEN m.title_norm IN ({qn}, 'the ' || {qn}) THEN 0
                        WHEN m.title_norm LIKE {qn} || '%' OR m.title_norm LIKE 'the ' || {qn} || '%' THEN 1
                        WHEN ' ' || m.title_norm LIKE '% ' || {qn} || '%' THEN 2
                        ELSE 3 END AS tier
            FROM movies m
            WHERE ((:has_words AND m.search_vector @@ to_tsquery('simple', :tsq))
               {genre_or}
               OR m.title ILIKE :like ESCAPE '\\'
               OR ({qn} <> '' AND m.title_norm LIKE '%' || {qn} || '%')){extra})
        SELECT id FROM hits
        ORDER BY tier, CASE WHEN tier < 3 THEN votes END DESC NULLS LAST, rank DESC, votes DESC NULLS LAST
        LIMIT :limit"""), {"q": term, "tsq": tsq, "has_words": bool(words), "like": f"%{like_escape(term)}%",
                           "limit": limit, **fparams})]
    if len(ids) < FUZZY_BELOW and len(term) >= FUZZY_MIN_CHARS:
        # Sets the threshold of the indexed <% operator for this transaction only.
        db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
                   {"t": str(FUZZY_THRESHOLD)})
        fuzzy = db.execute(text(f"""
            SELECT m.id FROM movies m
            WHERE {qn} <% m.title_norm{extra}
            ORDER BY round(greatest(word_similarity({qn}, m.title_norm), similarity({qn}, m.title_norm))::numeric, 2) DESC,
                     m.tmdb_vote_count DESC NULLS LAST
            LIMIT :limit"""), {"q": term, "limit": limit, **fparams})
        seen = set(ids)
        ids += [r[0] for r in fuzzy if r[0] not in seen][:limit - len(ids)]
    return ids, p


def find_people(db: Session, q: str, limit: int = 5) -> list[dict]:
    """People whose name starts with the query or has a word that does, the ones with most films first."""
    q = q.strip()
    if len(q) < 3:
        return []
    like = like_escape(q)
    rows = db.execute(text("""
        SELECT p.id, p.name, p.profile_path,
               (SELECT count(DISTINCT mc.movie_id) FROM movie_credits mc WHERE mc.person_id = p.id) AS films
        FROM people p
        WHERE p.name ILIKE :a ESCAPE '\\' OR p.name ILIKE :b ESCAPE '\\'
           OR (:squashed <> '' AND replace(lower(p.name), ' ', '') LIKE :squashed || '%')
        ORDER BY films DESC, p.name LIMIT :limit"""), {
        "a": f"{like}%", "b": f"% {like}%", "limit": limit,
        # "shahrukh" finds Shah Rukh Khan: the query and the names are compared with the spaces left out.
        "squashed": like_escape(re.sub(r"\s+", "", q.lower())) if len(q) >= 4 else ""}).mappings()
    return [dict(r) for r in rows if r["films"]]


def find_genres(db: Session, q: str) -> list[dict]:
    """Genres whose name starts with the query ("horr" -> Horror), for a link to the genre page."""
    q = q.strip()
    if len(q) < 3:
        return []
    rows = db.execute(text("SELECT name, slug FROM genres WHERE name ILIKE :a ESCAPE '\\' ORDER BY name"),
                      {"a": f"{like_escape(q)}%"}).mappings()
    return [dict(r) for r in rows]
