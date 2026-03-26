"""Base models for durable and cache tables."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class DurableBase(DeclarativeBase):
    """Base class for durable tables managed by Alembic migrations.

    Tables: users, refresh_tokens, social_accounts, cross_posts.
    """


class CacheBase(DeclarativeBase):
    """Base class for cache tables dropped and regenerated on startup.

    Tables: posts_cache, labels_cache, label_parents_cache,
    post_labels_cache, sync_manifest, posts_fts.
    """
