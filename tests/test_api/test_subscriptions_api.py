"""Integration tests for the subscription API endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
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
    """Create settings for subscription API tests."""
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
    """Enable subscriptions in the app's DB via the service layer.

    Writes to the same session factory the app uses, so the app sees the change.
    """
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
            from_email="blog@example.com",
            from_name="Test Blog",
            controller_name="Test Controller",
            controller_contact="privacy@example.com",
            privacy_policy_url="https://example.com/privacy",
            postal_address="123 Test St, Test City",
        )


@pytest.mark.asyncio
async def test_subscribe_rejected_when_disabled(client: AsyncClient) -> None:
    resp = await client.post("/api/subscribe", json={"email": "r@x.com"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subscribe_generic_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_subscriptions: None
) -> None:
    async def fake_send(**kwargs: str) -> str:
        return "e1"

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    resp = await client.post("/api/subscribe", json={"email": "r@x.com"})
    assert resp.status_code == 200
    assert "confirm" in resp.json()["message"].lower()


@pytest.mark.asyncio
async def test_subscribe_bad_email_422(client: AsyncClient, enable_subscriptions: None) -> None:
    resp = await client.post("/api/subscribe", json={"email": "nope"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_settings_never_returns_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_segment(**kwargs: str) -> str:
        return "seg_auto"

    monkeypatch.setattr(resend_client, "create_segment", fake_segment)
    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.put(
        "/api/admin/subscriptions/settings",
        json={"api_key": "re_secret"},
        headers=headers,
    )
    resp = await client.get("/api/admin/subscriptions/settings", headers=headers)
    body = resp.json()
    assert body["key_configured"] is True
    assert "re_secret" not in resp.text
    assert "api_key" not in body


@pytest.mark.asyncio
async def test_subscribe_rate_limited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_subscriptions: None
) -> None:
    """4th subscribe from the same IP within a minute should return 429 with Retry-After."""

    async def fake_send(**kwargs: str) -> str:
        return "email_id"

    monkeypatch.setattr(resend_client, "send_email", fake_send)

    # First 3 should succeed (burst limit is 3/minute)
    for i in range(3):
        resp = await client.post("/api/subscribe", json={"email": f"user{i}@x.com"})
        assert resp.status_code == 200, f"Request {i + 1} failed unexpectedly: {resp.status_code}"

    # 4th should be rate-limited
    resp = await client.post("/api/subscribe", json={"email": "user99@x.com"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/subscriptions/settings"),
        ("PUT", "/api/admin/subscriptions/settings"),
        ("POST", "/api/admin/subscriptions/test"),
        ("GET", "/api/admin/subscriptions/broadcasts"),
        ("POST", "/api/admin/subscriptions/broadcasts"),
    ],
)
async def test_admin_endpoints_require_auth(client: AsyncClient, method: str, path: str) -> None:
    """Unauthenticated access to every admin subscription endpoint returns 401/403."""
    resp = await client.request(method, path, json={})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_confirm_page_renders_for_bad_token(client: AsyncClient) -> None:
    """GET /subscribe/confirm?token=bad returns 400 and an HTML body with error message."""
    resp = await client.get("/subscribe/confirm?token=bad")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_confirm_page_success(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
    app_settings: Settings,
) -> None:
    """A valid confirmation token renders the success page (200) and creates the contact."""
    from backend.services.subscription_tokens import create_confirm_token

    async def fake_create_contact(**kwargs: str) -> None:
        return None

    monkeypatch.setattr(resend_client, "create_contact", fake_create_contact)

    token = create_confirm_token("r@x.com", app_settings.secret_key)
    resp = await client.get(f"/subscribe/confirm?token={token}")
    assert resp.status_code == 200
    assert "subscribed" in resp.text.lower()


@pytest.mark.asyncio
async def test_put_settings_precondition_returns_400(client: AsyncClient) -> None:
    """Enabling without from_email returns 400 (EnablePreconditionError)."""
    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        "/api/admin/subscriptions/settings",
        json={"enabled": True, "api_key": "re_x"},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_settings_explicit_null_clears_optional_field(client: AsyncClient) -> None:
    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    first = await client.put(
        "/api/admin/subscriptions/settings",
        json={"from_name": "Blog"},
        headers=headers,
    )
    assert first.status_code == 200

    cleared = await client.put(
        "/api/admin/subscriptions/settings",
        json={"from_name": None},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["from_name"] is None


@pytest.mark.asyncio
async def test_trigger_broadcast_404_for_missing_post(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_subscriptions: None
) -> None:
    """POST /api/admin/subscriptions/broadcasts with non-existent post_path → 404."""
    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/admin/subscriptions/broadcasts",
        json={"post_path": "posts/nonexistent-post/index.md"},
        headers=headers,
    )
    assert resp.status_code == 404


async def _seed_published_post(client: AsyncClient, file_path: str) -> None:
    """Insert a minimal published PostCache row into the app's DB."""
    from backend.models.post import PostCache
    from backend.utils.datetime import now_utc

    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None, "Test client must use ASGITransport"
    session_factory = app.state.session_factory
    now = now_utc()
    async with session_factory() as session:
        session.add(
            PostCache(
                file_path=file_path,
                title="Published Post",
                created_at=now,
                modified_at=now,
                is_draft=False,
                content_hash="0" * 64,
                rendered_html="<p>Body</p>",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_trigger_broadcast_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_subscriptions: None
) -> None:
    """A valid published post triggers a manual broadcast (202) without the once-guard."""
    calls: list[dict[str, object]] = []

    def fake_fire(*args: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    file_path = "posts/published-post/index.md"
    await _seed_published_post(client, file_path)

    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/admin/subscriptions/broadcasts",
        json={"post_path": file_path},
        headers=headers,
    )
    assert resp.status_code == 202
    assert "message" in resp.json()
    assert len(calls) == 1
    recorded = calls[0]
    assert recorded["trigger"] == "manual"
    assert recorded["enforce_once_guard"] is False
    assert recorded["post_path"] == file_path


_WEBHOOK_SECRET_BYTES = b"w" * 32
_TEST_WEBHOOK_SECRET = "whsec_" + base64.b64encode(_WEBHOOK_SECRET_BYTES).decode()


def _svix_headers(payload: bytes, msg_id: str = "msg_test_api") -> dict[str, str]:
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
async def enable_webhook_secret(client: AsyncClient) -> None:
    """Configure the webhook secret via the app's session factory."""
    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None
    session_factory = app.state.session_factory
    secret_key: str = app.state.settings.secret_key
    async with session_factory() as session:
        await subscription_service.update_settings(
            session,
            secret_key=secret_key,
            webhook_secret=_TEST_WEBHOOK_SECRET,
        )


@pytest.mark.asyncio
async def test_webhook_valid_signature_returns_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    async def fake_delete(*, api_key: str, audience_id: str, contact_id: str) -> None:
        pass

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {
            "type": "contact.unsubscribed",
            "data": {"audience_id": "aud_1", "contact": {"id": "c1"}},
        }
    ).encode()
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_bad_signature_returns_400(
    client: AsyncClient,
    enable_webhook_secret: None,
) -> None:
    payload = b'{"type": "contact.unsubscribed", "data": {}}'
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={
            "svix-id": "msg_test",
            "svix-timestamp": str(int(time.time())),
            "svix-signature": "v1,invalidsig==",
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_no_secret_configured_returns_200(client: AsyncClient) -> None:
    # No webhook secret set — endpoint returns 200 and does nothing.
    payload = b'{"type": "contact.unsubscribed", "data": {}}'
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_resend_api_failure_still_returns_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    async def fake_delete(*, api_key: str, audience_id: str, contact_id: str) -> None:
        raise resend_client.ResendError("network down")

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {
            "type": "contact.unsubscribed",
            "data": {"audience_id": "aud_1", "contact": {"id": "c1"}},
        }
    ).encode()
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_unknown_event_type_returns_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    delete_calls: list[str] = []

    async def fake_delete(*, api_key: str, audience_id: str, contact_id: str) -> None:
        delete_calls.append(contact_id)

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {"type": "contact.created", "data": {"audience_id": "aud_1", "contact": {"id": "c1"}}}
    ).encode()
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert delete_calls == []


@pytest.mark.asyncio
async def test_webhook_missing_contact_id_returns_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    delete_calls: list[str] = []

    async def fake_delete(*, api_key: str, audience_id: str, contact_id: str) -> None:
        delete_calls.append(contact_id)

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {"type": "contact.unsubscribed", "data": {"audience_id": "aud_1", "contact": {}}}
    ).encode()
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert delete_calls == []
