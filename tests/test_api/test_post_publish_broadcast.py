"""Tests for auto-broadcast fired on draft→published transition and direct publish."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from backend.services import resend_client, subscription_service
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for post broadcast tests."""
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create test HTTP client with fully initialized app."""
    async with create_test_client(app_settings) as ac:
        yield ac


async def _get_admin_token(client: AsyncClient) -> str:
    """Obtain a valid admin Bearer token."""
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def enable_subscriptions(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable subscriptions in the app's DB via the service layer."""
    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None, "Test client must use ASGITransport"
    session_factory = app.state.session_factory
    secret_key: str = app.state.settings.secret_key

    async def fake_create_segment(**kwargs: str) -> str:
        return "seg_test_id"

    monkeypatch.setattr(resend_client, "create_segment", fake_create_segment)

    async with session_factory() as session:
        await subscription_service.update_settings(
            session,
            secret_key=secret_key,
            enabled=True,
            api_key="re_test_key",
            webhook_secret="whsec_test",
            from_email="blog@example.com",
            from_name="Test Blog",
            controller_name="Test Controller",
            controller_contact="privacy@example.com",
            privacy_policy_url="https://example.com/privacy",
            postal_address="123 Test St, Test City",
        )


def _draft_post(title: str) -> dict[str, object]:
    return {"title": title, "subtitle": "", "body": "# Hi", "labels": [], "is_draft": True}


def _published_post(title: str) -> dict[str, object]:
    return {"title": title, "subtitle": "", "body": "# Hi", "labels": [], "is_draft": False}


@pytest.mark.asyncio
async def test_publishing_post_fires_auto_broadcast(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """Draft → published transition triggers one auto-broadcast with correct params."""
    calls: list[dict[str, object]] = []

    def fake_fire(session_factory: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/posts",
        json=_draft_post("Hello Broadcast"),
        headers=headers,
    )
    assert created.status_code == 201
    path = created.json()["file_path"]

    publish_resp = await client.put(
        f"/api/posts/{path}",
        json=_published_post("Hello Broadcast"),
        headers=headers,
    )
    # The optional broadcast hook must not corrupt the publish response.
    assert publish_resp.status_code == 200

    assert len(calls) == 1
    call = calls[0]
    assert call["trigger"] == "auto"
    assert call["enforce_once_guard"] is True
    assert call["post_path"] == path
    assert call["post_title"] == "Hello Broadcast"


@pytest.mark.asyncio
async def test_publishing_does_not_fire_when_disabled(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When subscriptions are not enabled, no broadcast is fired on publish."""
    calls: list[dict[str, object]] = []

    def fake_fire(session_factory: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/posts",
        json=_draft_post("Disabled Test"),
        headers=headers,
    )
    assert created.status_code == 201
    path = created.json()["file_path"]

    await client.put(
        f"/api/posts/{path}",
        json=_published_post("Disabled Test"),
        headers=headers,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_saving_draft_does_not_fire(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """Saving a draft (is_draft stays True) does not fire a broadcast."""
    calls: list[dict[str, object]] = []

    def fake_fire(session_factory: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/posts",
        json=_draft_post("Draft Save"),
        headers=headers,
    )
    assert created.status_code == 201
    path = created.json()["file_path"]

    await client.put(
        f"/api/posts/{path}",
        json=_draft_post("Draft Save Updated"),
        headers=headers,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_updating_published_post_does_not_refire(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """Updating an already-published post (no transition) does not fire another broadcast."""
    calls: list[dict[str, object]] = []

    def fake_fire(session_factory: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/posts",
        json=_draft_post("Published Post"),
        headers=headers,
    )
    assert created.status_code == 201
    path = created.json()["file_path"]

    # First update: publish — fires once
    await client.put(
        f"/api/posts/{path}",
        json=_published_post("Published Post"),
        headers=headers,
    )
    assert len(calls) == 1

    calls.clear()

    # Second update: edit while published — must NOT fire again
    edited = {
        "title": "Published Post Edited",
        "subtitle": "",
        "body": "# Hello Edited",
        "labels": [],
        "is_draft": False,
    }
    await client.put(f"/api/posts/{path}", json=edited, headers=headers)
    assert calls == []


@pytest.mark.asyncio
async def test_creating_published_post_fires(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """Creating a post directly as published (is_draft=False) fires the broadcast."""
    calls: list[dict[str, object]] = []

    def fake_fire(session_factory: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/posts",
        json=_published_post("Direct Publish"),
        headers=headers,
    )
    # The optional broadcast hook must not corrupt the create response.
    assert created.status_code == 201

    assert len(calls) == 1
    call = calls[0]
    assert call["trigger"] == "auto"
    assert call["enforce_once_guard"] is True
    assert call["post_title"] == "Direct Publish"
