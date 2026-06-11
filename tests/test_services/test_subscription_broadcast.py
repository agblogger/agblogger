"""Tests for subscription broadcast firing and once-guard ledger (Task 9)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from backend.models.base import DurableBase
from backend.models.subscription import SubscriptionBroadcast
from backend.services import resend_client, subscription_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

SECRET = "s" * 48


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


@pytest.mark.asyncio
async def test_send_broadcast_records_sent(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads: dict[str, str] = {}

    async def fake_broadcast(**kwargs: str) -> str:
        payloads.update(kwargs)
        return "bcast_1"

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)
    await _enable(session, monkeypatch)

    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path="posts/hello/index.md",
        post_title="Hello",
        post_html="<p>b</p>",
        post_url="https://blog.example/post/hello",
        trigger="manual",
    )
    rows = (await session.execute(select(SubscriptionBroadcast))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "sent"
    assert rows[0].resend_broadcast_id == "bcast_1"
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in payloads["html"]


@pytest.mark.asyncio
async def test_resend_failure_records_failed_not_raised(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(**kwargs: str) -> str:
        raise resend_client.ResendError("nope")

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", boom)
    await _enable(session, monkeypatch)

    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path="p",
        post_title="t",
        post_html="<p>b</p>",
        post_url="u",
        trigger="auto",
    )
    rows = (await session.execute(select(SubscriptionBroadcast))).scalars().all()
    assert rows[0].status == "failed" and rows[0].error


@pytest.mark.asyncio
async def test_once_guard_blocks_second_auto_send(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_broadcast(**kwargs: str) -> str:
        return "b"

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)
    await _enable(session, monkeypatch)

    assert await subscription_service.already_broadcast(session, "posts/x/index.md") is False
    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path="posts/x/index.md",
        post_title="x",
        post_html="<p>b</p>",
        post_url="u",
        trigger="auto",
    )
    assert await subscription_service.already_broadcast(session, "posts/x/index.md") is True


@pytest.mark.asyncio
async def test_send_broadcast_unexpected_error_records_internal_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(**kwargs: str) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", boom)
    await _enable(session, monkeypatch)

    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path="posts/err/index.md",
        post_title="Err",
        post_html="<p>x</p>",
        post_url="https://blog.example/post/err",
        trigger="manual",
    )
    rows = (await session.execute(select(SubscriptionBroadcast))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error == "Internal error"
    assert "boom" not in (rows[0].error or "")


@pytest.mark.asyncio
async def test_send_broadcast_not_configured_records_failed(
    session: AsyncSession,
) -> None:
    # No _enable call — subscriptions are not configured.
    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path="posts/unconfigured/index.md",
        post_title="Unconfigured",
        post_html="<p>x</p>",
        post_url="https://blog.example/post/unconfigured",
        trigger="manual",
    )
    rows = (await session.execute(select(SubscriptionBroadcast))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error == "Subscriptions not configured"


@pytest.mark.asyncio
async def test_fire_post_broadcast_runs_in_background(
    db_session_factory: async_sessionmaker[AsyncSession],
    _create_tables: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_broadcast(**kwargs: str) -> str:
        return "bg_bcast_1"

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)

    async with db_session_factory() as s:
        await _enable(s, monkeypatch)

    scheduled = subscription_service.fire_post_broadcast(
        db_session_factory,
        secret_key=SECRET,
        post_path="posts/y/index.md",
        post_title="Y",
        post_html="<p>b</p>",
        post_url="u",
        trigger="auto",
        enforce_once_guard=True,
    )
    assert scheduled is True

    # Drain all spawned background tasks deterministically.
    tasks = list(subscription_service._broadcast_tasks)
    await asyncio.gather(*tasks)

    async with db_session_factory() as s:
        assert await subscription_service.already_broadcast(s, "posts/y/index.md") is True


@pytest.mark.asyncio
async def test_failed_attempt_does_not_block_retry(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enable(session, monkeypatch)
    post_path = "posts/retry/index.md"

    async def boom(**kwargs: str) -> str:
        raise resend_client.ResendError("nope")

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", boom)
    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path=post_path,
        post_title="Retry",
        post_html="<p>b</p>",
        post_url="u",
        trigger="auto",
    )
    # A failed attempt must NOT engage the once-guard.
    assert await subscription_service.already_broadcast(session, post_path) is False

    async def fake_broadcast(**kwargs: str) -> str:
        return "bcast_retry"

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)
    await subscription_service.send_broadcast(
        session,
        secret_key=SECRET,
        post_path=post_path,
        post_title="Retry",
        post_html="<p>b</p>",
        post_url="u",
        trigger="auto",
    )
    assert await subscription_service.already_broadcast(session, post_path) is True
    rows = (
        (
            await session.execute(
                select(SubscriptionBroadcast).where(SubscriptionBroadcast.post_path == post_path)
            )
        )
        .scalars()
        .all()
    )
    assert any(row.status == "sent" for row in rows)


@pytest.mark.asyncio
async def test_close_broadcast_tasks_drains_inflight(
    db_session_factory: async_sessionmaker[AsyncSession],
    _create_tables: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_broadcast(**kwargs: str) -> str:
        return "bg_drain_1"

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)

    async with db_session_factory() as s:
        await _enable(s, monkeypatch)

    subscription_service.fire_post_broadcast(
        db_session_factory,
        secret_key=SECRET,
        post_path="posts/drain/index.md",
        post_title="Drain",
        post_html="<p>b</p>",
        post_url="u",
        trigger="manual",
        enforce_once_guard=False,
    )

    # close_broadcast_tasks must await the in-flight task so the row commits.
    await subscription_service.close_broadcast_tasks()

    async with db_session_factory() as s:
        assert await subscription_service.already_broadcast(s, "posts/drain/index.md") is True


def test_fire_post_broadcast_reports_capacity_rejection(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subscription_service, "_MAX_BROADCAST_TASKS", 0)

    scheduled = subscription_service.fire_post_broadcast(
        db_session_factory,
        secret_key=SECRET,
        post_path="posts/rejected/index.md",
        post_title="Rejected",
        post_html="<p>b</p>",
        post_url="u",
        trigger="manual",
        enforce_once_guard=False,
    )

    assert scheduled is False


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
