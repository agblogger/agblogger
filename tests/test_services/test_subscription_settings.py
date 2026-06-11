"""Tests for subscription settings service (Task 7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.models.base import DurableBase
from backend.services import resend_client, subscription_service

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


async def _fake_create_segment(*, api_key: str, name: str) -> str:
    return "seg_auto"


async def _fake_count_contacts(*, api_key: str, segment_id: str) -> int:
    return 5


@pytest.mark.asyncio
async def test_key_encrypted_and_never_returned(session: AsyncSession) -> None:
    await subscription_service.update_settings(
        session, secret_key=SECRET, api_key="re_secret", from_email="a@b.com"
    )
    # Stored value is ciphertext, not the plaintext key.
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_api_key_encrypted not in (None, "re_secret")
    assert subscription_service.decrypt_api_key(row, SECRET) == "re_secret"


@pytest.mark.asyncio
async def test_enable_requires_full_compliance_config(session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    # Missing controller fields -> enabling must fail.
    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(
            session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
        )
    # With everything set, enabling succeeds and a segment is auto-created.
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        from_email="a@b.com",
        from_name="Jane",
        controller_name="Jane Blog",
        controller_contact="jane@b.com",
        privacy_policy_url="https://b.com/privacy",
        postal_address="1 Main St",
    )
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.enabled is True
    assert row.resend_segment_id == "seg_auto"


@pytest.mark.asyncio
async def test_update_creates_singleton_with_id_1(session: AsyncSession) -> None:
    await subscription_service.update_settings(
        session, secret_key=SECRET, from_email="hello@example.com"
    )
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.id == 1
    assert row.enabled is False


@pytest.mark.asyncio
async def test_partial_update_preserves_other_fields(session: AsyncSession) -> None:
    await subscription_service.update_settings(
        session, secret_key=SECRET, from_email="first@example.com"
    )
    await subscription_service.update_settings(session, secret_key=SECRET, from_name="X")
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.from_email == "first@example.com"
    assert row.from_name == "X"


@pytest.mark.asyncio
async def test_explicit_none_clears_optional_field(session: AsyncSession) -> None:
    await subscription_service.update_settings(session, secret_key=SECRET, from_name="X")
    await subscription_service.update_settings(session, secret_key=SECRET, from_name=None)
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.from_name is None


@pytest.mark.asyncio
async def test_enabled_settings_reject_clearing_required_field(
    session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        from_email="a@b.com",
        controller_name="Jane Blog",
        controller_contact="jane@b.com",
        privacy_policy_url="https://b.com/privacy",
        postal_address="1 Main St",
    )

    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(
            session, secret_key=SECRET, controller_contact=""
        )

    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.enabled is True
    assert row.controller_contact == "jane@b.com"


@pytest.mark.asyncio
async def test_empty_api_key_does_not_overwrite_existing(session: AsyncSession) -> None:
    await subscription_service.update_settings(session, secret_key=SECRET, api_key="re_first")
    await subscription_service.update_settings(session, secret_key=SECRET, api_key="")
    row = await subscription_service._get_row(session)
    assert row is not None
    assert subscription_service.decrypt_api_key(row, SECRET) == "re_first"


@pytest.mark.asyncio
async def test_build_settings_response_never_contains_key(
    session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    monkeypatch.setattr(resend_client, "count_contacts", _fake_count_contacts)

    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        api_key="re_topSecret",
        from_email="news@example.com",
        from_name="Blog",
        controller_name="Blog Owner",
        controller_contact="owner@example.com",
        privacy_policy_url="https://example.com/privacy",
        postal_address="1 Main St",
        enabled=True,
    )
    response = await subscription_service.build_settings_response(session, SECRET)
    dumped = response.model_dump()
    # Key must not appear in any form in the response dict.
    for value in dumped.values():
        assert value != "re_topSecret"
        assert "api_key" not in str(value).lower()
    assert response.key_configured is True
    assert response.subscriber_count == 5


@pytest.mark.asyncio
async def test_build_settings_response_resend_error_gives_none_count(
    session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)

    async def _failing_count(*, api_key: str, segment_id: str) -> int:
        raise resend_client.ResendError("unavailable")

    monkeypatch.setattr(resend_client, "count_contacts", _failing_count)

    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        api_key="re_x",
        from_email="news@example.com",
        from_name="Blog",
        controller_name="Blog Owner",
        controller_contact="owner@example.com",
        privacy_policy_url="https://example.com/privacy",
        postal_address="1 Main St",
        enabled=True,
    )
    response = await subscription_service.build_settings_response(session, SECRET)
    assert response.subscriber_count is None


@pytest.mark.asyncio
async def test_disable_does_not_require_compliance(session: AsyncSession) -> None:
    # Only an API key is set — no compliance fields.
    await subscription_service.update_settings(session, secret_key=SECRET, api_key="re_x")
    # Disabling must succeed without raising EnablePreconditionError.
    await subscription_service.update_settings(session, secret_key=SECRET, enabled=False)
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.enabled is False


@pytest.mark.asyncio
async def test_failed_enable_persists_nothing(session: AsyncSession) -> None:
    # First-ever call with enable but missing compliance fields must roll back
    # entirely, leaving no singleton row behind.
    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(
            session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
        )
    assert await subscription_service._get_row(session) is None


@pytest.mark.asyncio
async def test_enable_resend_error_leaves_nothing_persisted(
    session: AsyncSession, monkeypatch
) -> None:
    async def _failing_create_segment(*, api_key: str, name: str) -> str:
        raise resend_client.ResendError("boom")

    monkeypatch.setattr(resend_client, "create_segment", _failing_create_segment)

    with pytest.raises(resend_client.ResendError):
        await subscription_service.update_settings(
            session,
            secret_key=SECRET,
            enabled=True,
            api_key="re_x",
            from_email="a@b.com",
            from_name="J",
            controller_name="J",
            controller_contact="j@b.com",
            privacy_policy_url="https://b/p",
            postal_address="x",
        )
    assert await subscription_service._get_row(session) is None


@pytest.mark.asyncio
async def test_enable_twice_creates_segment_once(session: AsyncSession, monkeypatch) -> None:
    calls: list[int] = []

    async def _counting_create_segment(*, api_key: str, name: str) -> str:
        calls.append(1)
        return "seg_auto"

    monkeypatch.setattr(resend_client, "create_segment", _counting_create_segment)

    full_kwargs = {
        "api_key": "re_x",
        "from_email": "a@b.com",
        "from_name": "J",
        "controller_name": "J",
        "controller_contact": "j@b.com",
        "privacy_policy_url": "https://b/p",
        "postal_address": "x",
    }
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, **full_kwargs
    )
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, **full_kwargs
    )
    # Second enable reuses the stored resend_segment_id rather than re-creating.
    assert len(calls) == 1
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_auto"
