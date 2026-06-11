# Resend Webhook Contact Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `POST /api/webhooks/resend` endpoint that verifies Resend's `contact.unsubscribed` webhook and permanently deletes the contact, making unsubscribe equivalent to GDPR erasure.

**Architecture:** New nullable `resend_webhook_secret_encrypted` column on the `subscription_settings` singleton (Alembic migration), verified with the `svix` Python library. A new `handle_resend_webhook` service function decrypts the secret, verifies the signature, and calls a new `delete_contact` client function on matching events. The endpoint returns 400 only on bad signatures; all other failures return 200 so Resend does not retry.

**Tech Stack:** Python/FastAPI, svix (new), httpx (existing), SQLAlchemy/Alembic (existing), Fernet/cryptography (existing).

---

## File Map

| File | Change |
|---|---|
| `pyproject.toml` | Add `svix` dependency |
| `backend/models/subscription.py` | Add `resend_webhook_secret_encrypted` column |
| `backend/migrations/versions/0007_subscription_webhook_secret.py` | New migration |
| `backend/services/resend_client.py` | Add `delete_contact` |
| `backend/services/subscription_service.py` | Add `decrypt_webhook_secret`, `handle_resend_webhook`; update `update_settings`, `build_settings_response` |
| `backend/schemas/subscription.py` | Add `webhook_secret` to update schema; `webhook_secret_configured` to response schema |
| `backend/api/subscriptions.py` | Add `webhook_router` with `POST /api/webhooks/resend` |
| `backend/api/pages.py` | Update retention sentence in privacy policy |
| `backend/main.py` | Import and register `webhook_router` |
| `tests/test_services/test_resend_client.py` | Add three `delete_contact` tests |
| `tests/test_services/test_subscription_settings.py` | Add two webhook-secret settings tests |
| `tests/test_services/test_subscription_webhook.py` | New file — six service-layer webhook tests |
| `tests/test_api/test_subscriptions_api.py` | Add four webhook endpoint API tests |

---

## Task 1: Add svix dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add svix to dependencies**

In `pyproject.toml`, add `"svix>=1.0"` after the httpx line (around line 36):

```toml
    # HTTP client (for cross-posting, sync client)
    "httpx>=0.28",
    "httpcore>=1.0,<2",
    # Webhook signature verification
    "svix>=1.0",
```

- [ ] **Step 2: Install**

```bash
uv sync
```

Expected: resolves and installs `svix` with no errors.

- [ ] **Step 3: Verify import works**

```bash
uv run python -c "from svix.webhooks import Webhook, WebhookVerificationError; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add svix dependency for webhook signature verification"
```

---

## Task 2: Add `delete_contact` to resend_client (TDD)

**Files:**
- Modify: `tests/test_services/test_resend_client.py`
- Modify: `backend/services/resend_client.py`

- [ ] **Step 1: Write the three failing tests**

Append to `tests/test_services/test_resend_client.py`:

```python
@pytest.mark.asyncio
async def test_delete_contact_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"id": "contact_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    await resend_client.delete_contact(
        api_key="re_x", audience_id="aud_1", contact_id="contact_1"
    )
    assert seen["method"] == "DELETE"
    assert "aud_1/contacts/contact_1" in seen["url"]


@pytest.mark.asyncio
async def test_delete_contact_404_treated_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Contact not found"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    # Must not raise
    await resend_client.delete_contact(
        api_key="re_x", audience_id="aud_1", contact_id="gone"
    )


@pytest.mark.asyncio
async def test_delete_contact_other_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError, match="Invalid API key"):
        await resend_client.delete_contact(
            api_key="re_bad", audience_id="aud_1", contact_id="c1"
        )
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_services/test_resend_client.py::test_delete_contact_success tests/test_services/test_resend_client.py::test_delete_contact_404_treated_as_success tests/test_services/test_resend_client.py::test_delete_contact_other_error_raises -v
```

Expected: `AttributeError: module 'backend.services.resend_client' has no attribute 'delete_contact'`

- [ ] **Step 3: Implement `delete_contact` in `backend/services/resend_client.py`**

Add after `create_contact` (after line 103):

```python
async def delete_contact(*, api_key: str, audience_id: str, contact_id: str) -> None:
    """Permanently delete a contact from the Resend audience. Treats 404 as success."""
    try:
        response = await _get_client().delete(
            f"{_API_BASE}/audiences/{audience_id}/contacts/{contact_id}",
            headers=_headers(api_key),
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend delete contact %s failed: %s", contact_id, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code == 404:
        return
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_services/test_resend_client.py::test_delete_contact_success tests/test_services/test_resend_client.py::test_delete_contact_404_treated_as_success tests/test_services/test_resend_client.py::test_delete_contact_other_error_raises -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/resend_client.py tests/test_services/test_resend_client.py
git commit -m "feat: add delete_contact to resend client"
```

---

## Task 3: DB migration and model column

**Files:**
- Modify: `backend/models/subscription.py`
- Create: `backend/migrations/versions/0007_subscription_webhook_secret.py`

- [ ] **Step 1: Add column to model**

In `backend/models/subscription.py`, add one line after `resend_api_key_encrypted` (after line 19):

```python
    resend_webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
```

The block becomes:

```python
    resend_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    resend_webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    resend_segment_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 2: Create migration file**

Create `backend/migrations/versions/0007_subscription_webhook_secret.py`:

```python
"""add resend_webhook_secret_encrypted to subscription_settings

Revision ID: a3d9b2e1f458
Revises: e2b4f7a1c509
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a3d9b2e1f458"
down_revision: str | None = "e2b4f7a1c509"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "subscription_settings",
        sa.Column("resend_webhook_secret_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscription_settings", "resend_webhook_secret_encrypted")
```

- [ ] **Step 3: Verify migration runs cleanly**

```bash
uv run pytest tests/test_services/test_migrations.py -v
```

Expected: all migration tests pass (they apply all migrations and check the schema).

- [ ] **Step 4: Commit**

```bash
git add backend/models/subscription.py backend/migrations/versions/0007_subscription_webhook_secret.py
git commit -m "feat: add resend_webhook_secret_encrypted column to subscription_settings"
```

---

## Task 4: Update schemas

**Files:**
- Modify: `backend/schemas/subscription.py`

- [ ] **Step 1: Add `webhook_secret_configured` to `SubscriptionSettingsResponse`**

In `backend/schemas/subscription.py`, add `webhook_secret_configured: bool` after `key_configured`:

```python
class SubscriptionSettingsResponse(BaseModel):
    """Admin view. key_configured is a bool; the key itself is never returned."""

    enabled: bool
    from_email: str | None
    from_name: str | None
    controller_name: str | None
    controller_contact: str | None
    privacy_policy_url: str | None
    postal_address: str | None
    key_configured: bool
    webhook_secret_configured: bool
    segment_configured: bool
    subscriber_count: int | None  # None when Resend is unreachable
```

- [ ] **Step 2: Add `webhook_secret` to `SubscriptionSettingsUpdate`**

Add `webhook_secret: str | None = None` after `api_key`:

```python
class SubscriptionSettingsUpdate(BaseModel):
    enabled: bool | None = None
    api_key: str | None = None  # write-only
    webhook_secret: str | None = None  # write-only
    from_email: str | None = None
    from_name: str | None = None
    controller_name: str | None = None
    controller_contact: str | None = None
    privacy_policy_url: str | None = None
    postal_address: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> SubscriptionSettingsUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self
```

- [ ] **Step 3: Verify static checks pass**

```bash
uv run ruff check backend/schemas/subscription.py
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/schemas/subscription.py
git commit -m "feat: add webhook_secret fields to subscription schemas"
```

---

## Task 5: Update service settings functions + tests

**Files:**
- Modify: `backend/services/subscription_service.py`
- Modify: `tests/test_services/test_subscription_settings.py`

- [ ] **Step 1: Write two failing tests**

Append to `tests/test_services/test_subscription_settings.py`:

```python
@pytest.mark.asyncio
async def test_webhook_secret_encrypted_and_flag_set(session: AsyncSession) -> None:
    from backend.services.crypto_service import decrypt_value

    await subscription_service.update_settings(
        session, secret_key=SECRET, webhook_secret="whsec_test123"
    )
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_webhook_secret_encrypted not in (None, "whsec_test123")
    assert decrypt_value(row.resend_webhook_secret_encrypted, SECRET) == "whsec_test123"


@pytest.mark.asyncio
async def test_webhook_secret_configured_flag_in_response(session: AsyncSession) -> None:
    response = await subscription_service.build_settings_response(session, SECRET)
    assert response.webhook_secret_configured is False

    await subscription_service.update_settings(
        session, secret_key=SECRET, webhook_secret="whsec_test"
    )
    response = await subscription_service.build_settings_response(session, SECRET)
    assert response.webhook_secret_configured is True
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_services/test_subscription_settings.py::test_webhook_secret_encrypted_and_flag_set tests/test_services/test_subscription_settings.py::test_webhook_secret_configured_flag_in_response -v
```

Expected: `TypeError` (unexpected keyword `webhook_secret`) or `AttributeError` on `webhook_secret_configured`.

- [ ] **Step 3: Add `decrypt_webhook_secret` and update `update_settings` in `subscription_service.py`**

Add after `decrypt_api_key` (after line 97):

```python
def decrypt_webhook_secret(row: SubscriptionSettings, secret_key: str) -> str | None:
    if not row.resend_webhook_secret_encrypted:
        return None
    return decrypt_value(row.resend_webhook_secret_encrypted, secret_key)
```

In `update_settings`, add `webhook_secret: str | None = None` parameter (after `api_key`):

```python
async def update_settings(
    session: AsyncSession,
    *,
    secret_key: str,
    enabled: bool | None = None,
    api_key: str | None = None,
    webhook_secret: str | None = None,
    from_email: _StringUpdate = _UNSET,
    from_name: _StringUpdate = _UNSET,
    controller_name: _StringUpdate = _UNSET,
    controller_contact: _StringUpdate = _UNSET,
    privacy_policy_url: _StringUpdate = _UNSET,
    postal_address: _StringUpdate = _UNSET,
) -> SubscriptionSettings:
```

And add the encryption block after the `api_key` block (after line 125):

```python
    if api_key is not None and api_key != "":
        row.resend_api_key_encrypted = encrypt_value(api_key, secret_key)
    if webhook_secret is not None and webhook_secret != "":
        row.resend_webhook_secret_encrypted = encrypt_value(webhook_secret, secret_key)
```

- [ ] **Step 4: Update both `build_settings_response` return sites to include `webhook_secret_configured`**

The `None`-row early-return (around line 185):

```python
    if row is None:
        return SubscriptionSettingsResponse(
            enabled=False,
            from_email=None,
            from_name=None,
            controller_name=None,
            controller_contact=None,
            privacy_policy_url=None,
            postal_address=None,
            key_configured=False,
            webhook_secret_configured=False,
            segment_configured=False,
            subscriber_count=None,
        )
```

The normal return (around line 206):

```python
    return SubscriptionSettingsResponse(
        enabled=row.enabled,
        from_email=row.from_email,
        from_name=row.from_name,
        controller_name=row.controller_name,
        controller_contact=row.controller_contact,
        privacy_policy_url=row.privacy_policy_url,
        postal_address=row.postal_address,
        key_configured=bool(row.resend_api_key_encrypted),
        webhook_secret_configured=bool(row.resend_webhook_secret_encrypted),
        segment_configured=bool(row.resend_segment_id),
        subscriber_count=count,
    )
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest tests/test_services/test_subscription_settings.py -v
```

Expected: all pass (including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/services/subscription_service.py tests/test_services/test_subscription_settings.py
git commit -m "feat: add webhook_secret to subscription settings service"
```

---

## Task 6: Add `handle_resend_webhook` service function + tests

**Files:**
- Create: `tests/test_services/test_subscription_webhook.py`
- Modify: `backend/services/subscription_service.py`

- [ ] **Step 1: Create the test file with six failing tests**

Create `tests/test_services/test_subscription_webhook.py`:

```python
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


def _svix_headers(
    payload: bytes, msg_id: str = "msg_test_1"
) -> dict[str, str]:
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
async def test_handle_webhook_no_secret_configured_returns_without_raising(
    session: AsyncSession,
) -> None:
    # No settings row at all — must return silently (no exception).
    await subscription_service.handle_resend_webhook(
        session,
        raw_body=b"{}",
        headers={},
        secret_key=SECRET,
    )


@pytest.mark.asyncio
async def test_handle_webhook_resend_error_does_not_raise(
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

    # Must not raise — errors are logged and swallowed
    await subscription_service.handle_resend_webhook(
        session,
        raw_body=payload,
        headers=_svix_headers(payload),
        secret_key=SECRET,
    )


@pytest.mark.asyncio
async def test_handle_webhook_missing_contact_id_does_not_raise(
    session: AsyncSession,
) -> None:
    await _configure_webhook_secret(session)

    payload = json.dumps(
        {
            "type": "contact.unsubscribed",
            "data": {"audience_id": "aud_abc", "contact": {}},
        }
    ).encode()

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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_services/test_subscription_webhook.py -v
```

Expected: `AttributeError: module ... has no attribute 'handle_resend_webhook'`

- [ ] **Step 3: Implement `handle_resend_webhook` in `subscription_service.py`**

Add `import json` to the imports at the top of `backend/services/subscription_service.py` (near the other stdlib imports):

```python
import asyncio
import json
import logging
```

Add `from svix.webhooks import Webhook, WebhookVerificationError` import:

```python
from svix.webhooks import Webhook, WebhookVerificationError
```

Add `__all__` export or simply add the function. Add `handle_resend_webhook` at the end of the file (before `close_broadcast_tasks`):

```python
async def handle_resend_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    headers: dict[str, str],
    secret_key: str,
) -> None:
    """Verify Resend webhook signature and process the event.

    Raises WebhookVerificationError on bad signature — caller maps this to 400.
    All other failures (missing config, Resend API errors, malformed payload)
    are logged and swallowed so the caller can return 200.
    """
    row = await _get_row(session)
    if row is None or not row.resend_webhook_secret_encrypted:
        logger.warning("Resend webhook received but no webhook secret is configured; ignoring")
        return

    webhook_secret = decrypt_webhook_secret(row, secret_key)
    if webhook_secret is None:
        logger.warning("Resend webhook: failed to decrypt webhook secret; ignoring")
        return

    # Raises WebhookVerificationError on bad/expired signature — propagated to caller.
    Webhook(webhook_secret).verify(raw_body, headers)

    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        logger.warning("Resend webhook: malformed JSON body")
        return

    if payload.get("type") != "contact.unsubscribed":
        return

    data = payload.get("data") or {}
    contact = data.get("contact") or {}
    contact_id = contact.get("id")
    audience_id = data.get("audience_id")

    if not contact_id or not audience_id:
        logger.warning(
            "Resend webhook: contact.unsubscribed missing contact id or audience_id"
        )
        return

    api_key = decrypt_api_key(row, secret_key)
    if api_key is None:
        logger.warning("Resend webhook: API key not configured; cannot delete contact %s", contact_id)
        return

    try:
        await resend_client.delete_contact(
            api_key=api_key, audience_id=audience_id, contact_id=contact_id
        )
        logger.info(
            "Deleted unsubscribed contact %s from audience %s", contact_id, audience_id
        )
    except resend_client.ResendError as exc:
        logger.warning(
            "Resend webhook: failed to delete contact %s from audience %s: %s",
            contact_id,
            audience_id,
            exc,
        )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_services/test_subscription_webhook.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/subscription_service.py tests/test_services/test_subscription_webhook.py
git commit -m "feat: add handle_resend_webhook to subscription service"
```

---

## Task 7: Webhook endpoint + API tests

**Files:**
- Modify: `backend/api/subscriptions.py`
- Modify: `backend/main.py`
- Modify: `tests/test_api/test_subscriptions_api.py`

- [ ] **Step 1: Write four failing API tests**

Append to `tests/test_api/test_subscriptions_api.py`:

```python
import base64
import hashlib
import hmac
import json
import time

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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_api/test_subscriptions_api.py::test_webhook_valid_signature_returns_200 tests/test_api/test_subscriptions_api.py::test_webhook_bad_signature_returns_400 tests/test_api/test_subscriptions_api.py::test_webhook_no_secret_configured_returns_200 tests/test_api/test_subscriptions_api.py::test_webhook_resend_api_failure_still_returns_200 -v
```

Expected: 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Add `webhook_router` to `backend/api/subscriptions.py`**

Add the import at the top with the other `svix` import:

```python
from svix.webhooks import WebhookVerificationError
```

Add after the existing router declarations (after `admin_router = ...`):

```python
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
```

Add the endpoint after the `admin_router` endpoints (at the end of the file):

```python
@webhook_router.post("/resend")
async def resend_webhook_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    raw_body = await request.body()
    try:
        await subscription_service.handle_resend_webhook(
            session,
            raw_body=raw_body,
            headers=dict(request.headers),
            secret_key=settings.secret_key,
        )
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception:
        logger.warning("Resend webhook processing error", exc_info=True)
    return {}
```

- [ ] **Step 4: Register `webhook_router` in `backend/main.py`**

Add import near the other subscription imports (around line 40):

```python
from backend.api.subscriptions import webhook_router as subscriptions_webhook_router
```

Add registration near the other subscription routers (around line 1020):

```python
    app.include_router(subscriptions_webhook_router)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest tests/test_api/test_subscriptions_api.py::test_webhook_valid_signature_returns_200 tests/test_api/test_subscriptions_api.py::test_webhook_bad_signature_returns_400 tests/test_api/test_subscriptions_api.py::test_webhook_no_secret_configured_returns_200 tests/test_api/test_subscriptions_api.py::test_webhook_resend_api_failure_still_returns_200 -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/api/subscriptions.py backend/main.py tests/test_api/test_subscriptions_api.py
git commit -m "feat: add POST /api/webhooks/resend endpoint"
```

---

## Task 8: Update privacy policy text

**Files:**
- Modify: `backend/api/pages.py`

- [ ] **Step 1: Update the retention paragraph**

In `backend/api/pages.py`, replace the retention section (around line 63):

Old:
```python
        "<h2>Retention</h2>"
        "<p>We keep your email address until you unsubscribe. Every email includes an"
        " unsubscribe link.</p>"
```

New:
```python
        "<h2>Retention</h2>"
        "<p>Your email address is deleted from our email service provider when you"
        " unsubscribe. Every email includes an unsubscribe link.</p>"
```

- [ ] **Step 2: Run static checks**

```bash
uv run ruff check backend/api/pages.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/api/pages.py
git commit -m "fix: update privacy policy retention text to reflect contact deletion on unsubscribe"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run the full gate**

```bash
just check
```

Expected: all static checks and tests pass, coverage targets met.

- [ ] **Step 2: Confirm webhook endpoint appears in the API**

```bash
uv run python -c "
from backend.main import create_app
from backend.config import Settings
import tempfile, pathlib
p = pathlib.Path(tempfile.mkdtemp())
s = Settings(secret_key='x'*48, database_url='sqlite+aiosqlite:///'+str(p/'t.db'), content_dir=p/'c', frontend_dir=p/'f', admin_username='a', admin_password='aaaaaaaa')
app = create_app(s)
routes = [r.path for r in app.routes if hasattr(r, 'path')]
assert '/api/webhooks/resend' in routes, routes
print('ok — /api/webhooks/resend registered')
"
```

Expected: `ok — /api/webhooks/resend registered`
