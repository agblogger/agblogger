"""Post cache models and FTS table DDL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import CacheBase

if TYPE_CHECKING:
    from backend.models.label import PostLabelCache


class PostCache(CacheBase):
    """Cached post metadata (regenerated from filesystem)."""

    __tablename__ = "posts_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    labels: Mapped[list[PostLabelCache]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_posts_created_at", "created_at"),
        Index("idx_posts_author", "author"),
    )


# posts_fts intentionally stays out of ORM metadata. SQLAlchemy would emit a
# plain CREATE TABLE statement during generic metadata.create_all() calls,
# which breaks the FTS5-only MATCH/rank behavior we need here.
FTS_CREATE_SQL = text(
    "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
    "title, subtitle, content, content='posts_cache', content_rowid='id')"
)

FTS_INSERT_SQL = text(
    "INSERT INTO posts_fts(rowid, title, subtitle, content) "
    "VALUES (:rowid, :title, :subtitle, :content)"
)

FTS_DELETE_SQL = text(
    "INSERT INTO posts_fts(posts_fts, rowid, title, subtitle, content) "
    "VALUES ('delete', :rowid, :title, :subtitle, :content)"
)
