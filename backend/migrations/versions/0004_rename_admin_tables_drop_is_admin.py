"""rename users/refresh_tokens to admin_users/admin_refresh_tokens, drop is_admin

Revision ID: c7e41a9b2d03
Revises: b5d91f3e7a02
Create Date: 2026-03-27 00:00:00.000000
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic
revision: str = "c7e41a9b2d03"
down_revision: str | None = "b5d91f3e7a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _social_accounts_table(user_table: str) -> sa.Table:
    """Return a Table definition for social_accounts with FK pointing to the given user table."""
    return sa.Table(
        "social_accounts",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("account_name", sa.String(), nullable=False),
        sa.Column("credentials", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [f"{user_table}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "platform", "account_name"),
    )


def _cross_posts_table(user_table: str) -> sa.Table:
    """Return a Table definition for cross_posts with FK pointing to the given user table."""
    return sa.Table(
        "cross_posts",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("post_path", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("platform_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("posted_at", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [f"{user_table}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    # Preserve the old authorization boundary by pruning legacy non-admin users
    # before every remaining row becomes an admin_user. Delete dependent rows
    # explicitly instead of relying on SQLite cascade behavior during migration.
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "DELETE FROM refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE is_admin = 0)"
        )
    )
    logger.info("Pruned %d refresh token(s) from non-admin users", result.rowcount)
    result = conn.execute(
        sa.text(
            "DELETE FROM social_accounts WHERE user_id IN (SELECT id FROM users WHERE is_admin = 0)"
        )
    )
    logger.info("Pruned %d social account(s) from non-admin users", result.rowcount)
    result = conn.execute(
        sa.text(
            "DELETE FROM cross_posts WHERE user_id IN (SELECT id FROM users WHERE is_admin = 0)"
        )
    )
    logger.info("Pruned %d cross post(s) from non-admin users", result.rowcount)
    result = conn.execute(sa.text("DELETE FROM users WHERE is_admin = 0"))
    logger.info("Pruned %d non-admin user(s)", result.rowcount)

    # Drop the is_admin column first (every authenticated user is the admin).
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")

    # Rename tables to reflect the single-admin design.
    op.rename_table("users", "admin_users")
    op.rename_table("refresh_tokens", "admin_refresh_tokens")

    # Recreate social_accounts and cross_posts via batch_alter_table to ensure
    # their FK constraints explicitly reference admin_users. Modern SQLite
    # (3.25.0+) updates FK text automatically on ALTER TABLE RENAME, but batch
    # recreation makes the schema DDL unambiguous and portable.
    with op.batch_alter_table(
        "social_accounts", copy_from=_social_accounts_table("admin_users"), recreate="always"
    ):
        pass  # copy_from defines the target schema; no extra ops needed

    with op.batch_alter_table(
        "cross_posts", copy_from=_cross_posts_table("admin_users"), recreate="always"
    ):
        pass  # copy_from defines the target schema; no extra ops needed


def downgrade() -> None:
    # Rename tables back to their pre-upgrade names first, then recreate
    # social_accounts and cross_posts via batch_alter_table so their FK
    # constraints explicitly reference the restored "users" table.
    op.rename_table("admin_refresh_tokens", "refresh_tokens")
    op.rename_table("admin_users", "users")

    with op.batch_alter_table(
        "social_accounts", copy_from=_social_accounts_table("users"), recreate="always"
    ):
        pass

    with op.batch_alter_table(
        "cross_posts", copy_from=_cross_posts_table("users"), recreate="always"
    ):
        pass

    # Re-add the is_admin column. New rows default to 0 (non-admin). The UPDATE
    # below sets every existing row to 1 because all rows that survived to this
    # revision were admin users (non-admins were pruned during the upgrade step).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"))
    op.execute("UPDATE users SET is_admin = 1")
