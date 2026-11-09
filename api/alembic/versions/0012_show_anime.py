"""user_preferences.show_anime: anime rows and tabs are optional (off by default)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_preferences", sa.Column("show_anime", sa.Boolean, server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("user_preferences", "show_anime")
