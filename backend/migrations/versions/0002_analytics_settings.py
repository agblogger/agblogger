"""add analytics_settings table

Revision ID: a3c72e8d4f01
Revises: f11ad63c6789
Create Date: 2026-03-25 00:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic
revision: str = "a3c72e8d4f01"
down_revision: str | None = "f11ad63c6789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False),
        sa.Column("show_views_on_posts", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("analytics_settings")
