"""move sync_manifest from cache to durable tables

Revision ID: d8a3c6f0e921
Revises: c7e41a9b2d03
Create Date: 2026-04-06 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "d8a3c6f0e921"
down_revision: str | None = "c7e41a9b2d03"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # sync_manifest was previously a CacheBase table (dropped/recreated on every startup),
    # which caused sync state to be lost on server restarts. Recreate it as a durable table
    # so that the last agreed client-server file state survives across restarts.
    #
    # Drop first in case the table already exists from a prior startup's cache setup.
    op.execute("DROP TABLE IF EXISTS sync_manifest")
    op.create_table(
        "sync_manifest",
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_mtime", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("file_path"),
    )


def downgrade() -> None:
    op.drop_table("sync_manifest")
