"""Tests for subscription settings service (Task 7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.models.base import DurableBase
from backend.services import resend_client, subscription_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SECRET = "s" * 48
WEBHOOK_SECRET = "whsec_test"


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
async def test_enable_requires_key_from_email_and_webhook_secret(
    session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    # Missing from_email -> enabling must fail.
    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(
            session, secret_key=SECRET, enabled=True, api_key="re_x"
        )
    with pytest.raises(subscription_service.EnablePreconditionError, match="webhook"):
        await subscription_service.update_settings(
            session,
            secret_key=SECRET,
            enabled=True,
            api_key="re_x",
            from_email="a@b.com",
        )
    # Compliance fields remain optional once deletion webhook handling is configured.
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret="whsec_test",
        from_email="a@b.com",
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
async def test_enabled_settings_reject_clearing_from_email(
    session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )

    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(session, secret_key=SECRET, from_email="")

    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.enabled is True
    assert row.from_email == "a@b.com"


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
        webhook_secret=WEBHOOK_SECRET,
        from_email="news@example.com",
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
        webhook_secret=WEBHOOK_SECRET,
        from_email="news@example.com",
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
    # First-ever call with enable but missing from_email must roll back entirely.
    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(
            session, secret_key=SECRET, enabled=True, api_key="re_x"
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
            webhook_secret=WEBHOOK_SECRET,
            from_email="a@b.com",
        )
    assert await subscription_service._get_row(session) is None


@pytest.mark.asyncio
async def test_enable_twice_creates_segment_once(session: AsyncSession, monkeypatch) -> None:
    calls: list[int] = []

    async def _counting_create_segment(*, api_key: str, name: str) -> str:
        calls.append(1)
        return "seg_auto"

    async def _fake_check_segment_exists(*, api_key: str, segment_id: str) -> bool:
        return True

    monkeypatch.setattr(resend_client, "create_segment", _counting_create_segment)
    monkeypatch.setattr(resend_client, "check_segment_exists", _fake_check_segment_exists)

    full_kwargs = {
        "api_key": "re_x",
        "webhook_secret": WEBHOOK_SECRET,
        "from_email": "a@b.com",
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


@pytest.mark.asyncio
async def test_enable_with_valid_segment_does_not_recreate(
    session: AsyncSession, monkeypatch
) -> None:
    create_calls: list[int] = []

    async def _counting_create(*, api_key: str, name: str) -> str:
        create_calls.append(1)
        return "seg_original"

    async def _exists_true(*, api_key: str, segment_id: str) -> bool:
        assert segment_id == "seg_original"
        return True

    monkeypatch.setattr(resend_client, "create_segment", _counting_create)
    monkeypatch.setattr(resend_client, "check_segment_exists", _exists_true)

    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )
    # Enable a second time — segment still exists, no re-creation.
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )
    assert len(create_calls) == 1
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_original"


@pytest.mark.asyncio
async def test_enable_with_stale_segment_recreates(session: AsyncSession, monkeypatch) -> None:
    create_calls: list[str] = []

    async def _counting_create(*, api_key: str, name: str) -> str:
        seg_id = f"seg_{len(create_calls) + 1}"
        create_calls.append(seg_id)
        return seg_id

    async def _exists_false(*, api_key: str, segment_id: str) -> bool:
        return False

    monkeypatch.setattr(resend_client, "create_segment", _counting_create)
    monkeypatch.setattr(resend_client, "check_segment_exists", _exists_false)

    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )
    # Enable again — segment probe says it's gone, so a new one is created.
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )
    assert len(create_calls) == 2
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_2"


@pytest.mark.asyncio
async def test_check_segment_exists_error_during_reenable_propagates(
    session: AsyncSession, monkeypatch
) -> None:
    async def _create_segment(*, api_key: str, name: str) -> str:
        return "seg_original"

    async def _check_raises(*, api_key: str, segment_id: str) -> bool:
        raise resend_client.ResendError("auth failure")

    monkeypatch.setattr(resend_client, "create_segment", _create_segment)
    monkeypatch.setattr(resend_client, "check_segment_exists", _check_raises)

    # First enable — no segment stored yet, check_segment_exists not called.
    # Temporarily use a passing check for the first enable.
    async def _check_ok(*, api_key: str, segment_id: str) -> bool:
        return True

    monkeypatch.setattr(resend_client, "check_segment_exists", _check_ok)
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )

    # Second enable — segment is stored, check_segment_exists raises.
    monkeypatch.setattr(resend_client, "check_segment_exists", _check_raises)
    with pytest.raises(resend_client.ResendError, match="auth failure"):
        await subscription_service.update_settings(
            session,
            secret_key=SECRET,
            enabled=True,
            api_key="re_x",
            webhook_secret=WEBHOOK_SECRET,
            from_email="a@b.com",
        )

    # Row should still be enabled with the original segment (rollback preserved state).
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.enabled is True
    assert row.resend_segment_id == "seg_original"


@pytest.mark.asyncio
async def test_first_enable_does_not_call_check_segment_exists(
    session: AsyncSession, monkeypatch
) -> None:
    async def _check_raises(*, api_key: str, segment_id: str) -> bool:
        raise resend_client.ResendError("should not be called on first enable")

    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    monkeypatch.setattr(resend_client, "check_segment_exists", _check_raises)

    # First enable with no stored segment — check_segment_exists must not be invoked.
    await subscription_service.update_settings(
        session,
        secret_key=SECRET,
        enabled=True,
        api_key="re_x",
        webhook_secret=WEBHOOK_SECRET,
        from_email="a@b.com",
    )
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_auto"


@pytest.mark.asyncio
async def test_webhook_secret_encrypted_and_flag_set(session: AsyncSession) -> None:
    from backend.services.crypto_service import decrypt_value

    await subscription_service.update_settings(
        session, secret_key=SECRET, webhook_secret="whsec_test123"
    )
    row = await subscription_service._get_row(session)
    assert row is not None
    encrypted = row.resend_webhook_secret_encrypted
    assert encrypted is not None
    assert encrypted != "whsec_test123"
    assert decrypt_value(encrypted, SECRET) == "whsec_test123"


@pytest.mark.asyncio
async def test_webhook_secret_configured_flag_in_response(session: AsyncSession) -> None:
    response = await subscription_service.build_settings_response(session, SECRET)
    assert response.webhook_secret_configured is False

    await subscription_service.update_settings(
        session, secret_key=SECRET, webhook_secret="whsec_test"
    )
    response = await subscription_service.build_settings_response(session, SECRET)
    assert response.webhook_secret_configured is True
