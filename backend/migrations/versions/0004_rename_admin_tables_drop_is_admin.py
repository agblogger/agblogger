"""rename users/refresh_tokens to admin_users/admin_refresh_tokens, drop is_admin

Revision ID: c7e41a9b2d03
Revises: b5d91f3e7a02
Create Date: 2026-03-27 00:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic
revision: str = "c7e41a9b2d03"
down_revision: str | None = "b5d91f3e7a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the is_admin column first (every authenticated user is the admin).
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")

    # Rename tables to reflect the single-admin design.
    op.rename_table("users", "admin_users")
    op.rename_table("refresh_tokens", "admin_refresh_tokens")


def downgrade() -> None:
    # Rename tables back.
    op.rename_table("admin_refresh_tokens", "refresh_tokens")
    op.rename_table("admin_users", "users")

    # Re-add the is_admin column.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="1"))
