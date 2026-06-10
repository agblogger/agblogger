from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.subscription import (
    SendTestEmailRequest,
    SubscribeRequest,
    SubscriptionSettingsResponse,
    SubscriptionSettingsUpdate,
    TriggerBroadcastRequest,
)


def test_subscribe_request_validates_email() -> None:
    assert SubscribeRequest(email="a@b.com").email == "a@b.com"
    with pytest.raises(ValidationError):
        SubscribeRequest(email="not-an-email")


def test_settings_update_requires_a_field() -> None:
    with pytest.raises(ValidationError):
        SubscriptionSettingsUpdate()  # all-None must be rejected
    # api_key is accepted and is write-only (no response schema exposes it).
    SubscriptionSettingsUpdate(api_key="re_123")


def test_response_schema_never_exposes_api_key() -> None:
    """Invariant: SubscriptionSettingsResponse must never carry the API key."""
    assert "api_key" not in SubscriptionSettingsResponse.model_fields
    assert "resend_api_key_encrypted" not in SubscriptionSettingsResponse.model_fields


def test_trigger_broadcast_request_validates_post_path() -> None:
    assert TriggerBroadcastRequest(post_path="posts/hello/index.md").post_path == (
        "posts/hello/index.md"
    )
    with pytest.raises(ValidationError):
        TriggerBroadcastRequest(post_path="")
    with pytest.raises(ValidationError):
        TriggerBroadcastRequest(post_path="x" * 401)


def test_send_test_email_request_validates_email() -> None:
    assert SendTestEmailRequest(email="a@b.com").email == "a@b.com"
    with pytest.raises(ValidationError):
        SendTestEmailRequest(email="nope")
