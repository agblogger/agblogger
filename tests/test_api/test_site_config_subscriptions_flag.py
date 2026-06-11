"""Tests for subscriptions_enabled flag in the public site config API."""

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
    """Create settings for site config subscriptions flag tests."""
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


@pytest.mark.asyncio
async def test_site_config_reports_subscriptions_disabled_by_default(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/pages")
    assert resp.status_code == 200
    assert resp.json()["subscriptions_enabled"] is False


@pytest.mark.asyncio
async def test_site_config_reports_enabled_with_full_compliance(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None, "Test client must use ASGITransport"
    session_factory = app.state.session_factory
    secret_key: str = app.state.settings.secret_key

    async def fake_segment(**kwargs: str) -> str:
        return "seg_auto"

    monkeypatch.setattr(resend_client, "create_segment", fake_segment)

    async with session_factory() as session:
        await subscription_service.update_settings(
            session,
            secret_key=secret_key,
            enabled=True,
            api_key="re_x",
            webhook_secret="whsec_test",
            from_email="a@b.com",
            controller_name="J",
            controller_contact="j@b.com",
            privacy_policy_url="https://b/p",
        )

    resp = await client.get("/api/pages")
    assert resp.json()["subscriptions_enabled"] is True
    assert resp.json()["subscription_compliance"] == {
        "controller_name": "J",
        "controller_contact": "j@b.com",
        "privacy_policy_url": "https://b/p",
    }


@pytest.mark.asyncio
async def test_site_config_reports_enabled_with_partial_compliance(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subscriptions can be enabled without compliance fields; partial fields are exposed."""
    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None, "Test client must use ASGITransport"
    session_factory = app.state.session_factory
    secret_key: str = app.state.settings.secret_key

    async def fake_segment(**kwargs: str) -> str:
        return "seg_auto"

    monkeypatch.setattr(resend_client, "create_segment", fake_segment)

    async with session_factory() as session:
        await subscription_service.update_settings(
            session,
            secret_key=secret_key,
            enabled=True,
            api_key="re_x",
            webhook_secret="whsec_test",
            from_email="a@b.com",
        )

    resp = await client.get("/api/pages")
    assert resp.json()["subscriptions_enabled"] is True
    compliance = resp.json()["subscription_compliance"]
    assert compliance["controller_name"] is None
    assert compliance["controller_contact"] is None
    assert compliance["privacy_policy_url"] is None
