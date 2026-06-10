# Email Subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an email-subscription feature where readers confirm-opt-in and Resend is the sole store of subscriber addresses; publishing a post broadcasts its HTML to subscribers via Resend.

**Architecture:** AgBlogger stores **zero subscriber PII**. It persists only non-PII config (`subscription_settings` singleton + `subscription_broadcasts` ledger) in the main durable DB. Subscribe uses a stateless signed (PyJWT) confirmation token; on confirm we create a Resend contact. Broadcasts and unsubscribe are delegated to Resend. The design mirrors the existing analytics feature (settings singleton + shared httpx client + fire-and-forget background tasks).

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, PyJWT, `httpx`, Pydantic (`EmailStr`), React + TypeScript (SWR, Zustand, Tailwind), Resend HTTP API.

**Spec:** `docs/specs/2026-06-10-subscriptions-design.md`

**Conventions for every task:**
- TDD: write the failing test, watch it fail, implement, watch it pass, commit.
- Run a single backend test with `uv run pytest <path>::<test> -v` (fast iteration). Run the full gate with `just check` before declaring done. Frontend tests run with `just test-frontend`.
- Python: ruff (line length 100), mypy strict; modern unions; no `type: ignore` / `noqa` / `fmt:` without asking.
- Commit format: `type: subject` (imperative, lowercase).
- **Frontend tasks:** per `frontend/CLAUDE.md`, use the `vercel-react-best-practices` and `frontend-design` skills; disable controls during async; verify in the browser with the Playwright MCP and delete any leftover screenshots.

**External-API caveat (read once):** Resend renamed "Audiences" → "Segments" and its exact endpoint paths/field names may differ slightly from this plan. Where a step calls Resend, verify the path/field against the live reference at https://resend.com/docs/api-reference before finalizing; the request/response *handling* in this plan is correct regardless.

---

## File structure

**Backend — create:**
- `backend/models/subscription.py` — `SubscriptionSettings` (singleton) + `SubscriptionBroadcast` (ledger) durable models.
- `backend/migrations/versions/0006_subscription_tables.py` — Alembic migration for the two tables.
- `backend/schemas/subscription.py` — Pydantic request/response schemas.
- `backend/services/resend_client.py` — thin async Resend HTTP boundary (contacts, broadcasts, transactional sends, contact count).
- `backend/services/subscription_email.py` — confirmation + broadcast HTML/text builders.
- `backend/services/subscription_service.py` — orchestration: settings, confirm tokens, subscribe/confirm, broadcast firing, once-guard ledger.
- `backend/api/subscriptions.py` — public (`/api/subscribe`, `/subscribe/confirm`) + admin (`/api/admin/subscriptions/*`) routers.

**Backend — modify:**
- `backend/services/key_derivation.py` — add confirm-token key derivation.
- `backend/schemas/page.py` — add `subscriptions_enabled` to `SiteConfigResponse`.
- `backend/services/page_service.py` — populate `subscriptions_enabled` in `get_site_config`.
- `backend/api/pages.py` — pass session so site config can read the flag.
- `backend/api/posts.py` — fire auto-broadcast on the draft→published transition (create + update endpoints).
- `backend/main.py` — register routers; close the Resend client in lifespan shutdown.

**Frontend — create:**
- `frontend/src/api/subscriptions.ts` — API module.
- `frontend/src/pages/SubscribePage.tsx` — public subscribe form + layered notice.
- `frontend/src/components/admin/SubscriptionsPanel.tsx` — admin tab.

**Frontend — modify:**
- `frontend/src/App.tsx` — add `/subscribe` route.
- `frontend/src/components/layout/Header.tsx` — conditional Subscribe link.
- `frontend/src/pages/AdminPage.tsx` — add "Subscriptions" tab.
- `frontend/src/stores/siteStore.ts` (+ `frontend/src/api/client.ts` types) — expose `subscriptions_enabled`.

**Docs — create/modify:**
- `docs/arch/subscriptions.md` (new) + updates to `index.md`, `backend.md`, `data-flow.md`, `security.md`, `frontend.md`, `deployment.md`.

---

## Task 1: Durable models — settings singleton + broadcast ledger

**Files:**
- Create: `backend/models/subscription.py`
- Test: `tests/test_models/test_subscription_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models/test_subscription_models.py
"""Subscription durable models live in the main DB and store no PII."""

from __future__ import annotations

from backend.models.base import DurableBase
from backend.models.subscription import SubscriptionBroadcast, SubscriptionSettings


def test_settings_is_durable_singleton() -> None:
    assert SubscriptionSettings.__tablename__ == "subscription_settings"
    assert issubclass(SubscriptionSettings, DurableBase)
    cols = SubscriptionSettings.__table__.columns
    # No email/PII columns — only config.
    assert {"id", "enabled", "resend_api_key_encrypted", "resend_segment_id",
            "from_email", "from_name", "controller_name", "controller_contact",
            "privacy_policy_url", "postal_address", "updated_at"} <= set(cols.keys())
    assert "email" not in cols.keys()


def test_broadcast_ledger_has_no_recipient_columns() -> None:
    assert SubscriptionBroadcast.__tablename__ == "subscription_broadcasts"
    cols = set(SubscriptionBroadcast.__table__.columns.keys())
    assert {"id", "post_path", "post_title", "resend_broadcast_id",
            "trigger", "status", "sent_at", "error"} <= cols
    assert "email" not in cols and "recipients" not in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models/test_subscription_models.py -v`
Expected: FAIL with `ModuleNotFoundError: backend.models.subscription`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/models/subscription.py
"""Subscription config + broadcast ledger (durable, no subscriber PII)."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import DurableBase


class SubscriptionSettings(DurableBase):
    """Singleton row holding subscription configuration. Stores no subscriber data."""

    __tablename__ = "subscription_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_subscription_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resend_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    resend_segment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    from_email: Mapped[str | None] = mapped_column(String, nullable=True)
    from_name: Mapped[str | None] = mapped_column(String, nullable=True)
    controller_name: Mapped[str | None] = mapped_column(String, nullable=True)
    controller_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    privacy_policy_url: Mapped[str | None] = mapped_column(String, nullable=True)
    postal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SubscriptionBroadcast(DurableBase):
    """One row per broadcast attempt. References a Resend broadcast, not recipients."""

    __tablename__ = "subscription_broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_path: Mapped[str] = mapped_column(Text, nullable=False)
    post_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resend_broadcast_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)  # "auto" | "manual"
    status: Mapped[str] = mapped_column(String, nullable=False)  # "sent" | "failed"
    sent_at: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models/test_subscription_models.py -v`
Expected: PASS.

- [ ] **Step 5: Register models for metadata.** Confirm `backend/models/__init__.py` imports models so Alembic autogenerate/`create_all` sees them. Open `backend/models/__init__.py`; if it lists models (it imports `AnalyticsSettings` etc.), add `from backend.models.subscription import SubscriptionBroadcast, SubscriptionSettings`.

Run: `uv run pytest tests/test_models/test_subscription_models.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/models/subscription.py backend/models/__init__.py tests/test_models/test_subscription_models.py
git commit -m "feat: add subscription settings and broadcast ledger models"
```

---

## Task 2: Alembic migration for subscription tables

**Files:**
- Create: `backend/migrations/versions/0006_subscription_tables.py`
- Test: `tests/test_migrations/test_subscription_migration.py`

Inspect `backend/migrations/versions/0002_analytics_settings.py` first to copy the revision style and `down_revision` chaining. The latest revision is `0005_sync_manifest_to_durable`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrations/test_subscription_migration.py
"""The subscription tables exist after migrations run."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from backend.config import Settings
from backend.database import create_engine
from backend.migrations.runner import run_migrations  # see Step 3 note


@pytest.mark.asyncio
async def test_subscription_tables_created(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db")
    engine, _ = create_engine(settings)
    await run_migrations(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert "subscription_settings" in tables
    assert "subscription_broadcasts" in tables
    await engine.dispose()
```

> Note: match the project's existing migration test style. Find how migrations are applied at startup (`grep -rn "command.upgrade\|alembic\|run_migrations" backend/`) and call the same entry point in the test. If the project has no migration-test helper, assert table creation by running the app's startup migration path used elsewhere in `tests/`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrations/test_subscription_migration.py -v`
Expected: FAIL (tables missing / migration absent).

- [ ] **Step 3: Write the migration**

```python
# backend/migrations/versions/0006_subscription_tables.py
"""subscription tables

Revision ID: 0006_subscription_tables
Revises: 0005_sync_manifest_to_durable
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_subscription_tables"
down_revision = "0005_sync_manifest_to_durable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resend_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("resend_segment_id", sa.String(), nullable=True),
        sa.Column("from_email", sa.String(), nullable=True),
        sa.Column("from_name", sa.String(), nullable=True),
        sa.Column("controller_name", sa.String(), nullable=True),
        sa.Column("controller_contact", sa.String(), nullable=True),
        sa.Column("privacy_policy_url", sa.String(), nullable=True),
        sa.Column("postal_address", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint("id = 1", name="ck_subscription_settings_singleton"),
    )
    op.create_table(
        "subscription_broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_path", sa.Text(), nullable=False),
        sa.Column("post_title", sa.Text(), nullable=False, server_default=""),
        sa.Column("resend_broadcast_id", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("sent_at", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_subscription_broadcasts_post_path",
        "subscription_broadcasts",
        ["post_path"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_broadcasts_post_path", "subscription_broadcasts")
    op.drop_table("subscription_broadcasts")
    op.drop_table("subscription_settings")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migrations/test_subscription_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0006_subscription_tables.py tests/test_migrations/test_subscription_migration.py
git commit -m "feat: add migration for subscription tables"
```

---

## Task 3: Confirmation-token signing (stateless double opt-in)

**Files:**
- Modify: `backend/services/key_derivation.py`
- Create: `backend/services/subscription_tokens.py`
- Test: `tests/test_services/test_subscription_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services/test_subscription_tokens.py
"""Stateless subscribe-confirm tokens: round-trip, tamper, expiry, type."""

from __future__ import annotations

import jwt
import pytest

from backend.services.key_derivation import derive_subscribe_confirm_key
from backend.services.subscription_tokens import (
    create_confirm_token,
    verify_confirm_token,
)

SECRET = "x" * 48


def test_round_trip() -> None:
    token = create_confirm_token("Reader@Example.com ", SECRET)
    # Email is normalized inside the token payload.
    assert verify_confirm_token(token, SECRET) == "reader@example.com"


def test_tampered_token_rejected() -> None:
    token = create_confirm_token("a@b.com", SECRET)
    assert verify_confirm_token(token + "x", SECRET) is None


def test_wrong_secret_rejected() -> None:
    token = create_confirm_token("a@b.com", SECRET)
    assert verify_confirm_token(token, "y" * 48) is None


def test_expired_token_rejected() -> None:
    token = create_confirm_token("a@b.com", SECRET, expires_minutes=-1)
    assert verify_confirm_token(token, SECRET) is None


def test_wrong_type_claim_rejected() -> None:
    key = derive_subscribe_confirm_key(SECRET)
    token = jwt.encode({"email": "a@b.com", "type": "other"}, key, algorithm="HS256")
    assert verify_confirm_token(token, SECRET) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_subscription_tokens.py -v`
Expected: FAIL (`derive_subscribe_confirm_key` / module missing).

- [ ] **Step 3a: Add key derivation**

```python
# backend/services/key_derivation.py  — add alongside the existing contexts/functions
_SUBSCRIBE_CONFIRM_CONTEXT = b"agblogger:subscribe-confirm:v1"


def derive_subscribe_confirm_key(secret_key: str) -> str:
    """Derive a signing key for stateless subscribe-confirmation tokens."""
    return base64.urlsafe_b64encode(
        _derive(secret_key, _SUBSCRIBE_CONFIRM_CONTEXT)
    ).decode("ascii")
```

- [ ] **Step 3b: Add token module**

```python
# backend/services/subscription_tokens.py
"""Signed, expiring subscribe-confirmation tokens (no server-side storage)."""

from __future__ import annotations

from datetime import timedelta

import jwt

from backend.services.key_derivation import derive_subscribe_confirm_key
from backend.utils.datetime import now_utc

_ALGORITHM = "HS256"
_TOKEN_TYPE = "subscribe-confirm"
_DEFAULT_EXPIRES_MINUTES = 60 * 48  # 48h confirmation window


def normalize_email(email: str) -> str:
    """Trim + lowercase for consistent dedup and token payloads."""
    return email.strip().lower()


def create_confirm_token(
    email: str, secret_key: str, *, expires_minutes: int = _DEFAULT_EXPIRES_MINUTES
) -> str:
    """Create a signed token carrying the (normalized) email and an expiry."""
    payload = {
        "email": normalize_email(email),
        "type": _TOKEN_TYPE,
        "exp": now_utc() + timedelta(minutes=expires_minutes),
    }
    return str(jwt.encode(payload, derive_subscribe_confirm_key(secret_key), algorithm=_ALGORITHM))


def verify_confirm_token(token: str, secret_key: str) -> str | None:
    """Return the normalized email if the token is valid and unexpired, else None."""
    try:
        payload = jwt.decode(
            token, derive_subscribe_confirm_key(secret_key), algorithms=[_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != _TOKEN_TYPE:
        return None
    email = payload.get("email")
    return email if isinstance(email, str) and email else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_subscription_tokens.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/key_derivation.py backend/services/subscription_tokens.py tests/test_services/test_subscription_tokens.py
git commit -m "feat: add stateless subscribe-confirmation tokens"
```

---

## Task 4: Pydantic schemas

**Files:**
- Create: `backend/schemas/subscription.py`
- Test: `tests/test_schemas/test_subscription_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas/test_subscription_schemas.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.subscription import (
    SubscribeRequest,
    SubscriptionSettingsUpdate,
)


def test_subscribe_request_validates_email() -> None:
    assert SubscribeRequest(email="a@b.com").email == "a@b.com"
    with pytest.raises(ValidationError):
        SubscribeRequest(email="not-an-email")


def test_settings_update_requires_a_field() -> None:
    with pytest.raises(ValidationError):
        SubscriptionSettingsUpdate()  # all-None must be rejected
    # api_key is accepted and is write-only (no response schema exposes it).
    SubscriptionSettingsUpdate(api_key="re_123")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schemas/test_subscription_schemas.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write the schemas**

```python
# backend/schemas/subscription.py
"""Request/response schemas for subscriptions. No schema ever exposes the API key."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, model_validator


class SubscribeRequest(BaseModel):
    email: EmailStr


class SubscribeResponse(BaseModel):
    # Identical message in every case (no enumeration).
    message: str = "Please check your inbox to confirm your subscription."


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
    segment_configured: bool
    subscriber_count: int | None  # None when Resend is unreachable


class SubscriptionSettingsUpdate(BaseModel):
    enabled: bool | None = None
    api_key: str | None = None  # write-only
    from_email: str | None = None
    from_name: str | None = None
    controller_name: str | None = None
    controller_contact: str | None = None
    privacy_policy_url: str | None = None
    postal_address: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "SubscriptionSettingsUpdate":
        if all(v is None for v in self.__dict__.values()):
            raise ValueError("At least one field must be provided")
        return self


class TestEmailRequest(BaseModel):
    email: EmailStr


class BroadcastSummary(BaseModel):
    id: int
    post_path: str
    post_title: str
    resend_broadcast_id: str | None
    trigger: str
    status: str
    sent_at: str
    error: str | None


class BroadcastListResponse(BaseModel):
    broadcasts: list[BroadcastSummary]


class TriggerBroadcastRequest(BaseModel):
    post_path: str = Field(min_length=1, max_length=400)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schemas/test_subscription_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/subscription.py tests/test_schemas/test_subscription_schemas.py
git commit -m "feat: add subscription API schemas"
```

---

## Task 5: Resend HTTP client

**Files:**
- Create: `backend/services/resend_client.py`
- Test: `tests/test_services/test_resend_client.py`

Read `tests/test_services/test_crosspost.py` to match the project's `httpx.MockTransport` style.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services/test_resend_client.py
from __future__ import annotations

import httpx
import pytest

from backend.services import resend_client
from backend.services.resend_client import ResendError


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_send_email_success(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "email_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    out = await resend_client.send_email(
        api_key="re_x", from_="A <a@b.com>", to="r@x.com", subject="s", html="<p>h</p>", text="h"
    )
    assert out == "email_1"
    assert seen["url"].endswith("/emails")
    assert seen["auth"] == "Bearer re_x"


@pytest.mark.asyncio
async def test_send_email_error_raises(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Invalid from"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.send_email(
            api_key="re_x", from_="bad", to="r@x.com", subject="s", html="h", text="h"
        )
    assert "Invalid from" in str(exc.value)


@pytest.mark.asyncio
async def test_create_contact_calls_segment(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(201, json={"id": "contact_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    await resend_client.create_contact(api_key="re_x", segment_id="seg_1", email="r@x.com")
    assert "seg_1" in seen["url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_resend_client.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write the client**

```python
# backend/services/resend_client.py
"""Thin async boundary over the Resend HTTP API. Verify exact paths against
https://resend.com/docs/api-reference (Audiences→Segments rename in progress)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.resend.com"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_client_instance: httpx.AsyncClient | None = None


class ResendError(Exception):
    """A Resend API call failed. Message is safe to show to the admin."""


def _get_client() -> httpx.AsyncClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client_instance


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _extract_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            return body["message"]
    except (ValueError, TypeError):
        pass
    return f"Resend returned HTTP {response.status_code}"


async def _post(api_key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await _get_client().post(
            f"{_API_BASE}{path}", json=payload, headers=_headers(api_key)
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend request to %s failed: %s", path, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
    data = response.json()
    return data if isinstance(data, dict) else {}


async def send_email(
    *, api_key: str, from_: str, to: str, subject: str, html: str, text: str
) -> str:
    """Send one transactional email (confirmation / test). Returns the email id."""
    data = await _post(
        api_key,
        "/emails",
        {"from": from_, "to": [to], "subject": subject, "html": html, "text": text},
    )
    return str(data.get("id", ""))


async def create_contact(*, api_key: str, segment_id: str, email: str) -> None:
    """Add a confirmed contact to the Resend segment/audience."""
    # Treat "already exists" as success so confirm is idempotent.
    try:
        await _post(
            api_key,
            f"/audiences/{segment_id}/contacts",
            {"email": email, "unsubscribed": False},
        )
    except ResendError as exc:
        if "already exists" in str(exc).lower():
            return
        raise


async def create_segment(*, api_key: str, name: str) -> str:
    """Create a segment/audience and return its id."""
    data = await _post(api_key, "/audiences", {"name": name})
    return str(data.get("id", ""))


async def create_and_send_broadcast(
    *, api_key: str, segment_id: str, from_: str, subject: str, html: str, text: str
) -> str:
    """Create a broadcast to the segment and send it now. Returns the broadcast id."""
    created = await _post(
        api_key,
        "/broadcasts",
        {
            "audience_id": segment_id,
            "from": from_,
            "subject": subject,
            "html": html,
            "text": text,
        },
    )
    broadcast_id = str(created.get("id", ""))
    if not broadcast_id:
        raise ResendError("Resend did not return a broadcast id")
    await _post(api_key, f"/broadcasts/{broadcast_id}/send", {})
    return broadcast_id


async def count_contacts(*, api_key: str, segment_id: str) -> int:
    """Return the number of contacts in the segment."""
    try:
        response = await _get_client().get(
            f"{_API_BASE}/audiences/{segment_id}/contacts", headers=_headers(api_key)
        )
    except httpx.HTTPError as exc:
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    return len(items) if isinstance(items, list) else 0


async def close_resend_client() -> None:
    """Close the shared client during app shutdown."""
    global _client_instance
    if _client_instance is not None:
        await _client_instance.aclose()
        _client_instance = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_resend_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/resend_client.py tests/test_services/test_resend_client.py
git commit -m "feat: add Resend HTTP client"
```

---

## Task 6: Email builders

**Files:**
- Create: `backend/services/subscription_email.py`
- Test: `tests/test_services/test_subscription_email.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services/test_subscription_email.py
from __future__ import annotations

from backend.services.subscription_email import (
    build_broadcast_email,
    build_confirmation_email,
)


def test_confirmation_email_contains_confirm_link() -> None:
    html, text = build_confirmation_email(
        confirm_url="https://blog.example/subscribe/confirm?token=T",
        controller_name="Jane Blog",
    )
    assert "https://blog.example/subscribe/confirm?token=T" in html
    assert "https://blog.example/subscribe/confirm?token=T" in text
    assert "Jane Blog" in html
    assert "ignore" in text.lower()  # "if you didn't request this, ignore"


def test_broadcast_email_has_post_link_unsubscribe_and_footer() -> None:
    html, text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "https://blog.example/post/hello" in html
    assert "<p>Body</p>" in html
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in html  # Resend-managed unsubscribe
    assert "Jane Blog" in html and "1 Main St, Town" in html
    assert "Hello" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_subscription_email.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write the builders**

```python
# backend/services/subscription_email.py
"""HTML + plain-text builders for subscription emails.

The post body is the backend-sanitized rendered HTML; we only wrap it. The
unsubscribe link uses Resend's managed merge tag so Resend owns the unsubscribe
flow and suppression."""

from __future__ import annotations

import html as _html

_WRAP_STYLE = "font-family:system-ui,Arial,sans-serif;max-width:640px;margin:0 auto;color:#111"


def build_confirmation_email(*, confirm_url: str, controller_name: str) -> tuple[str, str]:
    safe_name = _html.escape(controller_name)
    safe_url = _html.escape(confirm_url)
    html = (
        f'<div style="{_WRAP_STYLE}">'
        f"<p>Please confirm your subscription to {safe_name}.</p>"
        f'<p><a href="{safe_url}">Confirm my subscription</a></p>'
        f"<p style=\"color:#666;font-size:13px\">If you didn't request this, ignore this email "
        f"and you won't be subscribed.</p>"
        f"</div>"
    )
    text = (
        f"Please confirm your subscription to {controller_name}.\n\n"
        f"Confirm: {confirm_url}\n\n"
        f"If you didn't request this, ignore this email and you won't be subscribed."
    )
    return html, text


def build_broadcast_email(
    *,
    post_url: str,
    post_title: str,
    post_html: str,
    controller_name: str,
    postal_address: str,
) -> tuple[str, str]:
    safe_title = _html.escape(post_title)
    safe_url = _html.escape(post_url)
    safe_name = _html.escape(controller_name)
    safe_addr = _html.escape(postal_address)
    footer = (
        f'<hr style="margin-top:32px;border:none;border-top:1px solid #ddd">'
        f'<p style="color:#666;font-size:12px">'
        f"{safe_name} — {safe_addr}<br>"
        f'<a href="{{{{{{RESEND_UNSUBSCRIBE_URL}}}}}}">Unsubscribe</a></p>'
    )
    html = (
        f'<div style="{_WRAP_STYLE}">'
        f'<p><a href="{safe_url}">{safe_title}</a></p>'
        f"{post_html}"
        f"{footer}"
        f"</div>"
    )
    text = (
        f"{post_title}\n{post_url}\n\n"
        f"Read it online at the link above.\n\n"
        f"{controller_name} — {postal_address}\n"
        f"Unsubscribe: see the link in the HTML version."
    )
    return html, text
```

> Note on the footer: `{{{RESEND_UNSUBSCRIBE_URL}}}` is three literal braces each side; in the f-string they are written as quadruple-then-triple braces to escape. Verify the rendered output literally contains `{{{RESEND_UNSUBSCRIBE_URL}}}` (the test asserts this).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_subscription_email.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/subscription_email.py tests/test_services/test_subscription_email.py
git commit -m "feat: add subscription email builders"
```

---

## Task 7: Service — settings get/update with enable precondition + encryption

**Files:**
- Create: `backend/services/subscription_service.py`
- Test: `tests/test_services/test_subscription_settings.py`

Mirror `backend/services/analytics_service.py` `get/update_analytics_settings` (singleton + IntegrityError race retry). Use `backend/services/crypto_service.py` `encrypt_value`/`decrypt_value`.

- [ ] **Step 1: Write the failing test** (uses the project's async session fixture — find it in `tests/conftest.py`, commonly `db_session`)

```python
# tests/test_services/test_subscription_settings.py
from __future__ import annotations

import pytest

from backend.services import resend_client, subscription_service

SECRET = "s" * 48


@pytest.mark.asyncio
async def test_key_encrypted_and_never_returned(db_session, monkeypatch) -> None:
    await subscription_service.update_settings(
        db_session, secret_key=SECRET, api_key="re_secret", from_email="a@b.com"
    )
    # Stored value is ciphertext, not the plaintext key.
    row = await subscription_service._get_row(db_session)
    assert row.resend_api_key_encrypted not in (None, "re_secret")
    assert subscription_service.decrypt_api_key(row, SECRET) == "re_secret"


@pytest.mark.asyncio
async def test_enable_requires_full_compliance_config(db_session, monkeypatch) -> None:
    monkeypatch.setattr(resend_client, "create_segment", _fake_create_segment)
    # Missing controller fields -> enabling must fail.
    with pytest.raises(subscription_service.EnablePreconditionError):
        await subscription_service.update_settings(
            db_session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
        )
    # With everything set, enabling succeeds and a segment is auto-created.
    await subscription_service.update_settings(
        db_session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com",
        from_name="Jane", controller_name="Jane Blog", controller_contact="jane@b.com",
        privacy_policy_url="https://b.com/privacy", postal_address="1 Main St",
    )
    row = await subscription_service._get_row(db_session)
    assert row.enabled is True
    assert row.resend_segment_id == "seg_auto"


async def _fake_create_segment(*, api_key: str, name: str) -> str:
    return "seg_auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_subscription_settings.py -v`
Expected: FAIL (module/functions missing).

- [ ] **Step 3: Write the settings logic**

```python
# backend/services/subscription_service.py  (PART 1 of 3 — settings)
"""Subscription orchestration: settings, subscribe/confirm, broadcasts.

Stores no subscriber PII. Resend is the system of record for contacts."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.subscription import SubscriptionBroadcast, SubscriptionSettings
from backend.schemas.subscription import SubscriptionSettingsResponse
from backend.services import resend_client
from backend.services.crypto_service import decrypt_value, encrypt_value
from backend.utils.datetime import now_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_SEGMENT_NAME = "AgBlogger subscribers"
_REQUIRED_TO_ENABLE = (
    "from_email",
    "controller_name",
    "controller_contact",
    "privacy_policy_url",
    "postal_address",
)


class EnablePreconditionError(Exception):
    """Raised when enabling is requested without the required compliance config."""


async def _get_row(session: AsyncSession) -> SubscriptionSettings | None:
    result = await session.execute(select(SubscriptionSettings).limit(1))
    return result.scalar_one_or_none()


def decrypt_api_key(row: SubscriptionSettings, secret_key: str) -> str | None:
    if not row.resend_api_key_encrypted:
        return None
    return decrypt_value(row.resend_api_key_encrypted, secret_key)


async def update_settings(
    session: AsyncSession,
    *,
    secret_key: str,
    enabled: bool | None = None,
    api_key: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    controller_name: str | None = None,
    controller_contact: str | None = None,
    privacy_policy_url: str | None = None,
    postal_address: str | None = None,
) -> SubscriptionSettings:
    """Create/update the singleton, encrypting the key and enforcing the enable gate."""
    row = await _get_row(session)
    if row is None:
        row = SubscriptionSettings(id=1)
        session.add(row)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            row = await _get_row(session)
            assert row is not None

    if api_key is not None and api_key != "":
        row.resend_api_key_encrypted = encrypt_value(api_key, secret_key)
    for field, value in (
        ("from_email", from_email),
        ("from_name", from_name),
        ("controller_name", controller_name),
        ("controller_contact", controller_contact),
        ("privacy_policy_url", privacy_policy_url),
        ("postal_address", postal_address),
    ):
        if value is not None:
            setattr(row, field, value)

    if enabled is True:
        await _prepare_enable(session, row, secret_key)
        row.enabled = True
    elif enabled is False:
        row.enabled = False

    row.updated_at = now_utc().isoformat()
    await session.commit()
    await session.refresh(row)
    return row


async def _prepare_enable(
    session: AsyncSession, row: SubscriptionSettings, secret_key: str
) -> None:
    """Validate compliance config and ensure a Resend segment exists before enabling."""
    if not row.resend_api_key_encrypted:
        raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
    missing = [f for f in _REQUIRED_TO_ENABLE if not getattr(row, f)]
    if missing:
        raise EnablePreconditionError(
            "Set these before enabling: " + ", ".join(missing)
        )
    if not row.resend_segment_id:
        api_key = decrypt_api_key(row, secret_key)
        assert api_key is not None
        row.resend_segment_id = await resend_client.create_segment(
            api_key=api_key, name=_SEGMENT_NAME
        )


async def build_settings_response(
    session: AsyncSession, secret_key: str
) -> SubscriptionSettingsResponse:
    row = await _get_row(session)
    if row is None:
        return SubscriptionSettingsResponse(
            enabled=False, from_email=None, from_name=None, controller_name=None,
            controller_contact=None, privacy_policy_url=None, postal_address=None,
            key_configured=False, segment_configured=False, subscriber_count=None,
        )
    count: int | None = None
    api_key = decrypt_api_key(row, secret_key)
    if api_key and row.resend_segment_id:
        try:
            count = await resend_client.count_contacts(
                api_key=api_key, segment_id=row.resend_segment_id
            )
        except resend_client.ResendError:
            count = None
    return SubscriptionSettingsResponse(
        enabled=row.enabled,
        from_email=row.from_email,
        from_name=row.from_name,
        controller_name=row.controller_name,
        controller_contact=row.controller_contact,
        privacy_policy_url=row.privacy_policy_url,
        postal_address=row.postal_address,
        key_configured=bool(row.resend_api_key_encrypted),
        segment_configured=bool(row.resend_segment_id),
        subscriber_count=count,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_subscription_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/subscription_service.py tests/test_services/test_subscription_settings.py
git commit -m "feat: add subscription settings service with enable precondition"
```

---

## Task 8: Service — subscribe + confirm flows

**Files:**
- Modify: `backend/services/subscription_service.py` (PART 2)
- Test: `tests/test_services/test_subscription_flow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services/test_subscription_flow.py
from __future__ import annotations

import pytest

from backend.services import resend_client, subscription_service
from backend.services.subscription_tokens import create_confirm_token

SECRET = "s" * 48


@pytest.mark.asyncio
async def test_subscribe_sends_confirmation_and_stores_nothing(db_session, monkeypatch) -> None:
    sent: dict = {}

    async def fake_send(**kwargs):  # noqa: ANN003
        sent.update(kwargs)
        return "email_1"

    monkeypatch.setattr(resend_client, "send_email", fake_send)
    await _enable(db_session, monkeypatch)

    await subscription_service.subscribe(
        db_session, secret_key=SECRET, email="r@x.com", base_url="https://blog.example"
    )
    assert sent["to"] == "r@x.com"
    assert "subscribe/confirm?token=" in sent["html"]
    # No subscriber table exists at all — nothing is persisted about r@x.com.


@pytest.mark.asyncio
async def test_confirm_creates_contact(db_session, monkeypatch) -> None:
    created: dict = {}

    async def fake_create(**kwargs):  # noqa: ANN003
        created.update(kwargs)

    monkeypatch.setattr(resend_client, "create_contact", fake_create)
    await _enable(db_session, monkeypatch)

    token = create_confirm_token("r@x.com", SECRET)
    ok = await subscription_service.confirm(db_session, secret_key=SECRET, token=token)
    assert ok is True
    assert created["email"] == "r@x.com"
    assert created["segment_id"] == "seg_auto"


@pytest.mark.asyncio
async def test_confirm_rejects_bad_token(db_session, monkeypatch) -> None:
    await _enable(db_session, monkeypatch)
    assert await subscription_service.confirm(db_session, secret_key=SECRET, token="bad") is False


async def _enable(session, monkeypatch) -> None:
    async def fake_segment(**kwargs):  # noqa: ANN003
        return "seg_auto"
    monkeypatch.setattr(resend_client, "create_segment", fake_segment)
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com",
        from_name="Jane", controller_name="Jane Blog", controller_contact="jane@b.com",
        privacy_policy_url="https://b.com/privacy", postal_address="1 Main St",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_subscription_flow.py -v`
Expected: FAIL (`subscribe`/`confirm` missing).

- [ ] **Step 3: Add subscribe/confirm to the service**

```python
# backend/services/subscription_service.py  (PART 2 — append; add imports at top of file)
from backend.services.subscription_email import build_confirmation_email
from backend.services.subscription_tokens import (
    create_confirm_token,
    normalize_email,
    verify_confirm_token,
)


def _from_header(row: SubscriptionSettings) -> str:
    if row.from_name:
        return f"{row.from_name} <{row.from_email}>"
    return row.from_email or ""


async def subscribe(
    session: AsyncSession, *, secret_key: str, email: str, base_url: str
) -> None:
    """Send a confirmation email. Persists nothing. Raises if not configured/enabled."""
    row = await _get_row(session)
    if row is None or not row.enabled:
        raise SubscriptionsDisabledError()
    api_key = decrypt_api_key(row, secret_key)
    if api_key is None or not row.from_email:
        raise SubscriptionsDisabledError()

    token = create_confirm_token(email, secret_key)
    confirm_url = f"{base_url.rstrip('/')}/subscribe/confirm?token={token}"
    html, text = build_confirmation_email(
        confirm_url=confirm_url, controller_name=row.controller_name or row.from_email
    )
    await resend_client.send_email(
        api_key=api_key,
        from_=_from_header(row),
        to=normalize_email(email),
        subject=f"Confirm your subscription to {row.controller_name or row.from_email}",
        html=html,
        text=text,
    )


async def confirm(session: AsyncSession, *, secret_key: str, token: str) -> bool:
    """Verify the token and create the Resend contact. Returns False on bad token."""
    email = verify_confirm_token(token, secret_key)
    if email is None:
        return False
    row = await _get_row(session)
    if row is None or not row.enabled or not row.resend_segment_id:
        return False
    api_key = decrypt_api_key(row, secret_key)
    if api_key is None:
        return False
    await resend_client.create_contact(
        api_key=api_key, segment_id=row.resend_segment_id, email=email
    )
    return True


class SubscriptionsDisabledError(Exception):
    """Subscriptions are disabled or not fully configured."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_subscription_flow.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/subscription_service.py tests/test_services/test_subscription_flow.py
git commit -m "feat: add subscribe and confirm flows"
```

---

## Task 9: Service — broadcast firing + once-guard ledger

**Files:**
- Modify: `backend/services/subscription_service.py` (PART 3)
- Test: `tests/test_services/test_subscription_broadcast.py`

Mirror `analytics_service.fire_background_hit` for the background-task pattern (module-level `set`, `add_done_callback`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services/test_subscription_broadcast.py
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models.subscription import SubscriptionBroadcast
from backend.services import resend_client, subscription_service

SECRET = "s" * 48


@pytest.mark.asyncio
async def test_send_broadcast_records_sent(db_session, monkeypatch) -> None:
    payloads: dict = {}

    async def fake_broadcast(**kwargs):  # noqa: ANN003
        payloads.update(kwargs)
        return "bcast_1"

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)
    await _enable(db_session, monkeypatch)

    await subscription_service.send_broadcast(
        db_session, secret_key=SECRET, post_path="posts/hello/index.md",
        post_title="Hello", post_html="<p>b</p>", post_url="https://blog.example/post/hello",
        trigger="manual",
    )
    rows = (await db_session.execute(select(SubscriptionBroadcast))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "sent"
    assert rows[0].resend_broadcast_id == "bcast_1"
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in payloads["html"]


@pytest.mark.asyncio
async def test_resend_failure_records_failed_not_raised(db_session, monkeypatch) -> None:
    async def boom(**kwargs):  # noqa: ANN003
        raise resend_client.ResendError("nope")

    monkeypatch.setattr(resend_client, "create_and_send_broadcast", boom)
    await _enable(db_session, monkeypatch)

    await subscription_service.send_broadcast(
        db_session, secret_key=SECRET, post_path="p", post_title="t",
        post_html="<p>b</p>", post_url="u", trigger="auto",
    )
    rows = (await db_session.execute(select(SubscriptionBroadcast))).scalars().all()
    assert rows[0].status == "failed" and rows[0].error


@pytest.mark.asyncio
async def test_once_guard_blocks_second_auto_send(db_session, monkeypatch) -> None:
    async def fake_broadcast(**kwargs):  # noqa: ANN003
        return "b"
    monkeypatch.setattr(resend_client, "create_and_send_broadcast", fake_broadcast)
    await _enable(db_session, monkeypatch)

    assert await subscription_service.already_broadcast(db_session, "posts/x/index.md") is False
    await subscription_service.send_broadcast(
        db_session, secret_key=SECRET, post_path="posts/x/index.md", post_title="x",
        post_html="<p>b</p>", post_url="u", trigger="auto",
    )
    assert await subscription_service.already_broadcast(db_session, "posts/x/index.md") is True


async def _enable(session, monkeypatch) -> None:
    async def fake_segment(**kwargs):  # noqa: ANN003
        return "seg_auto"
    monkeypatch.setattr(resend_client, "create_segment", fake_segment)
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com",
        from_name="Jane", controller_name="Jane Blog", controller_contact="jane@b.com",
        privacy_policy_url="https://b.com/privacy", postal_address="1 Main St",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_subscription_broadcast.py -v`
Expected: FAIL.

- [ ] **Step 3: Add broadcast logic**

```python
# backend/services/subscription_service.py  (PART 3 — append)
from backend.services.subscription_email import build_broadcast_email

_broadcast_tasks: set[asyncio.Task[None]] = set()
_MAX_BROADCAST_TASKS = 16


async def already_broadcast(session: AsyncSession, post_path: str) -> bool:
    result = await session.execute(
        select(SubscriptionBroadcast).where(
            SubscriptionBroadcast.post_path == post_path,
            SubscriptionBroadcast.status == "sent",
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def send_broadcast(
    session: AsyncSession,
    *,
    secret_key: str,
    post_path: str,
    post_title: str,
    post_html: str,
    post_url: str,
    trigger: str,
) -> None:
    """Send one broadcast via Resend and record a ledger row. Never raises."""
    row = await _get_row(session)
    record = SubscriptionBroadcast(
        post_path=post_path, post_title=post_title, trigger=trigger,
        status="failed", sent_at=now_utc().isoformat(), error=None,
    )
    try:
        if row is None or not row.enabled or not row.resend_segment_id:
            record.error = "Subscriptions not configured"
        else:
            api_key = decrypt_api_key(row, secret_key)
            if api_key is None or not row.from_email:
                record.error = "Subscriptions not configured"
            else:
                html, text = build_broadcast_email(
                    post_url=post_url, post_title=post_title, post_html=post_html,
                    controller_name=row.controller_name or row.from_email,
                    postal_address=row.postal_address or "",
                )
                broadcast_id = await resend_client.create_and_send_broadcast(
                    api_key=api_key, segment_id=row.resend_segment_id,
                    from_=_from_header(row), subject=post_title, html=html, text=text,
                )
                record.resend_broadcast_id = broadcast_id
                record.status = "sent"
    except resend_client.ResendError as exc:
        record.error = str(exc)
    except Exception as exc:  # never let a broadcast crash the caller
        logger.error("Unexpected broadcast failure for %s", post_path, exc_info=True)
        record.error = "Internal error"
    session.add(record)
    await session.commit()


def fire_post_broadcast(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    secret_key: str,
    post_path: str,
    post_title: str,
    post_html: str,
    post_url: str,
    trigger: str,
    enforce_once_guard: bool,
) -> None:
    """Schedule a fire-and-forget broadcast. Used by the publish hook + manual trigger."""
    if len(_broadcast_tasks) >= _MAX_BROADCAST_TASKS:
        logger.warning("Dropping broadcast for %s: task limit reached", post_path)
        return

    async def _run() -> None:
        try:
            async with session_factory() as session:
                if enforce_once_guard and await already_broadcast(session, post_path):
                    return
                await send_broadcast(
                    session, secret_key=secret_key, post_path=post_path,
                    post_title=post_title, post_html=post_html, post_url=post_url,
                    trigger=trigger,
                )
        except Exception:
            logger.error("Background broadcast failed for %s", post_path, exc_info=True)

    task = asyncio.create_task(_run())
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_subscription_broadcast.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/subscription_service.py tests/test_services/test_subscription_broadcast.py
git commit -m "feat: add broadcast firing and once-guard"
```

---

## Task 10: API routers (public + admin)

**Files:**
- Create: `backend/api/subscriptions.py`
- Test: `tests/test_api/test_subscriptions_api.py`

Use the auth.py rate-limit pattern: `request.app.state.rate_limiter`, `_get_client_ip`. Reuse `get_session`, `get_session_factory`, `get_settings`, `require_admin` from `backend/api/deps.py`. Read an existing API test in `tests/test_api/` for the app/client fixture names.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api/test_subscriptions_api.py
from __future__ import annotations

import pytest

from backend.services import resend_client, subscription_service


@pytest.mark.asyncio
async def test_subscribe_rejected_when_disabled(client) -> None:
    resp = await client.post("/api/subscribe", json={"email": "r@x.com"})
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_subscribe_generic_success(client, monkeypatch, enable_subscriptions) -> None:
    async def fake_send(**kwargs):  # noqa: ANN003
        return "e1"
    monkeypatch.setattr(resend_client, "send_email", fake_send)
    resp = await client.post("/api/subscribe", json={"email": "r@x.com"})
    assert resp.status_code == 200
    assert "confirm" in resp.json()["message"].lower()


@pytest.mark.asyncio
async def test_subscribe_bad_email_422(client, enable_subscriptions) -> None:
    resp = await client.post("/api/subscribe", json={"email": "nope"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_settings_never_returns_key(admin_client, monkeypatch) -> None:
    async def fake_segment(**kwargs):  # noqa: ANN003
        return "seg_auto"
    monkeypatch.setattr(resend_client, "create_segment", fake_segment)
    await admin_client.put("/api/admin/subscriptions/settings", json={"api_key": "re_secret"})
    resp = await admin_client.get("/api/admin/subscriptions/settings")
    body = resp.json()
    assert body["key_configured"] is True
    assert "re_secret" not in resp.text
    assert "api_key" not in body
```

> Add an `enable_subscriptions` fixture in this test file (or `tests/conftest.py`) that calls `subscription_service.update_settings(..., enabled=True, ...)` with `resend_client.create_segment` monkeypatched, against the app's DB. Follow the existing `admin_client` fixture pattern in `tests/test_api/`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api/test_subscriptions_api.py -v`
Expected: FAIL (routes 404 / not registered).

- [ ] **Step 3: Write the routers**

```python
# backend/api/subscriptions.py
"""Subscription endpoints: public subscribe/confirm + admin management."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.deps import (
    get_session,
    get_session_factory,
    get_settings,
    require_admin,
)
from backend.config import Settings
from backend.models.subscription import SubscriptionBroadcast
from backend.models.user import AdminUser
from backend.schemas.subscription import (
    BroadcastListResponse,
    BroadcastSummary,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionSettingsResponse,
    SubscriptionSettingsUpdate,
    TestEmailRequest,
    TriggerBroadcastRequest,
)
from backend.services import resend_client, subscription_service
from backend.services.subscription_service import (
    EnablePreconditionError,
    SubscriptionsDisabledError,
)

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api", tags=["subscriptions"])
page_router = APIRouter(tags=["subscriptions"])  # backend-served HTML (no /api prefix)
admin_router = APIRouter(prefix="/api/admin/subscriptions", tags=["subscriptions-admin"])

_SUBSCRIBE_BURST = (3, 60)       # 3 / minute
_SUBSCRIBE_SUSTAINED = (10, 3600)  # 10 / hour


def _client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    host = request.client.host if request.client and request.client.host else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        from backend.net_utils import is_trusted_proxy
        if is_trusted_proxy(host, settings.trusted_proxy_ips):
            return forwarded.split(",")[0].strip()
    return host


def _enforce_subscribe_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    ip = _client_ip(request)
    for limit, window in (_SUBSCRIBE_BURST, _SUBSCRIBE_SUSTAINED):
        key = f"subscribe:{window}:{ip}"
        limited, retry_after = limiter.is_limited(key, limit, window)
        if limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
    for limit, window in (_SUBSCRIBE_BURST, _SUBSCRIBE_SUSTAINED):
        limiter.add_failure(f"subscribe:{window}:{ip}", window)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@public_router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe_endpoint(
    body: SubscribeRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SubscribeResponse:
    _enforce_subscribe_rate_limit(request)
    try:
        await subscription_service.subscribe(
            session, secret_key=settings.secret_key, email=str(body.email),
            base_url=_base_url(request),
        )
    except SubscriptionsDisabledError as exc:
        raise HTTPException(status_code=404, detail="Subscriptions are not available") from exc
    except resend_client.ResendError:
        # Quota exhaustion / provider hiccup — fail safe, do not leak detail.
        logger.warning("Subscribe confirmation send failed", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Subscriptions are temporarily unavailable"
        ) from None
    return SubscribeResponse()


@page_router.get("/subscribe/confirm", response_class=HTMLResponse)
async def confirm_endpoint(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    ok = False
    try:
        ok = await subscription_service.confirm(
            session, secret_key=settings.secret_key, token=token
        )
    except resend_client.ResendError:
        logger.warning("Confirm contact creation failed", exc_info=True)
    message = (
        "You're subscribed! Thanks for confirming."
        if ok
        else "This confirmation link is invalid or has expired."
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Subscription</title></head>"
        "<body style='font-family:system-ui,Arial,sans-serif;max-width:480px;margin:64px auto;"
        f"text-align:center'><p>{message}</p><p><a href='/'>Back to the blog</a></p></body></html>"
    )
    return HTMLResponse(content=html, status_code=200 if ok else 400)


# ── Admin ────────────────────────────────────────────────────────────────────


@admin_router.get("/settings", response_model=SubscriptionSettingsResponse)
async def get_settings_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> SubscriptionSettingsResponse:
    return await subscription_service.build_settings_response(session, settings.secret_key)


@admin_router.put("/settings", response_model=SubscriptionSettingsResponse)
async def update_settings_endpoint(
    body: SubscriptionSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> SubscriptionSettingsResponse:
    try:
        await subscription_service.update_settings(
            session, secret_key=settings.secret_key, enabled=body.enabled,
            api_key=body.api_key, from_email=body.from_email, from_name=body.from_name,
            controller_name=body.controller_name, controller_contact=body.controller_contact,
            privacy_policy_url=body.privacy_policy_url, postal_address=body.postal_address,
        )
    except EnablePreconditionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except resend_client.ResendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return await subscription_service.build_settings_response(session, settings.secret_key)


@admin_router.post("/test")
async def test_email_endpoint(
    body: TestEmailRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, str]:
    row = await subscription_service._get_row(session)
    if row is None:
        raise HTTPException(status_code=400, detail="Configure Resend first")
    api_key = subscription_service.decrypt_api_key(row, settings.secret_key)
    if api_key is None or not row.from_email:
        raise HTTPException(status_code=400, detail="Configure the API key and from-address first")
    from_ = f"{row.from_name} <{row.from_email}>" if row.from_name else row.from_email
    try:
        await resend_client.send_email(
            api_key=api_key, from_=from_, to=str(body.email),
            subject="AgBlogger test email",
            html="<p>This is a test email from your blog.</p>",
            text="This is a test email from your blog.",
        )
    except resend_client.ResendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": "Test email sent"}


@admin_router.get("/broadcasts", response_model=BroadcastListResponse)
async def list_broadcasts_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> BroadcastListResponse:
    result = await session.execute(
        select(SubscriptionBroadcast).order_by(SubscriptionBroadcast.id.desc()).limit(100)
    )
    rows = result.scalars().all()
    return BroadcastListResponse(
        broadcasts=[
            BroadcastSummary(
                id=r.id, post_path=r.post_path, post_title=r.post_title,
                resend_broadcast_id=r.resend_broadcast_id, trigger=r.trigger,
                status=r.status, sent_at=r.sent_at, error=r.error,
            )
            for r in rows
        ]
    )


@admin_router.post("/broadcasts")
async def trigger_broadcast_endpoint(
    body: TriggerBroadcastRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> dict[str, str]:
    from backend.models.post import PostCache

    result = await session.execute(
        select(PostCache).where(PostCache.file_path == body.post_path)
    )
    post = result.scalar_one_or_none()
    if post is None or post.is_draft:
        raise HTTPException(status_code=404, detail="Published post not found")
    post_url = f"{_base_url_from_settings(settings)}/post/{_slug(post.file_path)}"
    subscription_service.fire_post_broadcast(
        session_factory, secret_key=settings.secret_key, post_path=post.file_path,
        post_title=post.title, post_html=post.rendered_html or "", post_url=post_url,
        trigger="manual", enforce_once_guard=False,
    )
    return {"message": "Broadcast started"}


def _slug(file_path: str) -> str:
    from backend.utils.slug import file_path_to_slug
    return file_path_to_slug(file_path)


def _base_url_from_settings(settings: Settings) -> str:
    # Manual trigger has no request context for base_url; derive from the
    # public post URL convention. If a configured public base URL exists, prefer it.
    return getattr(settings, "public_base_url", "") or ""
```

> Note: for the manual trigger, `request.base_url` *is* available (the admin endpoint has a `Request` via dependency if added). Prefer passing `_base_url(request)` like the public endpoint — add `request: Request` to `trigger_broadcast_endpoint` and use `_base_url(request)` instead of `_base_url_from_settings`, to match the auto path. Keep `_slug` for the post path→slug conversion.

- [ ] **Step 4: Register routers in main.py.** In `backend/main.py`, near the other `app.include_router(...)` calls (~line 992-1003), add:

```python
from backend.api.subscriptions import (
    admin_router as subscriptions_admin_router,
    page_router as subscriptions_page_router,
    public_router as subscriptions_public_router,
)

app.include_router(subscriptions_public_router)
app.include_router(subscriptions_admin_router)
app.include_router(subscriptions_page_router)
```

The `subscriptions_page_router` (serving `/subscribe/confirm`) must be registered **before** the StaticFiles catch-all so it is not shadowed (same as the SEO routes).

- [ ] **Step 5: Close the Resend client in lifespan shutdown.** In `backend/main.py` lifespan shutdown (next to `close_analytics_client()` ~line 604-607):

```python
from backend.services.resend_client import close_resend_client
...
await close_resend_client()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_api/test_subscriptions_api.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/api/subscriptions.py backend/main.py tests/test_api/test_subscriptions_api.py tests/conftest.py
git commit -m "feat: add subscription API endpoints"
```

---

## Task 11: Publish hook — auto-broadcast on draft→published

**Files:**
- Modify: `backend/api/posts.py` (create endpoint ~921; update endpoint ~981 + ~1154)
- Test: `tests/test_api/test_post_publish_broadcast.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api/test_post_publish_broadcast.py
from __future__ import annotations

import pytest

from backend.services import subscription_service


@pytest.mark.asyncio
async def test_publishing_post_fires_broadcast(admin_client, monkeypatch, enable_subscriptions) -> None:
    calls: list[dict] = []

    def fake_fire(session_factory, **kwargs):  # noqa: ANN003
        calls.append(kwargs)

    monkeypatch.setattr(subscription_service, "fire_post_broadcast", fake_fire)

    # Create a draft, then update it to published.
    created = await admin_client.post(
        "/api/posts", json={"title": "Hello", "subtitle": "", "body": "# Hi", "labels": [], "is_draft": True},
    )
    path = created.json()["file_path"]
    await admin_client.put(
        f"/api/posts/{path}",
        json={"title": "Hello", "subtitle": "", "body": "# Hi", "labels": [], "is_draft": False},
    )
    assert any(c["trigger"] == "auto" and c["enforce_once_guard"] for c in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api/test_post_publish_broadcast.py -v`
Expected: FAIL (no broadcast fired).

- [ ] **Step 3a: Hook the update endpoint.** In `backend/api/posts.py`, in `update_post_endpoint`, capture the transition where the draft check already exists (line ~981) *before* `existing.is_draft` is overwritten:

```python
        # Draft → published transition: update created_at to publish time
        is_publish_transition = existing.is_draft and not body.is_draft
        if is_publish_transition:
            created_at = now
```

Then **after** the successful commit + git commit (after line ~1158, before `return await _build_post_detail(...)`), add:

```python
        if is_publish_transition:
            _fire_subscription_broadcast(request, existing)
```

`update_post_endpoint` does not currently take `request: Request`. Add `request: Request` to its signature (FastAPI injects it). Add the helper near the top of `posts.py`:

```python
def _fire_subscription_broadcast(request: Request, post: PostCache) -> None:
    """Fire an auto-broadcast for a newly published post (best-effort)."""
    from backend.services import subscription_service
    from backend.utils.slug import file_path_to_slug

    settings = request.app.state.settings
    session_factory = request.app.state.session_factory
    base_url = str(request.base_url).rstrip("/")
    subscription_service.fire_post_broadcast(
        session_factory,
        secret_key=settings.secret_key,
        post_path=post.file_path,
        post_title=post.title,
        post_html=post.rendered_html or "",
        post_url=f"{base_url}/post/{file_path_to_slug(post.file_path)}",
        trigger="auto",
        enforce_once_guard=True,
    )
```

- [ ] **Step 3b: Hook the create endpoint.** In `create_post_endpoint`, after `await session.commit()` + git commit (after line ~925, before `return await _build_post_detail(...)`), add:

```python
        if not post_data.is_draft:
            _fire_subscription_broadcast(request, post)
```

Add `request: Request` to `create_post_endpoint`'s signature.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api/test_post_publish_broadcast.py -v`
Expected: PASS.

- [ ] **Step 5: Run the posts test suite to confirm no regressions**

Run: `uv run pytest tests/test_api/ -k post -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_post_publish_broadcast.py
git commit -m "feat: auto-broadcast on post publish transition"
```

---

## Task 12: Expose `subscriptions_enabled` in site config

**Files:**
- Modify: `backend/schemas/page.py`, `backend/services/page_service.py`, `backend/api/pages.py`
- Test: `tests/test_api/test_site_config_subscriptions_flag.py`

Inspect `backend/services/page_service.py::get_site_config` to see its current signature (likely takes only `content_manager`). It needs the DB to read the enabled flag.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api/test_site_config_subscriptions_flag.py
from __future__ import annotations

import pytest

from backend.services import resend_client, subscription_service


@pytest.mark.asyncio
async def test_site_config_reports_subscriptions_disabled_by_default(client) -> None:
    resp = await client.get("/api/pages")
    assert resp.status_code == 200
    assert resp.json()["subscriptions_enabled"] is False


@pytest.mark.asyncio
async def test_site_config_reports_enabled(client, db_session, monkeypatch) -> None:
    async def fake_segment(**kwargs):  # noqa: ANN003
        return "seg_auto"
    monkeypatch.setattr(resend_client, "create_segment", fake_segment)
    await subscription_service.update_settings(
        db_session, secret_key="s" * 48, enabled=True, api_key="re_x", from_email="a@b.com",
        from_name="J", controller_name="J", controller_contact="j@b.com",
        privacy_policy_url="https://b/p", postal_address="x",
    )
    resp = await client.get("/api/pages")
    assert resp.json()["subscriptions_enabled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api/test_site_config_subscriptions_flag.py -v`
Expected: FAIL (`subscriptions_enabled` missing).

- [ ] **Step 3a: Add the field to the schema.**

```python
# backend/schemas/page.py — in SiteConfigResponse
class SiteConfigResponse(BaseModel):
    title: str
    description: str
    pages: list[PageConfig]
    subscriptions_enabled: bool = False
```

- [ ] **Step 3b: Read the flag in the service.** Add a helper to `subscription_service.py`:

```python
async def is_enabled(session: AsyncSession) -> bool:
    row = await _get_row(session)
    return bool(row and row.enabled)
```

- [ ] **Step 3c: Populate it in the endpoint.** Change `site_config` in `backend/api/pages.py` to take a session and set the flag:

```python
@router.get("", response_model=SiteConfigResponse)
async def site_config(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteConfigResponse:
    """Get site configuration including page list."""
    config = get_site_config(content_manager)
    config.subscriptions_enabled = await subscription_service.is_enabled(session)
    return config
```

Add imports to `pages.py`: `from backend.api.deps import get_session`, `from sqlalchemy.ext.asyncio import AsyncSession`, `from backend.services import subscription_service`. Confirm `get_site_config` returns a `SiteConfigResponse` instance that allows attribute assignment (it's a Pydantic model — assignment works since `model_config` default allows it; if it's frozen, build a copy with `model_copy(update={...})`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api/test_site_config_subscriptions_flag.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/page.py backend/services/page_service.py backend/services/subscription_service.py backend/api/pages.py tests/test_api/test_site_config_subscriptions_flag.py
git commit -m "feat: expose subscriptions_enabled in site config"
```

---

## Task 13: Backend full gate

- [ ] **Step 1: Run the backend gate**

Run: `just check-backend`
Expected: PASS (ruff, mypy strict, basedpyright, all backend tests). Fix any type/lint issues by adapting code (no `type: ignore`/`noqa`; ask the user if a suppression seems unavoidable).

- [ ] **Step 2: Commit any fixes**

```bash
git add -A
git commit -m "chore: satisfy backend static checks for subscriptions"
```

---

## Task 14: Frontend API module + client types

> Frontend tasks: use the `vercel-react-best-practices` and `frontend-design` skills; disable controls during async; verify in the browser with Playwright; remove screenshots after.

**Files:**
- Create: `frontend/src/api/subscriptions.ts`
- Modify: `frontend/src/api/client.ts` (add types), `frontend/src/stores/siteStore.ts` (`subscriptions_enabled`)
- Test: `frontend/src/api/__tests__/subscriptions.test.ts`

- [ ] **Step 1: Write the failing test** (mirror an existing `frontend/src/api/__tests__` test that mocks `api`)

```typescript
// frontend/src/api/__tests__/subscriptions.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { subscribe } from '@/api/subscriptions'
import api from '@/api/client'

vi.mock('@/api/client', () => ({
  default: { post: vi.fn(() => ({ json: () => Promise.resolve({ message: 'ok' }) })) },
}))

describe('subscriptions api', () => {
  beforeEach(() => vi.clearAllMocks())
  it('posts the email to /api/subscribe', async () => {
    const res = await subscribe('r@x.com')
    expect(api.post).toHaveBeenCalledWith('subscribe', { json: { email: 'r@x.com' } })
    expect(res.message).toBe('ok')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-frontend`
Expected: FAIL (module missing).

- [ ] **Step 3: Write the API module**

```typescript
// frontend/src/api/subscriptions.ts
import api from './client'

export interface SubscribeResponse { message: string }

export interface SubscriptionSettings {
  enabled: boolean
  from_email: string | null
  from_name: string | null
  controller_name: string | null
  controller_contact: string | null
  privacy_policy_url: string | null
  postal_address: string | null
  key_configured: boolean
  segment_configured: boolean
  subscriber_count: number | null
}

export interface BroadcastSummary {
  id: number
  post_path: string
  post_title: string
  resend_broadcast_id: string | null
  trigger: string
  status: string
  sent_at: string
  error: string | null
}

export async function subscribe(email: string): Promise<SubscribeResponse> {
  return api.post('subscribe', { json: { email } }).json<SubscribeResponse>()
}

export async function fetchSubscriptionSettings(): Promise<SubscriptionSettings> {
  return api.get('admin/subscriptions/settings').json<SubscriptionSettings>()
}

export async function updateSubscriptionSettings(
  patch: Partial<Record<string, unknown>>,
): Promise<SubscriptionSettings> {
  return api.put('admin/subscriptions/settings', { json: patch }).json<SubscriptionSettings>()
}

export async function sendTestEmail(email: string): Promise<{ message: string }> {
  return api.post('admin/subscriptions/test', { json: { email } }).json<{ message: string }>()
}

export async function fetchBroadcasts(): Promise<{ broadcasts: BroadcastSummary[] }> {
  return api.get('admin/subscriptions/broadcasts').json<{ broadcasts: BroadcastSummary[] }>()
}

export async function triggerBroadcast(postPath: string): Promise<{ message: string }> {
  return api
    .post('admin/subscriptions/broadcasts', { json: { post_path: postPath } })
    .json<{ message: string }>()
}
```

- [ ] **Step 4: Add `subscriptions_enabled` to the site config type + store.** In `frontend/src/stores/siteStore.ts`, extend the config type with `subscriptions_enabled: boolean` (default `false` when reading). Check `frontend/src/api/client.ts` for the `SiteConfig` interface and add the field there.

- [ ] **Step 5: Run test to verify it passes**

Run: `just test-frontend`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/subscriptions.ts frontend/src/api/client.ts frontend/src/stores/siteStore.ts frontend/src/api/__tests__/subscriptions.test.ts
git commit -m "feat: add subscriptions frontend API module"
```

---

## Task 15: Public SubscribePage + route + header link

**Files:**
- Create: `frontend/src/pages/SubscribePage.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/layout/Header.tsx`
- Test: `frontend/src/pages/__tests__/SubscribePage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/__tests__/SubscribePage.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SubscribePage from '@/pages/SubscribePage'
import * as apiMod from '@/api/subscriptions'

vi.mock('@/api/subscriptions')

describe('SubscribePage', () => {
  it('submits the email and shows a confirmation message', async () => {
    vi.mocked(apiMod.subscribe).mockResolvedValue({ message: 'Please check your inbox to confirm your subscription.' })
    render(<SubscribePage />)
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'r@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: /subscribe/i }))
    await waitFor(() => expect(apiMod.subscribe).toHaveBeenCalledWith('r@x.com'))
    expect(await screen.findByText(/check your inbox/i)).toBeInTheDocument()
  })

  it('shows the GDPR layered notice', () => {
    render(<SubscribePage />)
    expect(screen.getByText(/privacy/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-frontend`
Expected: FAIL (page missing).

- [ ] **Step 3: Write the page** (use the `frontend-design` skill for the visual treatment; this is the functional baseline — disable controls while submitting). Read the controller/privacy info from `siteStore` config where available; the notice text is static plus the privacy-policy link.

```tsx
// frontend/src/pages/SubscribePage.tsx
import { useState } from 'react'
import { subscribe } from '@/api/subscriptions'
import { HTTPError } from '@/api/client'

export default function SubscribePage() {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await subscribe(email)
      setDone(true)
    } catch (err) {
      setError(
        err instanceof HTTPError && err.response.status === 429
          ? 'Too many requests. Please try again later.'
          : 'Subscriptions are currently unavailable. Please try again later.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (done) {
    return (
      <div className="max-w-md mx-auto text-center py-16">
        <p className="text-ink">Please check your inbox to confirm your subscription.</p>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto py-12">
      <h1 className="font-display text-3xl text-ink mb-6">Subscribe</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <label htmlFor="sub-email" className="block text-sm text-muted">Email</label>
        <input
          id="sub-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={submitting}
          className="w-full border border-border rounded px-3 py-2 bg-paper text-ink disabled:opacity-50"
        />
        {error !== null && <p className="text-red-600 text-sm">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="px-4 py-2 bg-accent text-white rounded disabled:opacity-50"
        >
          {submitting ? 'Subscribing…' : 'Subscribe'}
        </button>
      </form>
      <p className="text-xs text-muted mt-6 leading-relaxed">
        We use your email only to notify you of new posts, based on your consent. Email is
        delivered by Resend (Resend Inc., USA) as our processor; this involves a transfer
        outside the EEA under appropriate safeguards. We keep your address until you
        unsubscribe (a link is in every email). You can withdraw consent at any time and
        lodge a complaint with a supervisory authority. See our{' '}
        <a href="/page/privacy" className="underline">Privacy Policy</a>.
      </p>
    </div>
  )
}
```

> If `controller_name`/`privacy_policy_url` are exposed publicly later, render them dynamically. For v1 the notice is static text + a privacy-policy link; confirm the privacy page path with the user (default `/page/privacy`).

- [ ] **Step 4: Add the route.** In `frontend/src/App.tsx`, add to the children array and a lazy import:

```tsx
const SubscribePage = lazy(() => import("@/pages/SubscribePage"));
// ...
      { path: "/subscribe", element: <SubscribePage /> },
```

- [ ] **Step 5: Add the header link.** In `frontend/src/components/layout/Header.tsx`, read `subscriptions_enabled` from `siteStore` and render a `<Link to="/subscribe">Subscribe</Link>` only when true. Match the existing header link styling.

- [ ] **Step 6: Run test to verify it passes**

Run: `just test-frontend`
Expected: PASS.

- [ ] **Step 7: Browser-verify with Playwright** that `/subscribe` renders, the link appears only when enabled, and submit shows the confirmation. Remove screenshots.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/SubscribePage.tsx frontend/src/App.tsx frontend/src/components/layout/Header.tsx frontend/src/pages/__tests__/SubscribePage.test.tsx
git commit -m "feat: add public subscribe page and header link"
```

---

## Task 16: Admin Subscriptions tab

**Files:**
- Create: `frontend/src/components/admin/SubscriptionsPanel.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Test: `frontend/src/components/admin/__tests__/SubscriptionsPanel.test.tsx`

Model the panel on `frontend/src/components/admin/AnalyticsPanel.tsx` (props `busy`, `onBusyChange`). Read it first.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/admin/__tests__/SubscriptionsPanel.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SubscriptionsPanel from '@/components/admin/SubscriptionsPanel'
import * as apiMod from '@/api/subscriptions'

vi.mock('@/api/subscriptions')

describe('SubscriptionsPanel', () => {
  it('shows subscriber count and key status', async () => {
    vi.mocked(apiMod.fetchSubscriptionSettings).mockResolvedValue({
      enabled: true, from_email: 'a@b.com', from_name: 'J', controller_name: 'J',
      controller_contact: 'j@b.com', privacy_policy_url: 'https://b/p', postal_address: 'x',
      key_configured: true, segment_configured: true, subscriber_count: 42,
    })
    vi.mocked(apiMod.fetchBroadcasts).mockResolvedValue({ broadcasts: [] })
    render(<SubscriptionsPanel busy={false} onBusyChange={() => {}} />)
    expect(await screen.findByText(/42/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/configured/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-frontend`
Expected: FAIL (panel missing).

- [ ] **Step 3: Write the panel.** Implement (use `frontend-design` skill for polish; disable controls while busy):
  - Load settings + broadcasts on mount (SWR or `useEffect`, matching `AnalyticsPanel`).
  - **Settings form:** enable toggle (disabled with a tooltip/message until `key_configured` + compliance fields + `from_email` are filled); API key input (write-only, placeholder shows "configured ✓"/"not set", only sends `api_key` when non-empty); from email/name; controller name/contact; privacy policy URL; postal address; Save (calls `updateSubscriptionSettings`). On a 400 `EnablePreconditionError`, show the returned detail.
  - **Subscribers:** display `subscriber_count` (or "unavailable").
  - **Send to subscribers:** a published-post selector (fetch `GET /api/posts`, filter non-drafts) + "Send broadcast" with a `window.confirm("Email subscribers about '<title>'?")` guard → `triggerBroadcast(path)`.
  - **Broadcast history:** table from `fetchBroadcasts()` (title, date, status, error).
  - "Send test email" button → prompt for/use an email → `sendTestEmail`.
  - Call `onBusyChange(true/false)` around async work (matches AnalyticsPanel contract).

```tsx
// frontend/src/components/admin/SubscriptionsPanel.tsx
import { useEffect, useState } from 'react'
import {
  fetchSubscriptionSettings,
  updateSubscriptionSettings,
  fetchBroadcasts,
  sendTestEmail,
  triggerBroadcast,
  type SubscriptionSettings,
  type BroadcastSummary,
} from '@/api/subscriptions'

interface Props { busy: boolean; onBusyChange: (b: boolean) => void }

export default function SubscriptionsPanel({ busy, onBusyChange }: Props) {
  const [settings, setSettings] = useState<SubscriptionSettings | null>(null)
  const [broadcasts, setBroadcasts] = useState<BroadcastSummary[]>([])
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        setSettings(await fetchSubscriptionSettings())
        setBroadcasts((await fetchBroadcasts()).broadcasts)
      } catch {
        setError('Failed to load subscription settings.')
      }
    })()
  }, [])

  if (settings === null) return <p className="text-muted">Loading…</p>

  function update<K extends keyof SubscriptionSettings>(key: K, value: SubscriptionSettings[K]) {
    setSettings((s) => (s === null ? s : { ...s, [key]: value }))
  }

  async function save(patch: Record<string, unknown>) {
    onBusyChange(true)
    setError(null)
    setMessage(null)
    try {
      const next = await updateSubscriptionSettings(patch)
      setSettings(next)
      setApiKey('')
      setMessage('Saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
    } finally {
      onBusyChange(false)
    }
  }

  return (
    <div className="space-y-8">
      {error !== null && <p className="text-red-600 text-sm">{error}</p>}
      {message !== null && <p className="text-green-600 text-sm">{message}</p>}

      <section className="space-y-3">
        <h2 className="font-display text-xl text-ink">Settings</h2>
        <p className="text-sm text-muted">
          Subscribers: {settings.subscriber_count ?? 'unavailable'} · API key:{' '}
          {settings.key_configured ? 'configured ✓' : 'not set'}
        </p>
        {/* API key (write-only) */}
        <label className="block text-sm text-muted">Resend API key</label>
        <input
          type="password"
          value={apiKey}
          disabled={busy}
          placeholder={settings.key_configured ? 'configured ✓ (enter to replace)' : 'not set'}
          onChange={(e) => setApiKey(e.target.value)}
          className="w-full border border-border rounded px-3 py-2 bg-paper disabled:opacity-50"
        />
        {/* From + compliance fields */}
        {([
          ['from_email', 'From email'],
          ['from_name', 'From name'],
          ['controller_name', 'Data controller name'],
          ['controller_contact', 'Controller contact'],
          ['privacy_policy_url', 'Privacy policy URL'],
          ['postal_address', 'Postal address (email footer)'],
        ] as const).map(([key, label]) => (
          <div key={key}>
            <label className="block text-sm text-muted">{label}</label>
            <input
              value={(settings[key] as string | null) ?? ''}
              disabled={busy}
              onChange={(e) => update(key, e.target.value as never)}
              className="w-full border border-border rounded px-3 py-2 bg-paper disabled:opacity-50"
            />
          </div>
        ))}
        <button
          disabled={busy}
          onClick={() =>
            void save({
              api_key: apiKey || undefined,
              from_email: settings.from_email,
              from_name: settings.from_name,
              controller_name: settings.controller_name,
              controller_contact: settings.controller_contact,
              privacy_policy_url: settings.privacy_policy_url,
              postal_address: settings.postal_address,
            })
          }
          className="px-4 py-2 bg-accent text-white rounded disabled:opacity-50"
        >
          Save
        </button>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={busy}
            onChange={(e) => void save({ enabled: e.target.checked })}
          />
          Enable subscriptions
        </label>
      </section>

      <section className="space-y-2">
        <h2 className="font-display text-xl text-ink">Broadcast history</h2>
        {broadcasts.length === 0 ? (
          <p className="text-sm text-muted">No broadcasts yet.</p>
        ) : (
          <ul className="text-sm text-ink space-y-1">
            {broadcasts.map((b) => (
              <li key={b.id}>
                {b.sent_at} — {b.post_title} — <span>{b.status}</span>
                {b.error !== null && <span className="text-red-600"> ({b.error})</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
```

> The post-picker "Send to subscribers" and "Send test email" controls: add them following the same disabled-while-busy pattern, calling `triggerBroadcast` (behind `window.confirm`) and `sendTestEmail`. Keep each control disabled during async.

- [ ] **Step 4: Add the tab to AdminPage.** In `frontend/src/pages/AdminPage.tsx`: add `{ key: 'subscriptions', label: 'Subscriptions' }` to `ADMIN_TABS`; lazy-import the panel (`const SubscriptionsPanel = lazy(() => import('@/components/admin/SubscriptionsPanel'))`); add a `subscriptionsBusy` state into the `busy` aggregate; render it under `activeTab === 'subscriptions'` inside `<Suspense>` (mirror the analytics tab block).

- [ ] **Step 5: Run test to verify it passes**

Run: `just test-frontend`
Expected: PASS.

- [ ] **Step 6: Browser-verify with Playwright** the tab loads, the enable toggle is gated by the precondition, saving works, and the history renders. Remove screenshots.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/admin/SubscriptionsPanel.tsx frontend/src/pages/AdminPage.tsx frontend/src/components/admin/__tests__/SubscriptionsPanel.test.tsx
git commit -m "feat: add admin subscriptions panel"
```

---

## Task 17: Documentation

**Files:**
- Create: `docs/arch/subscriptions.md`
- Modify: `docs/arch/index.md`, `backend.md`, `data-flow.md`, `security.md`, `frontend.md`, `deployment.md`

- [ ] **Step 1: Write `docs/arch/subscriptions.md`** — succinct, matching the existing arch-doc style. Cover: the store-zero-PII principle (Resend is system of record); the `subscription_settings` + `subscription_broadcasts` durable tables; stateless signed-token double opt-in; the publish→Resend-broadcast flow; managed unsubscribe; the enable precondition; code entry points (`backend/services/subscription_service.py`, `backend/services/resend_client.py`, `backend/api/subscriptions.py`, `frontend/src/components/admin/SubscriptionsPanel.tsx`).

- [ ] **Step 2: Update the other docs** with one-to-three-line references:
  - `index.md`: add a "Read subscriptions.md for …" line + entry point.
  - `backend.md`: new durable tables (Alembic-managed), the Resend integration, no separate DB.
  - `data-flow.md`: publish → fire background Resend broadcast.
  - `security.md`: store-zero-PII, Resend key encrypted at rest (SECRET_KEY) and confirm-token signing, subscribe rate limit + transactional-quota protection, controllership retained.
  - `frontend.md`: `/subscribe` route + admin Subscriptions tab.
  - `deployment.md`: operator must own/verify a sending domain + sign Resend's DPA; SECRET_KEY now also protects the Resend key and signs confirm tokens; free-tier limits (marketing unlimited ≤1,000 contacts; confirmations are transactional 100/day, 3,000/mo).

- [ ] **Step 3: Commit**

```bash
git add docs/arch/
git commit -m "docs: document subscriptions architecture"
```

---

## Task 18: Final full gate

- [ ] **Step 1: Run the complete gate**

Run: `just check`
Expected: PASS (backend static + tests, frontend static + tests, coverage targets). Fix issues by adapting code; do not suppress checks without asking the user.

- [ ] **Step 2: Manual end-to-end smoke (optional but recommended)** with `just start`, real or test Resend key in a dev account: enable in admin → subscribe → confirm link → publish a post → verify a broadcast row appears. Then `just stop`.

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: finalize subscriptions feature"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** every spec section maps to a task — settings/ledger model (T1-2), stateless confirm token (T3), schemas (T4), Resend client (T5), emails (T6), settings+precondition (T7), subscribe/confirm (T8), broadcast+once-guard (T9), API incl. rate limit + generic responses + key-never-returned (T10), publish hook (T11), header flag (T12), frontend (T14-16), GDPR notice (T15), docs incl. free-tier + domain note (T17).
- **Resend endpoints** (contacts/broadcasts/segments paths) are the one external unknown — verify against the live API reference per the caveat at the top; the handling code is correct regardless.
- **No PII** is written anywhere: grep the final diff for any `email` column or subscriber persistence and confirm there is none outside transient request handling and the signed token.
- **Base URL** for confirm + post links is request-derived (`request.base_url`); ensure proxy headers are correct in deployment (same dependency as existing SEO absolute URLs).
