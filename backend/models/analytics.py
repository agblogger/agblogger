"""Analytics settings model."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import DurableBase


class AnalyticsSettings(DurableBase):
    """Singleton row storing analytics configuration."""

    __tablename__ = "analytics_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_views_on_posts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
