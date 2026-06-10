"""add subscription_settings and subscription_broadcasts tables

Revision ID: e2b4f7a1c509
Revises: d8a3c6f0e921
Create Date: 2026-06-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "e2b4f7a1c509"
down_revision: str | None = "d8a3c6f0e921"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "subscription_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resend_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("resend_segment_id", sa.String(), nullable=True),
        sa.Column("from_email", sa.String(), nullable=True),
        sa.Column("from_name", sa.String(), nullable=True),
        sa.Column("controller_name", sa.String(), nullable=True),
        sa.Column("controller_contact", sa.String(), nullable=True),
        sa.Column("privacy_policy_url", sa.String(), nullable=True),
        sa.Column("postal_address", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_subscription_settings_singleton"),
    )
    op.create_table(
        "subscription_broadcasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_path", sa.Text(), nullable=False),
        sa.Column("post_title", sa.Text(), nullable=False, server_default=""),
        sa.Column("resend_broadcast_id", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("sent_at", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "trigger IN ('auto', 'manual')", name="ck_subscription_broadcasts_trigger"
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')", name="ck_subscription_broadcasts_status"
        ),
    )
    op.create_index(
        "ix_subscription_broadcasts_post_path",
        "subscription_broadcasts",
        ["post_path"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_broadcasts_post_path", "subscription_broadcasts")
    op.drop_table("subscription_broadcasts")
    op.drop_table("subscription_settings")
