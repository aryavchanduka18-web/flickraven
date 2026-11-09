"""Load the cleaned catalog into Postgres (step 12). Safe to re-run: everything is an upsert,
and each loaded film's genres, keywords, credits and awards are replaced, never duplicated."""
import math

import pandas as pd
from sqlalchemy import Column, Engine, Integer, MetaData, Table, delete, select, text
from sqlalchemy.dialects.postgresql import insert

from app.models.catalog import SEARCH_VECTOR_UPDATE_SQL
from pipeline.catalog import slugify

MOVIE_COLUMNS = [
    "tmdb_id", "ml_movie_id", "imdb_id", "title", "original_title", "overview", "release_date", "year",
    "runtime_min", "original_language", "spoken_languages", "countries", "certification", "poster_path",
    "backdrop_path", "dominant_color", "tagline", "studios", "logo_path", "catalog_part",
    "ml_rating_count", "ml_rating_mean", "rating_hist", "tmdb_vote_count", "collection_id", "collection_name",
    "title_type", "seasons", "episodes", "series_status",
]
CHUNK = 2000
USER_TABLES = ("onboarding_picks", "ratings", "reactions", "user_movie_list", "watched",
               "interactions", "recommendation_logs")


def _clean(value):
    """pandas/numpy values -> plain Python values psycopg understands (NaN/NA -> None)."""
    if value is None:
        return None
    if hasattr(value, "tolist") and not isinstance(value, str):
        value = value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _records(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    return [{c: _clean(v) for c, v in zip(columns, row)} for row in df[columns].itertuples(index=False)]


def _upsert(conn, table, rows: list[dict], key: str, update: list[str]) -> None:
    for i in range(0, len(rows), CHUNK):
        stmt = insert(table).values(rows[i:i + CHUNK])
        if update:
            stmt = stmt.on_conflict_do_update(index_elements=[key], set_={c: stmt.excluded[c] for c in update})
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=[key])
        conn.execute(stmt)


def _insert(conn, table, rows: list[dict]) -> None:
    for i in range(0, len(rows), CHUNK):
        conn.execute(insert(table).values(rows[i:i + CHUNK]))


def load_catalog(engine: Engine, movies: pd.DataFrame, credits: pd.DataFrame,
                 awards: pd.DataFrame, aggregates: pd.DataFrame, prune: bool = True) -> dict[str, int]:
    """movies: movies_clean rows; credits: credits_clean rows; awards: awards.parquet rows;
    aggregates: per ml_movie_id count, mean, 10-bucket histogram (1..10 scale)."""
    md = MetaData()
    md.reflect(engine, only=["movies", "genres", "movie_genres", "people", "movie_credits",
                             "keywords", "movie_keywords", "movie_awards"])
    t = md.tables

    m = movies.merge(aggregates, on="ml_movie_id", how="left") if len(aggregates) else movies.copy()
    for col, default in (("ml_rating_count", 0), ("ml_rating_mean", None), ("rating_hist", None),
                         ("title_type", "movie"), ("seasons", None), ("episodes", None), ("series_status", None)):
        if col not in m:
            m[col] = default
    m["title_type"] = m["title_type"].fillna("movie")
    for col in ("seasons", "episodes"):                 # whole numbers for the smallint / integer columns
        m[col] = m[col].astype("Int64")
    m["ml_rating_count"] = m["ml_rating_count"].fillna(0).astype(int)
    m["ml_rating_mean"] = m["ml_rating_mean"].map(lambda v: None if v is None or pd.isna(v) else round(float(v), 2))

    with engine.begin() as conn:
        _upsert(conn, t["movies"], _records(m, MOVIE_COLUMNS), "tmdb_id",
                [c for c in MOVIE_COLUMNS if c != "tmdb_id"])
        loaded = set(m["tmdb_id"].tolist())
        movie_id = {k: v for k, v in conn.execute(select(t["movies"].c.tmdb_id, t["movies"].c.id)).all() if k in loaded}
        ids = list(movie_id.values())

        genre_names = sorted({g for gs in m["genres"] for g in gs})
        _upsert(conn, t["genres"], [{"name": g, "slug": slugify(g)} for g in genre_names], "name", [])
        genre_id = dict(conn.execute(select(t["genres"].c.name, t["genres"].c.id)).all())

        kw_names = sorted({k for ks in m["keywords"] for k in ks})
        _upsert(conn, t["keywords"], [{"name": k} for k in kw_names], "name", [])
        # Whole-table id maps: an IN (...) list of ~100k values exceeds the driver's parameter limit.
        kw_id = dict(conn.execute(select(t["keywords"].c.name, t["keywords"].c.id)).all())

        people = credits.drop_duplicates("tmdb_person_id")
        _upsert(conn, t["people"], _records(people, ["tmdb_person_id", "name", "profile_path"]),
                "tmdb_person_id", ["name", "profile_path"])
        person_id = dict(conn.execute(select(t["people"].c.tmdb_person_id, t["people"].c.id)).all())

        for name in ("movie_genres", "movie_keywords", "movie_credits", "movie_awards"):
            for i in range(0, len(ids), CHUNK):
                conn.execute(delete(t[name]).where(t[name].c.movie_id.in_(ids[i:i + CHUNK])))

        _insert(conn, t["movie_genres"], [{"movie_id": movie_id[r.tmdb_id], "genre_id": genre_id[g]}
                                          for r in m.itertuples() for g in dict.fromkeys(r.genres)])
        _insert(conn, t["movie_keywords"], [{"movie_id": movie_id[r.tmdb_id], "keyword_id": kw_id[k]}
                                            for r in m.itertuples() for k in dict.fromkeys(r.keywords)])
        cr = credits[credits["tmdb_id"].isin(movie_id)]
        _insert(conn, t["movie_credits"], [
            {"movie_id": movie_id[r.tmdb_id], "person_id": person_id[r.tmdb_person_id], "role": r.role,
             "character": _clean(r.character), "credit_order": _clean(r.credit_order)}
            for r in cr.itertuples()])
        aw = awards[awards["tmdb_id"].isin(movie_id)]
        _insert(conn, t["movie_awards"], [
            {"movie_id": movie_id[r.tmdb_id], "award": r.award, "category": _clean(r.category),
             "year": _clean(r.year), "result": r.result, "wikidata_id": r.wikidata_id}
            for r in aw.itertuples()])

        # Fresh statistics first: without them the planner thinks these tables are empty and the
        # search-vector join runs as a nested loop that takes many minutes on the full catalog.
        for name in ("movies", "movie_credits", "people"):
            conn.execute(text(f"ANALYZE {name}"))
        conn.execute(text(SEARCH_VECTOR_UPDATE_SQL))

        # Films that left the catalog are removed, unless site users already reference them
        # (deleting those would cascade into user data); kept ones are reported.
        if prune:
            conn.execute(text("CREATE TEMP TABLE keep_ids (tmdb_id int PRIMARY KEY) ON COMMIT DROP"))
            _insert(conn, Table("keep_ids", MetaData(), Column("tmdb_id", Integer)),
                    [{"tmdb_id": int(i)} for i in m["tmdb_id"]])
            referenced = " OR ".join(f"EXISTS (SELECT 1 FROM {u} WHERE {u}.movie_id = movies.id)" for u in USER_TABLES)
            stale = conn.execute(text(
                f"DELETE FROM movies WHERE tmdb_id NOT IN (SELECT tmdb_id FROM keep_ids) AND NOT ({referenced})")).rowcount
            kept = conn.execute(text(
                f"SELECT count(*) FROM movies WHERE tmdb_id NOT IN (SELECT tmdb_id FROM keep_ids) AND ({referenced})")).scalar()

        if prune:
            counts_extra = {"removed_stale_movies": stale, "stale_movies_kept_for_user_data": kept}
        else:
            counts_extra = {}
        counts = {name: conn.execute(text(f"select count(*) from {name}")).scalar()
                  for name in ("movies", "genres", "movie_genres", "people", "movie_credits",
                               "keywords", "movie_keywords", "movie_awards")}
    return {**counts, **counts_extra}
