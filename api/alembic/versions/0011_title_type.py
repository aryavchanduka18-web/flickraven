"""title_type (movie, series, anime) and series facts on movies

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("movies", sa.Column("title_type", sa.Text, server_default="movie", nullable=False))
    op.add_column("movies", sa.Column("seasons", sa.SmallInteger))
    op.add_column("movies", sa.Column("episodes", sa.Integer))
    op.add_column("movies", sa.Column("series_status", sa.Text))
    op.create_check_constraint("ck_movies_title_type", "movies", "title_type IN ('movie','series','anime')")
    op.create_index("ix_movies_title_type", "movies", ["title_type"])


def downgrade() -> None:
    op.drop_index("ix_movies_title_type", table_name="movies")
    op.drop_constraint("ck_movies_title_type", "movies")
    op.drop_column("movies", "series_status")
    op.drop_column("movies", "episodes")
    op.drop_column("movies", "seasons")
    op.drop_column("movies", "title_type")
