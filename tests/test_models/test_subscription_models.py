"""Subscription durable models live in the main DB and store no PII."""

from __future__ import annotations

from backend.models.base import DurableBase
from backend.models.subscription import SubscriptionBroadcast, SubscriptionSettings


def test_settings_is_durable_singleton() -> None:
    assert SubscriptionSettings.__tablename__ == "subscription_settings"
    assert issubclass(SubscriptionSettings, DurableBase)
    cols = SubscriptionSettings.__table__.columns
    assert {
        "id",
        "enabled",
        "resend_api_key_encrypted",
        "resend_segment_id",
        "from_email",
        "from_name",
        "controller_name",
        "controller_contact",
        "privacy_policy_url",
        "postal_address",
        "updated_at",
    } <= set(cols.keys())
    assert "email" not in cols


def test_broadcast_ledger_has_no_recipient_columns() -> None:
    assert SubscriptionBroadcast.__tablename__ == "subscription_broadcasts"
    cols = set(SubscriptionBroadcast.__table__.columns.keys())
    assert {
        "id",
        "post_path",
        "post_title",
        "resend_broadcast_id",
        "trigger",
        "status",
        "sent_at",
        "error",
    } <= cols
    assert "email" not in cols and "recipients" not in cols
