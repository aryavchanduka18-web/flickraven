"""Feedback on a recommendation with its reasons and the request that produced it (Perfect Pick rejections)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rec_feedback",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("movie_id", sa.Integer, sa.ForeignKey("movies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("reasons", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("context", postgresql.JSONB),
        sa.Column("surface", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rec_feedback_user_id_created_at", "rec_feedback", ["user_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("rec_feedback")
