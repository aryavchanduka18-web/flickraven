"""Where to watch: movie_watch_providers (TMDB watch/providers, data by JustWatch)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "movie_watch_providers",
        sa.Column("movie_id", sa.Integer, sa.ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.Text, primary_key=True),
        sa.Column("provider_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.CHAR(2), nullable=False),
        sa.Column("provider_name", sa.Text, nullable=False),
        sa.Column("logo_path", sa.Text),
        sa.Column("display_priority", sa.Integer),
        sa.Column("link", sa.Text),
        sa.Column("fetched_on", sa.Date, nullable=False),
        sa.CheckConstraint("kind IN ('flatrate','free','ads','rent','buy')", name="ck_movie_watch_providers_kind"),
    )


def downgrade() -> None:
    op.drop_table("movie_watch_providers")
