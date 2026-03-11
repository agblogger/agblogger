"""Sync manifest model."""

from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import CacheBase


class SyncManifest(CacheBase):
    """Sync manifest entry tracking file state at last sync."""

    __tablename__ = "sync_manifest"

    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_mtime: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[str] = mapped_column(Text, nullable=False)
