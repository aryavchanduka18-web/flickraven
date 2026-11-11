"""Append-only logs: every user event, and every recommendation that was shown."""
import uuid
from datetime import datetime

from sqlalchemy import REAL, BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Interaction(Base):
    __tablename__ = "interactions"
    __table_args__ = (
        Index("ix_interactions_user_id_created_at", "user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    movie_id: Mapped[int | None] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(REAL)
    source: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    origin: Mapped[str | None] = mapped_column(Text)      # the row or page the action came from (source = where it happened)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Impression(Base):
    """A row or card that was genuinely visible (on screen long enough), reported by the browser. Never a rejection."""
    __tablename__ = "impressions"
    __table_args__ = (
        Index("ix_impressions_user_id_created_at", "user_id", text("created_at DESC")),
        Index("ix_impressions_created_at", "created_at"),
        Index("uq_impressions_once", "user_id", "page_id", "surface", "kind", text("(coalesce(movie_id, 0))"), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    page_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    movie_id: Mapped[int | None] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    position: Mapped[int | None] = mapped_column(SmallInteger)
    visible_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecommendationLog(Base):
    __tablename__ = "recommendation_logs"
    __table_args__ = (Index("ix_recommendation_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    surface: Mapped[str | None] = mapped_column(Text)
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int | None] = mapped_column(SmallInteger)
    final_score: Mapped[float | None] = mapped_column(REAL)
    match_pct: Mapped[int | None] = mapped_column(SmallInteger)
    components: Mapped[dict | None] = mapped_column(JSONB)
    reason_code: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )