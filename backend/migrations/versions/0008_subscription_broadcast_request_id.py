"""add subscription broadcast request correlation id

Revision ID: f4c8e2a7b193
Revises: a3d9b2e1f458
Create Date: 2026-06-12 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "f4c8e2a7b193"
down_revision: str | None = "a3d9b2e1f458"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "subscription_broadcasts",
        sa.Column("request_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_subscription_broadcasts_request_id",
        "subscription_broadcasts",
        ["request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_broadcasts_request_id", table_name="subscription_broadcasts")
    op.drop_column("subscription_broadcasts", "request_id")
