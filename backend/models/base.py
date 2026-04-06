"""Base models for durable and cache tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from sqlalchemy import Table


class DurableBase(DeclarativeBase):
    """Base class for durable tables managed by Alembic migrations.

    Tables: admin_users, admin_refresh_tokens, social_accounts, cross_posts,
    analytics_settings, sync_manifest.
    """


class CacheBase(DeclarativeBase):
    """Base class for cache tables dropped and regenerated on startup.

    Tables: posts_cache, pages_cache, labels_cache, label_parents_cache,
    post_labels_cache.
    """


def cache_non_virtual_tables() -> list[Table]:
    """Return cache tables that SQLAlchemy should manage directly."""
    return [
        table
        for table in CacheBase.metadata.sorted_tables
        if not table.info.get("is_virtual", False)
    ]
