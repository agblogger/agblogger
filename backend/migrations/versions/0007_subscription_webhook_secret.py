"""add resend_webhook_secret_encrypted to subscription_settings

Revision ID: a3d9b2e1f458
Revises: e2b4f7a1c509
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a3d9b2e1f458"
down_revision: str | None = "e2b4f7a1c509"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "subscription_settings",
        sa.Column("resend_webhook_secret_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscription_settings", "resend_webhook_secret_encrypted")
