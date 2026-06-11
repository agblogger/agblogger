"""Tests for subscription_service.handle_resend_webhook."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import TYPE_CHECKING

import pytest

from backend.models.base import DurableBase
from backend.services import resend_client, subscription_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SECRET = "s" * 48
_WEBHOOK_SECRET_BYTES = b"w" * 32
_WEBHOOK_SECRET = "whsec_" + base64.b64encode(_WEBHOOK_SECRET_BYTES).decode()


def _svix_headers(payload: bytes, msg_id: str = "msg_test_1") -> dict[str, str]:
    """Generate svix-compatible signature headers with a current timestamp."""
    ts = str(int(time.time()))
    to_sign = f"{msg_id}.{ts}.".encode() + payload
    sig = base64.b64encode(
        hmac.new(_WEBHOOK_SECRET_BYTES, to_sign, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": ts,
        "svix-signature": f"v1,{sig}",
    }


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


async def _configure_webhook_secret(session: AsyncSession) -> None:
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        api_key="re_test",
        webhook_secret=_WEBHOOK_SECRET,
    )


@pytest.mark.asyncio
async def test_handle_webhook_deletes_contact_on_unsubscribed(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[dict[str, str]] = []

    async def fake_delete(*, api_key: str, audience_id: str, contact_id: str) -> None:
        deleted.append({"audience_id": audience_id, "contact_id": contact_id})

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)
    await _configure_webhook_secret(session)

    payload = json.dumps(
        {
            "type": "contact.unsubscribed",
            "data": {
                "audience_id": "aud_abc",
                "contact": {"id": "contact_xyz", "email": "user@example.com"},
            },
        }
    ).encode()

    await subscription_service.handle_resend_webhook(
        session,
        raw_body=payload,
        headers=_svix_headers(payload),
        secret_key=SECRET,
    )
    assert len(deleted) == 1
    assert deleted[0]["audience_id"] == "aud_abc"
    assert deleted[0]["contact_id"] == "contact_xyz"


@pytest.mark.asyncio
async def test_handle_webhook_ignores_unknown_event_type(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[object] = []

    async def fake_delete(**kwargs: object) -> None:
        deleted.append(kwargs)

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)
    await _configure_webhook_secret(session)

    payload = json.dumps({"type": "email.delivered", "data": {}}).encode()

    await subscription_service.handle_resend_webhook(
        session,
        raw_body=payload,
        headers=_svix_headers(payload),
        secret_key=SECRET,
    )
    assert deleted == []


@pytest.mark.asyncio
async def test_handle_webhook_no_secret_configured_requests_retry(
    session: AsyncSession,
) -> None:
    with pytest.raises(subscription_service.WebhookProcessingError):
        await subscription_service.handle_resend_webhook(
            session,
            raw_body=b"{}",
            headers={},
            secret_key=SECRET,
        )


@pytest.mark.asyncio
async def test_handle_webhook_resend_error_raises_for_provider_retry(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_delete(**kwargs: object) -> None:
        raise resend_client.ResendError("network failure")

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)
    await _configure_webhook_secret(session)

    payload = json.dumps(
        {
            "type": "contact.unsubscribed",
            "data": {
                "audience_id": "aud_abc",
                "contact": {"id": "contact_xyz"},
            },
        }
    ).encode()

    with pytest.raises(resend_client.ResendError, match="network failure"):
        await subscription_service.handle_resend_webhook(
            session,
            raw_body=payload,
            headers=_svix_headers(payload),
            secret_key=SECRET,
        )


@pytest.mark.asyncio
async def test_handle_webhook_missing_contact_id_requests_retry(
    session: AsyncSession,
) -> None:
    await _configure_webhook_secret(session)

    payload = json.dumps(
        {
            "type": "contact.unsubscribed",
            "data": {"audience_id": "aud_abc", "contact": {}},
        }
    ).encode()

    with pytest.raises(subscription_service.WebhookProcessingError):
        await subscription_service.handle_resend_webhook(
            session,
            raw_body=payload,
            headers=_svix_headers(payload),
            secret_key=SECRET,
        )


@pytest.mark.asyncio
async def test_handle_webhook_bad_signature_raises_verification_error(
    session: AsyncSession,
) -> None:
    from svix.webhooks import WebhookVerificationError

    await _configure_webhook_secret(session)

    payload = b'{"type": "contact.unsubscribed"}'
    bad_headers = {
        "svix-id": "msg_test",
        "svix-timestamp": str(int(time.time())),
        "svix-signature": "v1,badsignature==",
    }

    with pytest.raises(WebhookVerificationError):
        await subscription_service.handle_resend_webhook(
            session,
            raw_body=payload,
            headers=bad_headers,
            secret_key=SECRET,
        )
