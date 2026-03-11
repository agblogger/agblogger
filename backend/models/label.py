"""Label cache models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import CacheBase

if TYPE_CHECKING:
    from backend.models.post import PostCache


class LabelCache(CacheBase):
    """Cached label definition (regenerated from labels.toml + implicit labels)."""

    __tablename__ = "labels_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    names: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_implicit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parent_edges: Mapped[list[LabelParentCache]] = relationship(
        foreign_keys="LabelParentCache.label_id",
        back_populates="label",
        cascade="all, delete-orphan",
    )
    child_edges: Mapped[list[LabelParentCache]] = relationship(
        foreign_keys="LabelParentCache.parent_id",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    post_labels: Mapped[list[PostLabelCache]] = relationship(
        back_populates="label", cascade="all, delete-orphan"
    )


class LabelParentCache(CacheBase):
    """Parent-child relationship between labels (DAG edges)."""

    __tablename__ = "label_parents_cache"

    label_id: Mapped[str] = mapped_column(String, ForeignKey("labels_cache.id"), primary_key=True)
    parent_id: Mapped[str] = mapped_column(String, ForeignKey("labels_cache.id"), primary_key=True)

    label: Mapped[LabelCache] = relationship(foreign_keys=[label_id], back_populates="parent_edges")
    parent: Mapped[LabelCache] = relationship(
        foreign_keys=[parent_id], back_populates="child_edges"
    )

    __table_args__ = (CheckConstraint("label_id != parent_id"),)


class PostLabelCache(CacheBase):
    """Association between posts and labels."""

    __tablename__ = "post_labels_cache"

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("posts_cache.id", ondelete="CASCADE"),
        primary_key=True,
    )
    label_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("labels_cache.id"),
        primary_key=True,
    )

    post: Mapped[PostCache] = relationship(back_populates="labels")
    label: Mapped[LabelCache] = relationship(back_populates="post_labels")
