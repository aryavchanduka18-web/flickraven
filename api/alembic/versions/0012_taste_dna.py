"""Taste DNA: what a user enjoyed (or not) about a title, and their Refine My Taste settings

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "title_feedback_tags",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("movie_id", sa.Integer, sa.ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag", sa.Text, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_title_feedback_tags_movie_id", "title_feedback_tags", ["movie_id"])
    op.add_column("user_preferences", sa.Column("taste_overrides", JSONB))


def downgrade() -> None:
    op.drop_column("user_preferences", "taste_overrides")
    op.drop_index("ix_title_feedback_tags_movie_id", table_name="title_feedback_tags")
    op.drop_table("title_feedback_tags")
