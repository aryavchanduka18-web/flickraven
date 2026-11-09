"""IMDb rating and vote count per film, display only (pipeline/imdb_ratings.py)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("movies", sa.Column("imdb_rating", sa.Numeric(3, 1)))
    op.add_column("movies", sa.Column("imdb_votes", sa.Integer))


def downgrade() -> None:
    op.drop_column("movies", "imdb_votes")
    op.drop_column("movies", "imdb_rating")
