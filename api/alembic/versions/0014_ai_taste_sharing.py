"""Opt-in: share a coarse taste summary with the AI assistant (off by default)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_preferences",
                  sa.Column("ai_taste_sharing", sa.Boolean, server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_column("user_preferences", "ai_taste_sharing")
