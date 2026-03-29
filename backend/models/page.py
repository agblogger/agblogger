"""Page cache model."""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import CacheBase


class PageCache(CacheBase):
    """Cached rendered HTML for top-level pages (regenerated from filesystem)."""

    __tablename__ = "pages_cache"

    page_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_html: Mapped[str] = mapped_column(Text, nullable=False)
