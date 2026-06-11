"""Tests for subscription subscribe + confirm flows (Task 8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.models.base import DurableBase
from backend.services import resend_client, subscription_service
from backend.services.subscription_tokens import create_confirm_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SECRET = "s" * 48


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


@pytest.mark.asyncio
async def test_subscribe_sends_confirmation_and_stores_nothing(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, object] = {}

    async def fake_send(**kwargs: str) -> str:
        sent.update(kwargs)
        return "email_1"

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    await _enable(session, monkeypatch)

    await subscription_service.subscribe(
        session, secret_key=SECRET, email="r@x.com", base_url="https://blog.example"
    )
    assert sent["to"] == "r@x.com"
    assert "subscribe/confirm?token=" in str(sent["html"])
    # Store-zero-PII guarantee: subscribe only reads the settings row, so the
    # session has no pending inserts or modifications afterward.
    assert len(session.new) == 0
    assert len(session.dirty) == 0


@pytest.mark.asyncio
async def test_confirm_creates_contact(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: dict[str, object] = {}

    async def fake_create(**kwargs: str) -> None:
        created.update(kwargs)

    monkeypatch.setattr(resend_client, "create_contact", fake_create)
    await _enable(session, monkeypatch)

    token = create_confirm_token("r@x.com", SECRET)
    ok = await subscription_service.confirm(session, secret_key=SECRET, token=token)
    assert ok is True
    assert created["email"] == "r@x.com"
    assert created["segment_id"] == "seg_auto"


@pytest.mark.asyncio
async def test_confirm_rejects_bad_token(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enable(session, monkeypatch)
    assert await subscription_service.confirm(session, secret_key=SECRET, token="bad") is False


@pytest.mark.asyncio
async def test_subscribe_raises_when_disabled(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without calling _enable, subscriptions are not set up — must raise.
    with pytest.raises(subscription_service.SubscriptionsDisabledError):
        await subscription_service.subscribe(
            session, secret_key=SECRET, email="r@x.com", base_url="https://blog.example"
        )


@pytest.mark.asyncio
async def test_confirm_returns_false_when_disabled(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A valid token but subscriptions not enabled -> False.
    token = create_confirm_token("r@x.com", SECRET)
    result = await subscription_service.confirm(session, secret_key=SECRET, token=token)
    assert result is False


@pytest.mark.asyncio
async def test_subscribe_normalizes_recipient(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, object] = {}

    async def fake_send(**kwargs: str) -> str:
        sent.update(kwargs)
        return "email_1"

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    await _enable(session, monkeypatch)

    await subscription_service.subscribe(
        session, secret_key=SECRET, email="  Reader@X.com ", base_url="https://blog.example"
    )
    assert sent["to"] == "reader@x.com"
    assert "Jane Blog" in str(sent["subject"])


@pytest.mark.asyncio
async def test_confirm_is_idempotent(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create(**kwargs: str) -> None:
        pass

    monkeypatch.setattr(resend_client, "create_contact", fake_create)
    await _enable(session, monkeypatch)

    token = create_confirm_token("r@x.com", SECRET)
    first = await subscription_service.confirm(session, secret_key=SECRET, token=token)
    second = await subscription_service.confirm(session, secret_key=SECRET, token=token)
    assert first is True
    assert second is True


@pytest.mark.asyncio
async def test_subscribe_propagates_resend_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_send(**kwargs: str) -> str:
        raise resend_client.ResendError("quota")

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    await _enable(session, monkeypatch)

    # The reliability contract Task 10 depends on: provider errors propagate
    # (Task 10 maps ResendError to a 503) rather than being swallowed here.
    with pytest.raises(resend_client.ResendError):
        await subscription_service.subscribe(
            session, secret_key=SECRET, email="r@x.com", base_url="https://blog.example"
        )


async def _enable(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_segment(**kwargs: str) -> str:
        return "seg_auto"

    monkeypatch.setattr(resend_client, "create_segment", fake_segment)
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret="whsec_test",
        from_email="a@b.com",
        from_name="Jane",
        controller_name="Jane Blog",
        controller_contact="jane@b.com",
        privacy_policy_url="https://b.com/privacy",
        postal_address="1 Main St",
    )
