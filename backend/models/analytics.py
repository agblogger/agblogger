"""Analytics settings model."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import DurableBase


class AnalyticsSettings(DurableBase):
    """Singleton row storing analytics configuration."""

    __tablename__ = "analytics_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_analytics_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_views_on_posts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
