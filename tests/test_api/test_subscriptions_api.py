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
            webhook_secret="whsec_test",
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
async def test_enabling_subscriptions_automatically_registers_webhook(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    webhook_calls: list[dict[str, object]] = []

    async def fake_create_segment(**kwargs: str) -> str:
        return "seg_auto"

    async def fake_create_webhook(*, api_key: str, endpoint: str, events: list[str]) -> str:
        webhook_calls.append({"api_key": api_key, "endpoint": endpoint, "events": events})
        return "whsec_generated"

    async def fake_count_contacts(**kwargs: str) -> int:
        return 0

    monkeypatch.setattr(resend_client, "create_segment", fake_create_segment)
    monkeypatch.setattr(resend_client, "create_webhook", fake_create_webhook)
    monkeypatch.setattr(resend_client, "count_contacts", fake_count_contacts)
    token = await _get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        "https://test/api/admin/subscriptions/settings",
        json={"enabled": True, "api_key": "re_x", "from_email": "blog@example.com"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json()["webhook_secret_configured"] is True
    assert webhook_calls == [
        {
            "api_key": "re_x",
            "endpoint": "https://test/api/webhooks/resend",
            "events": ["contact.updated"],
        }
    ]


@pytest.mark.asyncio
async def test_localhost_webhook_failure_does_not_block_enabling(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create_segment(**kwargs: str) -> str:
        return "seg_auto"

    async def failing_create_webhook(**kwargs: object) -> str:
        raise resend_client.ResendError("Endpoint URL scheme must be https")

    async def fake_count_contacts(**kwargs: str) -> int:
        return 0

    monkeypatch.setattr(resend_client, "create_segment", fake_create_segment)
    monkeypatch.setattr(resend_client, "create_webhook", failing_create_webhook)
    monkeypatch.setattr(resend_client, "count_contacts", fake_count_contacts)
    token = await _get_admin_token(client)

    resp = await client.put(
        "/api/admin/subscriptions/settings",
        json={"enabled": True, "api_key": "re_x", "from_email": "blog@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert resp.json()["webhook_secret_configured"] is False
    assert "Endpoint URL scheme" not in resp.text

    async def fake_send(**kwargs: str) -> str:
        return "email_1"

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    subscribe = await client.post("/api/subscribe", json={"email": "reader@example.com"})
    assert subscribe.status_code == 200


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

    def fake_fire(*args: object, **kwargs: object) -> bool:
        calls.append(kwargs)
        return True

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
    payload = resp.json()
    assert payload["message"] == "Broadcast queued"
    assert len(payload["request_id"]) == 36
    assert len(calls) == 1
    recorded = calls[0]
    assert recorded["trigger"] == "manual"
    assert recorded["enforce_once_guard"] is False
    assert recorded["post_path"] == file_path
    assert recorded["request_id"] == payload["request_id"]


@pytest.mark.asyncio
async def test_trigger_broadcast_reports_capacity_rejection(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_subscriptions: None
) -> None:
    monkeypatch.setattr(subscription_service, "fire_post_broadcast", lambda *args, **kwargs: False)
    file_path = "posts/capacity-rejected/index.md"
    await _seed_published_post(client, file_path)
    token = await _get_admin_token(client)

    resp = await client.post(
        "/api/admin/subscriptions/broadcasts",
        json={"post_path": file_path},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 503
    assert "capacity" in resp.json()["detail"].lower()


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
            api_key="re_test_key",
            webhook_secret=_TEST_WEBHOOK_SECRET,
        )


@pytest.mark.asyncio
async def test_webhook_valid_signature_returns_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    async def fake_delete(*, api_key: str, contact_id: str) -> None:
        pass

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {
            "type": "contact.updated",
            "data": {"id": "c1", "unsubscribed": True},
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
    payload = b'{"type": "contact.updated", "data": {}}'
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
async def test_webhook_no_secret_configured_returns_retryable_error(client: AsyncClient) -> None:
    payload = b'{"type": "contact.updated", "data": {}}'
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_webhook_resend_api_failure_returns_retryable_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    async def fake_delete(*, api_key: str, contact_id: str) -> None:
        raise resend_client.ResendError("network down")

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {
            "type": "contact.updated",
            "data": {"audience_id": "aud_1", "id": "c1", "unsubscribed": True},
        }
    ).encode()
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_webhook_unknown_event_type_returns_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    delete_calls: list[str] = []

    async def fake_delete(*, api_key: str, contact_id: str) -> None:
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
async def test_webhook_missing_contact_id_returns_retryable_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_webhook_secret: None,
) -> None:
    delete_calls: list[str] = []

    async def fake_delete(*, api_key: str, contact_id: str) -> None:
        delete_calls.append(contact_id)

    monkeypatch.setattr(resend_client, "delete_contact", fake_delete)

    payload = json.dumps(
        {"type": "contact.updated", "data": {"audience_id": "aud_1", "unsubscribed": True}}
    ).encode()
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 503
    assert delete_calls == []


# ── Task 1: confirm endpoint error handling ───────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_bad_token_returns_400(client: AsyncClient) -> None:
    """An explicit bad/expired token → 400 with 'invalid or has expired' in body."""
    resp = await client.get("/subscribe/confirm?token=this_is_a_bad_token")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_confirm_resend_error_returns_503(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
    app_settings: Settings,
) -> None:
    """Valid token but create_contact raises ResendError → 503 retryable, no detail leaked."""
    from backend.services.subscription_tokens import create_confirm_token

    error_detail = "Internal Resend API failure detail xyz"

    async def fake_create_contact(**kwargs: str) -> None:
        raise resend_client.ResendError(error_detail)

    monkeypatch.setattr(resend_client, "create_contact", fake_create_contact)

    token = create_confirm_token("r@x.com", app_settings.secret_key)
    resp = await client.get(f"/subscribe/confirm?token={token}")
    # Must be 503 (retryable), NOT 400 (bad token)
    assert resp.status_code == 503
    # Must NOT contain "invalid or has expired" — that message is for bad tokens
    assert "invalid or has expired" not in resp.text.lower()
    # Must NOT leak the internal Resend error detail
    assert error_detail not in resp.text


@pytest.mark.asyncio
async def test_confirm_internal_server_error_returns_503(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
    app_settings: Settings,
) -> None:
    """Valid token but create_contact raises InternalServerError → 503, no detail leaked."""
    from backend.exceptions import InternalServerError
    from backend.services.subscription_tokens import create_confirm_token

    secret_internal_detail = "Decryption failed with key abc123"

    async def fake_create_contact(**kwargs: str) -> None:
        raise InternalServerError(secret_internal_detail)

    monkeypatch.setattr(resend_client, "create_contact", fake_create_contact)

    token = create_confirm_token("r@x.com", app_settings.secret_key)
    resp = await client.get(f"/subscribe/confirm?token={token}")
    assert resp.status_code == 503
    assert secret_internal_detail not in resp.text


# ── Task 8: Security-relevant test gaps ──────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_resend_error_returns_503_without_leaked_detail(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """ResendError during subscribe → 503, internal error string must NOT appear in body."""
    internal_detail = "Internal Resend API failure detail LEAKED"

    async def fake_send(**kwargs: str) -> str:
        raise resend_client.ResendError(internal_detail)

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    resp = await client.post("/api/subscribe", json={"email": "r@x.com"})
    assert resp.status_code == 503
    assert internal_detail not in resp.text


@pytest.mark.asyncio
async def test_x_forwarded_for_spoofed_by_untrusted_client_uses_peer_ip(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """Untrusted client spoofing X-Forwarded-For → rate limit uses real peer IP, not spoofed."""
    used_ips: list[str] = []
    original_is_limited = None

    async def fake_send(**kwargs: str) -> str:
        return "ok"

    monkeypatch.setattr(resend_client, "send_email", fake_send)

    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None
    limiter = app.state.rate_limiter
    original_is_limited = limiter.is_limited

    def capturing_is_limited(key: str, limit: int, window: int) -> tuple[bool, int]:
        # Extract IP from key pattern "subscribe:<window>:<ip>"
        parts = key.split(":")
        if len(parts) >= 3:
            used_ips.append(parts[2])
        return original_is_limited(key, limit, window)

    limiter.is_limited = capturing_is_limited

    # Send with a spoofed X-Forwarded-For header
    resp = await client.post(
        "/api/subscribe",
        json={"email": "victim@x.com"},
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    # Should succeed (not 429), and the rate-limit key should NOT be the spoofed IP
    assert resp.status_code in (200, 503)  # either way, spoofed IP should not be used
    # The rate limit key must use the real peer IP (testclient uses 127.0.0.1 or similar)
    # — it must NOT be the spoofed "1.2.3.4"
    for ip in used_ips:
        assert ip != "1.2.3.4", f"Spoofed IP was used for rate limiting: {ip}"


@pytest.mark.asyncio
async def test_x_forwarded_for_trusted_proxy_uses_forwarded_ip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_content_dir: Path,
    tmp_path: Path,
) -> None:
    """Trusted proxy sends X-Forwarded-For → first forwarded IP used for rate limiting."""
    from tests.conftest import create_test_client

    used_ips: list[str] = []

    async def fake_send(**kwargs: str) -> str:
        return "ok"

    db_path = tmp_path / "trusted_test.db"
    trusted_settings = Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
        trusted_proxy_ips=["127.0.0.1"],
    )

    async with create_test_client(trusted_settings) as trusted_client:
        trusted_transport = trusted_client._transport
        trusted_app = getattr(trusted_transport, "app", None)
        assert trusted_app is not None
        trusted_limiter = trusted_app.state.rate_limiter
        original_is_limited = trusted_limiter.is_limited

        def capturing_is_limited(key: str, limit: int, window: int) -> tuple[bool, int]:
            parts = key.split(":")
            if len(parts) >= 3:
                used_ips.append(parts[2])
            return original_is_limited(key, limit, window)

        trusted_limiter.is_limited = capturing_is_limited

        import backend.services.resend_client as rc_mod

        monkeypatch.setattr(rc_mod, "send_email", fake_send)

        session_factory = trusted_app.state.session_factory
        secret_key: str = trusted_app.state.settings.secret_key

        async def fake_create_segment(**kwargs: str) -> str:
            return "seg_trusted"

        monkeypatch.setattr(rc_mod, "create_segment", fake_create_segment)

        async with session_factory() as session:
            from backend.services import subscription_service as ss

            await ss.update_settings(
                session,
                secret_key=secret_key,
                enabled=True,
                api_key="re_trusted",
                webhook_secret="whsec_trusted",
                from_email="trusted@example.com",
                from_name="Trusted Blog",
                controller_name="Trusted",
                controller_contact="p@t.com",
                privacy_policy_url="https://t.com/privacy",
                postal_address="1 Trust St",
            )

        resp = await trusted_client.post(
            "/api/subscribe",
            json={"email": "user@example.com"},
            headers={"X-Forwarded-For": "5.6.7.8"},
        )
        assert resp.status_code in (200, 503)
        # The rate limit must use the forwarded IP "5.6.7.8"
        assert any(ip == "5.6.7.8" for ip in used_ips), (
            f"Expected '5.6.7.8' in used IPs but got: {used_ips}"
        )


@pytest.mark.asyncio
async def test_admin_test_endpoint_success(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """Admin POST /api/admin/subscriptions/test → 200 with message."""

    async def fake_send(**kwargs: str) -> str:
        return "email_id"

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    token = await _get_admin_token(client)
    resp = await client.post(
        "/api/admin/subscriptions/test",
        json={"email": "admin@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Test email sent"


@pytest.mark.asyncio
async def test_admin_test_endpoint_disabled_returns_400(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SubscriptionsDisabledError → 400."""
    token = await _get_admin_token(client)
    # No enable_subscriptions fixture — subscriptions not configured
    resp = await client.post(
        "/api/admin/subscriptions/test",
        json={"email": "admin@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_test_endpoint_resend_error_returns_502(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enable_subscriptions: None,
) -> None:
    """ResendError during test email → 502."""

    async def fake_send(**kwargs: str) -> str:
        raise resend_client.ResendError("Resend API failure")

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    token = await _get_admin_token(client)
    resp = await client.post(
        "/api/admin/subscriptions/test",
        json={"email": "admin@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_privacy_page_returns_generated_policy_when_no_file(
    client: AsyncClient,
    enable_subscriptions: None,
) -> None:
    """GET /api/pages/privacy → 200 with privacy policy content when no privacy.md exists."""
    resp = await client.get("/api/pages/privacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "privacy"
    # The generated policy contains recognizable content
    assert "email" in body["rendered_html"].lower() or "privacy" in body["title"].lower()


@pytest.fixture
def app_settings_with_privacy(tmp_path: Path) -> Settings:
    """Settings for an app that has a user-authored privacy.md pre-created."""
    content = tmp_path / "content_with_privacy"
    content.mkdir()
    (content / "posts").mkdir()
    (content / "assets").mkdir()
    (content / "index.toml").write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "privacy"\ntitle = "Privacy Policy"\nfile = "pages/privacy.md"\n'
    )
    (content / "labels.toml").write_text("[labels]\n")
    pages_dir = content / "pages"
    pages_dir.mkdir()
    (pages_dir / "privacy.md").write_text(
        "---\ntitle: My Privacy Page\n---\n\nCustom user-authored privacy content here."
    )
    db_path = tmp_path / "privacy_test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=content,
        frontend_dir=tmp_path / "frontend_privacy",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client_with_privacy(
    app_settings_with_privacy: Settings,
) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(app_settings_with_privacy) as ac:
        yield ac


@pytest.mark.asyncio
async def test_privacy_page_user_authored_overrides_builtin(
    client_with_privacy: AsyncClient,
) -> None:
    """When content/pages/privacy.md exists → user content returned, not generated policy."""
    resp = await client_with_privacy.get("/api/pages/privacy")
    assert resp.status_code == 200
    body = resp.json()
    # The user-authored content should override the generated policy
    assert "Custom user-authored privacy content here" in body["rendered_html"] or (
        body["title"] == "My Privacy Page"
    )


@pytest.mark.asyncio
async def test_webhook_malformed_json_returns_503(
    client: AsyncClient,
    enable_webhook_secret: None,
) -> None:
    """Valid signature but body is not valid JSON → 503."""
    payload = b"this-is-not-json"
    resp = await client.post(
        "/api/webhooks/resend",
        content=payload,
        headers={**_svix_headers(payload), "content-type": "application/json"},
    )
    assert resp.status_code == 503
