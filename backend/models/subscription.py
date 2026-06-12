"""Subscription config + broadcast ledger (durable, no subscriber PII)."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.crypto_types import Ciphertext
from backend.models.base import DurableBase
from backend.schemas.subscription import BroadcastStatus, BroadcastTrigger


class SubscriptionSettings(DurableBase):
    """Singleton row holding subscription configuration. Stores no subscriber data."""

    __tablename__ = "subscription_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_subscription_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resend_api_key_encrypted: Mapped[Ciphertext | None] = mapped_column(Text, nullable=True)
    resend_webhook_secret_encrypted: Mapped[Ciphertext | None] = mapped_column(Text, nullable=True)
    resend_segment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    from_email: Mapped[str | None] = mapped_column(String, nullable=True)
    from_name: Mapped[str | None] = mapped_column(String, nullable=True)
    controller_name: Mapped[str | None] = mapped_column(String, nullable=True)
    controller_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    privacy_policy_url: Mapped[str | None] = mapped_column(String, nullable=True)
    postal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SubscriptionBroadcast(DurableBase):
    """One row per broadcast attempt. References a Resend broadcast, not recipients."""

    __tablename__ = "subscription_broadcasts"
    # CheckConstraints kept as defense-in-depth; Python types are BroadcastStatus/BroadcastTrigger.
    __table_args__ = (
        CheckConstraint("trigger IN ('auto', 'manual')", name="ck_subscription_broadcasts_trigger"),
        CheckConstraint("status IN ('sent', 'failed')", name="ck_subscription_broadcasts_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )
    post_path: Mapped[str] = mapped_column(Text, nullable=False)
    post_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resend_broadcast_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger: Mapped[BroadcastTrigger] = mapped_column(String, nullable=False)
    status: Mapped[BroadcastStatus] = mapped_column(String, nullable=False)
    sent_at: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
