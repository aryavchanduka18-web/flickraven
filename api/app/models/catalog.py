"""Movie catalogue: movies, genres, people, keywords, awards."""
from datetime import date

from sqlalchemy import (
    CHAR, CheckConstraint, Computed, Date, ForeignKey, Index, Integer, Numeric, REAL,
    SmallInteger, String, Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Full-text search (spec section 10): title + cast + director. Cast and directors live in
# other tables, so the column is filled by the catalog loader (pipeline/loader.py) with
# SEARCH_VECTOR_UPDATE_SQL rather than being a generated column.
SEARCH_VECTOR_UPDATE_SQL = """
UPDATE movies m SET search_vector =
    setweight(to_tsvector('simple', coalesce(m.title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(m.original_title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(p.directors, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(p.cast_names, '')), 'C')
FROM (
    SELECT mv.id,
           string_agg(pe.name, ' ') FILTER (WHERE mc.role = 'director') AS directors,
           string_agg(pe.name, ' ') FILTER (WHERE mc.role = 'cast') AS cast_names
    FROM movies mv
    LEFT JOIN movie_credits mc ON mc.movie_id = mv.id
    LEFT JOIN people pe ON pe.id = mc.person_id
    GROUP BY mv.id
) p
WHERE p.id = m.id
"""


def normalize_sql(expr: str) -> str:
    """SQL that normalizes a title (or a search query) for typo-tolerant matching: lower case, dots and
    apostrophes removed ("L.A." -> "la", "Schindler's" -> "schindlers"), any other run of punctuation
    or spaces turned into one space. Used for movies.title_norm and, with the same expression, the query."""
    return (f"lower(btrim(regexp_replace(regexp_replace({expr}, '[.''’`]', '', 'g'), "
            f"'[^[:alnum:]]+', ' ', 'g')))")


TITLE_NORM_SQL = normalize_sql("title")


class Movie(Base):
    __tablename__ = "movies"
    __table_args__ = (
        CheckConstraint("catalog_part IN ('A','B','C','D')", name="ck_movies_catalog_part"),
        CheckConstraint("title_type IN ('movie','series','anime')", name="ck_movies_title_type"),
        Index("ix_movies_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_movies_title_norm_trgm", "title_norm", postgresql_using="gin",
              postgresql_ops={"title_norm": "gin_trgm_ops"}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    ml_movie_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    imdb_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_title: Mapped[str | None] = mapped_column(Text)
    overview: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    runtime_min: Mapped[int | None] = mapped_column(SmallInteger)
    original_language: Mapped[str | None] = mapped_column(String(3))
    spoken_languages: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    countries: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    certification: Mapped[str | None] = mapped_column(Text)
    poster_path: Mapped[str | None] = mapped_column(Text)
    backdrop_path: Mapped[str | None] = mapped_column(Text)
    dominant_color: Mapped[str | None] = mapped_column(CHAR(7))
    tagline: Mapped[str | None] = mapped_column(Text)
    studios: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    logo_path: Mapped[str | None] = mapped_column(Text)
    catalog_part: Mapped[str | None] = mapped_column(CHAR(1))
    ml_rating_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    ml_rating_mean: Mapped[float | None] = mapped_column(Numeric(4, 2))
    # 10 buckets: count of ratings at 1, 2, ..., 10
    rating_hist: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    popularity_score: Mapped[float | None] = mapped_column(REAL)
    tmdb_vote_count: Mapped[int | None] = mapped_column(Integer)
    # IMDb's own rating, display only (pipeline/imdb_ratings.py, IMDb's non-commercial dataset). Models,
    # sorting and filters never read these; switch the display off with IMDB_RATINGS=false.
    imdb_rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    imdb_votes: Mapped[int | None] = mapped_column(Integer)
    # movie, series or anime. A series is stored with tmdb_id = 10,000,000 + its TV id (pipeline/series.py).
    title_type: Mapped[str] = mapped_column(Text, server_default="movie", nullable=False, index=True)
    seasons: Mapped[int | None] = mapped_column(SmallInteger)
    episodes: Mapped[int | None] = mapped_column(Integer)
    series_status: Mapped[str | None] = mapped_column(Text)
    # TMDB collection (franchise), for "More from <collection>" on the film page.
    collection_id: Mapped[int | None] = mapped_column(Integer, index=True)
    collection_name: Mapped[str | None] = mapped_column(Text)
    search_vector = mapped_column(TSVECTOR)
    title_norm: Mapped[str | None] = mapped_column(Text, Computed(TITLE_NORM_SQL, persisted=True))


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class MovieGenre(Base):
    __tablename__ = "movie_genres"

    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_person_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    profile_path: Mapped[str | None] = mapped_column(Text)


class MovieCredit(Base):
    __tablename__ = "movie_credits"
    __table_args__ = (
        CheckConstraint("role IN ('cast','director','writer')", name="ck_movie_credits_role"),
    )

    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    character: Mapped[str | None] = mapped_column(Text)
    credit_order: Mapped[int | None] = mapped_column(SmallInteger)


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class MovieKeyword(Base):
    __tablename__ = "movie_keywords"

    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class MovieAward(Base):
    __tablename__ = "movie_awards"
    __table_args__ = (
        CheckConstraint("result IN ('won','nominated')", name="ck_movie_awards_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    award: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    wikidata_id: Mapped[str | None] = mapped_column(Text)


class MovieWatchProvider(Base):
    """Where a film can be watched (TMDB watch/providers, data by JustWatch), one row per service and kind.

    Only one region is kept per film: India when TMDB lists any service there, else the fallback region
    (pipeline/watch_providers.py). Refreshed monthly; `link` is TMDB's page for that film and region,
    which links on to the services. The site only links out and never claims a film is available
    anywhere TMDB does not list it."""
    __tablename__ = "movie_watch_providers"
    __table_args__ = (
        CheckConstraint("kind IN ('flatrate','free','ads','rent','buy')", name="ck_movie_watch_providers_kind"),
    )

    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_path: Mapped[str | None] = mapped_column(Text)
    display_priority: Mapped[int | None] = mapped_column(Integer)
    link: Mapped[str | None] = mapped_column(Text)
    fetched_on: Mapped[date] = mapped_column(Date, nullable=False)
