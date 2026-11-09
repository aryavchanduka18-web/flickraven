"""Users and their current state: preferences, onboarding, ratings, reactions, list, watched.

These tables hold the *current* answer (one row per user and movie). The full history
of events lives in the append-only interactions table (see activity.py).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, false, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def user_fk(**kw) -> Mapped[int]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), **kw)


def movie_fk(**kw) -> Mapped[int]:
    return mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), **kw)


def created_now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_guest_created_at", "created_at", postgresql_where=text("is_guest")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    is_guest: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = created_now()
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sessions issued before this moment are no longer accepted (see app/auth.py).
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint(
            "discovery_mode IN ('familiar','balanced','discover')",
            name="ck_user_preferences_discovery_mode",
        ),
    )

    user_id: Mapped[int] = user_fk(primary_key=True)
    languages: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    liked_genre_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    disliked_genre_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    # Anime rows, tabs and onboarding picks are optional; anime stays searchable either way.
    show_anime: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    # Tune sliders {adventurous, hidden, international, length}, 0-100, 50 = neutral (engine Tuning).
    tuning: Mapped[dict | None] = mapped_column(JSONB)
    discovery_mode: Mapped[str] = mapped_column(Text, server_default="balanced", nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnboardingPick(Base):
    """Movies picked during onboarding. These are preference signals, not behavioural
    interactions, so they do not move a user out of the cold-start stage."""

    __tablename__ = "onboarding_picks"

    user_id: Mapped[int] = user_fk(primary_key=True)
    movie_id: Mapped[int] = movie_fk(primary_key=True, index=True)
    created_at: Mapped[datetime] = created_now()


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 10", name="ck_ratings_rating"),)

    user_id: Mapped[int] = user_fk(primary_key=True)
    movie_id: Mapped[int] = movie_fk(primary_key=True, index=True)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = created_now()
    updated_at: Mapped[datetime] = created_now()


class Reaction(Base):
    __tablename__ = "reactions"
    __table_args__ = (CheckConstraint("value IN (-1, 1)", name="ck_reactions_value"),)

    user_id: Mapped[int] = user_fk(primary_key=True)
    movie_id: Mapped[int] = movie_fk(primary_key=True, index=True)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    updated_at: Mapped[datetime] = created_now()


class UserMovieList(Base):
    __tablename__ = "user_movie_list"

    user_id: Mapped[int] = user_fk(primary_key=True)
    movie_id: Mapped[int] = movie_fk(primary_key=True, index=True)
    added_at: Mapped[datetime] = created_now()


class Watched(Base):
    __tablename__ = "watched"

    user_id: Mapped[int] = user_fk(primary_key=True)
    movie_id: Mapped[int] = movie_fk(primary_key=True, index=True)
    marked_at: Mapped[datetime] = created_now()