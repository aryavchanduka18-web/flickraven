"""Impressions (what was actually visible) and the origin row of an action

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "impressions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surface", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("movie_id", sa.Integer, sa.ForeignKey("movies.id", ondelete="CASCADE")),
        sa.Column("position", sa.SmallInteger),
        sa.Column("visible_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_impressions_user_id_created_at", "impressions", ["user_id", sa.text("created_at DESC")])
    op.create_index("ix_impressions_created_at", "impressions", ["created_at"])
    # Each row or card counts once per page load.
    op.execute("CREATE UNIQUE INDEX uq_impressions_once ON impressions (user_id, page_id, surface, kind, (coalesce(movie_id, 0)))")
    op.add_column("interactions", sa.Column("origin", sa.Text))


def downgrade() -> None:
    op.drop_column("interactions", "origin")
    op.drop_table("impressions")
