"""Request/response schemas for subscriptions. No schema ever exposes the API key."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, model_validator


class SubscribeRequest(BaseModel):
    email: EmailStr


class SubscribeResponse(BaseModel):
    # Identical message in every case (no enumeration).
    message: str = "Please check your inbox to confirm your subscription."


class SubscriptionSettingsResponse(BaseModel):
    """Admin view. key_configured is a bool; the key itself is never returned."""

    enabled: bool
    from_email: str | None
    from_name: str | None
    controller_name: str | None
    controller_contact: str | None
    privacy_policy_url: str | None
    postal_address: str | None
    key_configured: bool
    webhook_secret_configured: bool
    segment_configured: bool
    subscriber_count: int | None  # None when Resend is unreachable


class SubscriptionSettingsUpdate(BaseModel):
    enabled: bool | None = None
    api_key: str | None = None  # write-only
    webhook_secret: str | None = None  # write-only
    from_email: str | None = None
    from_name: str | None = None
    controller_name: str | None = None
    controller_contact: str | None = None
    privacy_policy_url: str | None = None
    postal_address: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> SubscriptionSettingsUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class SendTestEmailRequest(BaseModel):
    email: EmailStr


class BroadcastSummary(BaseModel):
    """One broadcast attempt as shown to the admin (no recipient data)."""

    id: int
    post_path: str
    post_title: str
    resend_broadcast_id: str | None
    trigger: str
    status: str
    sent_at: str
    error: str | None


class BroadcastListResponse(BaseModel):
    broadcasts: list[BroadcastSummary]


class TriggerBroadcastRequest(BaseModel):
    post_path: str = Field(min_length=1, max_length=400)
