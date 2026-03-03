"""Cross-posting models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base
from backend.schemas.crosspost import CrossPostStatus

if TYPE_CHECKING:
    from backend.models.user import User


class SocialAccount(Base):
    """Connected social media account for cross-posting."""

    __tablename__ = "social_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    credentials: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship(back_populates="social_accounts")

    __table_args__ = (UniqueConstraint("user_id", "platform", "account_name"),)


class CrossPost(Base):
    """Cross-posting history entry."""

    __tablename__ = "cross_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    post_path: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    platform_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[CrossPostStatus] = mapped_column(
        String, nullable=False, default=CrossPostStatus.PENDING
    )
    posted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="cross_posts")
