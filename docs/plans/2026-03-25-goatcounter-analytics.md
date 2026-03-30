# GoatCounter Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fully server-internal GoatCounter analytics integration — hit recording, admin dashboard with charts, and optional public view counts on posts.

**Architecture:** GoatCounter runs as a sidecar Docker container on the internal network. The AgBlogger backend records hits server-side when serving posts/pages and proxies GoatCounter's stats API for an admin dashboard. No public GoatCounter exposure.

**Tech Stack:** GoatCounter (Docker), httpx (async HTTP client), crawlerdetect (bot filtering), Alembic (migration), Recharts (frontend charts), Pydantic (schemas)

**Spec:** `docs/specs/2026-03-24-goatcounter-analytics-design.md`

---

### Task 1: Analytics Settings — Database Model & Migration

**Files:**
- Create: `backend/models/analytics.py`
- Modify: `backend/models/__init__.py`
- Create: `backend/migrations/versions/0002_analytics_settings.py`
- Test: `tests/test_services/test_analytics_settings.py`

- [ ] **Step 1: Write failing test for analytics settings model**

```python
"""Tests for analytics settings persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from backend.models.analytics import AnalyticsSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.anyio
async def test_default_analytics_settings(db_session: AsyncSession) -> None:
    """Fresh database has no settings row — service should use defaults."""
    result = await db_session.execute(select(AnalyticsSettings))
    assert result.scalar_one_or_none() is None


@pytest.mark.anyio
async def test_create_analytics_settings(db_session: AsyncSession) -> None:
    """Can create and persist analytics settings."""
    settings = AnalyticsSettings(analytics_enabled=False, show_views_on_posts=True)
    db_session.add(settings)
    await db_session.commit()

    result = await db_session.execute(select(AnalyticsSettings))
    row = result.scalar_one()
    assert row.analytics_enabled is False
    assert row.show_views_on_posts is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend` (or `pytest tests/test_services/test_analytics_settings.py -v`)
Expected: ImportError — `backend.models.analytics` does not exist

- [ ] **Step 3: Create the analytics settings model**

Create `backend/models/analytics.py`:

```python
"""Analytics settings model."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import DurableBase


class AnalyticsSettings(DurableBase):
    """Singleton row storing analytics configuration."""

    __tablename__ = "analytics_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_views_on_posts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 4: Register the model in `backend/models/__init__.py`**

Add `AnalyticsSettings` to the imports and `__all__` list.

- [ ] **Step 5: Create Alembic migration**

Create `backend/migrations/versions/0002_analytics_settings.py`:

```python
"""analytics settings

Revision ID: a1b2c3d4e5f6
Revises: f11ad63c6789
Create Date: 2026-03-25
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f11ad63c6789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("show_views_on_posts", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("analytics_settings")
```

Note: Generate the actual revision ID with `alembic revision` or use a unique hex string. The `down_revision` must match the existing `0001` migration's revision ID (`f11ad63c6789`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_services/test_analytics_settings.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/models/analytics.py backend/models/__init__.py \
  backend/migrations/versions/0002_analytics_settings.py \
  tests/test_services/test_analytics_settings.py
git commit -m "feat: add analytics settings durable model and migration"
```

---

### Task 2: Analytics Schemas

**Files:**
- Create: `backend/schemas/analytics.py`

- [ ] **Step 1: Create Pydantic schemas for analytics API**

```python
"""Analytics API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsSettingsResponse(BaseModel):
    """Current analytics settings."""

    analytics_enabled: bool
    show_views_on_posts: bool


class AnalyticsSettingsUpdate(BaseModel):
    """Request body for updating analytics settings."""

    analytics_enabled: bool | None = None
    show_views_on_posts: bool | None = None


class ViewCountResponse(BaseModel):
    """Public view count for a single post."""

    views: int | None = None


class TotalStatsResponse(BaseModel):
    """Total pageview statistics."""

    total_views: int
    total_unique: int


class PathHit(BaseModel):
    """Per-path hit data."""

    path: str
    views: int
    unique: int


class PathHitsResponse(BaseModel):
    """Per-path hit statistics."""

    paths: list[PathHit] = Field(default_factory=list)


class ReferrerEntry(BaseModel):
    """Referrer data for a path."""

    referrer: str
    count: int


class PathReferrersResponse(BaseModel):
    """Referrer breakdown for a specific path."""

    path_id: int
    referrers: list[ReferrerEntry] = Field(default_factory=list)


class BreakdownEntry(BaseModel):
    """Browser/OS/etc. breakdown entry."""

    name: str
    count: int
    percent: float


class BreakdownResponse(BaseModel):
    """Breakdown by category (browser, OS, etc.)."""

    category: str
    entries: list[BreakdownEntry] = Field(default_factory=list)
```

- [ ] **Step 2: Commit**

```bash
git add backend/schemas/analytics.py
git commit -m "feat: add analytics API schemas"
```

---

### Task 3: Analytics Service — Settings Management

**Files:**
- Create: `backend/services/analytics_service.py`
- Test: `tests/test_services/test_analytics_service.py`

- [ ] **Step 1: Write failing tests for settings management**

```python
"""Tests for analytics service — settings management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from backend.models.analytics import AnalyticsSettings
from backend.services.analytics_service import get_analytics_settings, update_analytics_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.anyio
async def test_get_default_settings(db_session: AsyncSession) -> None:
    """Returns defaults when no settings row exists."""
    settings = await get_analytics_settings(db_session)
    assert settings.analytics_enabled is True
    assert settings.show_views_on_posts is False


@pytest.mark.anyio
async def test_update_settings_creates_row(db_session: AsyncSession) -> None:
    """First update creates the settings row."""
    result = await update_analytics_settings(
        db_session, analytics_enabled=False, show_views_on_posts=True
    )
    assert result.analytics_enabled is False
    assert result.show_views_on_posts is True

    # Verify persisted
    row = (await db_session.execute(select(AnalyticsSettings))).scalar_one()
    assert row.analytics_enabled is False


@pytest.mark.anyio
async def test_update_settings_partial(db_session: AsyncSession) -> None:
    """Partial update only changes specified fields."""
    await update_analytics_settings(db_session, analytics_enabled=False)
    result = await update_analytics_settings(db_session, show_views_on_posts=True)
    assert result.analytics_enabled is False  # unchanged
    assert result.show_views_on_posts is True  # updated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_analytics_service.py -v`
Expected: ImportError — `backend.services.analytics_service` does not exist

- [ ] **Step 3: Implement settings management**

Create `backend/services/analytics_service.py`:

```python
"""Analytics service: settings management and GoatCounter integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.analytics import AnalyticsSettings
from backend.schemas.analytics import AnalyticsSettingsResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_analytics_settings(session: AsyncSession) -> AnalyticsSettingsResponse:
    """Get current analytics settings, returning defaults if no row exists."""
    result = await session.execute(select(AnalyticsSettings))
    row = result.scalar_one_or_none()
    if row is None:
        return AnalyticsSettingsResponse(analytics_enabled=True, show_views_on_posts=False)
    return AnalyticsSettingsResponse(
        analytics_enabled=row.analytics_enabled,
        show_views_on_posts=row.show_views_on_posts,
    )


async def update_analytics_settings(
    session: AsyncSession,
    *,
    analytics_enabled: bool | None = None,
    show_views_on_posts: bool | None = None,
) -> AnalyticsSettingsResponse:
    """Update analytics settings. Creates the row on first call."""
    result = await session.execute(select(AnalyticsSettings))
    row = result.scalar_one_or_none()
    if row is None:
        row = AnalyticsSettings(
            analytics_enabled=analytics_enabled if analytics_enabled is not None else True,
            show_views_on_posts=show_views_on_posts if show_views_on_posts is not None else False,
        )
        session.add(row)
    else:
        if analytics_enabled is not None:
            row.analytics_enabled = analytics_enabled
        if show_views_on_posts is not None:
            row.show_views_on_posts = show_views_on_posts
    await session.commit()
    return AnalyticsSettingsResponse(
        analytics_enabled=row.analytics_enabled,
        show_views_on_posts=row.show_views_on_posts,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_services/test_analytics_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/analytics_service.py tests/test_services/test_analytics_service.py
git commit -m "feat: add analytics service settings management"
```

---

### Task 4: Analytics Service — Hit Recording

**Files:**
- Modify: `backend/services/analytics_service.py`
- Test: `tests/test_services/test_analytics_hit_recording.py`

This task adds the fire-and-forget hit recording logic. The service sends `POST /api/v0/count` to GoatCounter with path, IP, and User-Agent. It skips hits from authenticated users and bots.

- [ ] **Step 1: Install crawlerdetect dependency**

Add `crawlerdetect` to the project's Python dependencies (check `pyproject.toml` or `requirements.txt` for the dependency format used).

- [ ] **Step 2: Write failing tests for hit recording**

Tests should mock `httpx.AsyncClient` to avoid needing a real GoatCounter instance. Test that:
- A hit is sent for unauthenticated, non-bot requests
- Hits are skipped for authenticated users (user is not None)
- Hits are skipped for bot User-Agents (detected by crawlerdetect)
- Hits are skipped when analytics is disabled
- Network errors are logged but don't raise exceptions
- The correct path, IP, and User-Agent are forwarded

Key test structure:

```python
"""Tests for analytics hit recording."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.analytics_service import record_hit

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.anyio
async def test_record_hit_sends_to_goatcounter(db_session: AsyncSession) -> None:
    """Unauthenticated, non-bot request records a hit."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock()
    with patch("backend.services.analytics_service._get_http_client", return_value=mock_client):
        await record_hit(
            session=db_session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "/api/v0/count" in call_kwargs.args[0] or "/api/v0/count" in str(call_kwargs)


@pytest.mark.anyio
async def test_record_hit_skips_authenticated_user(db_session: AsyncSession) -> None:
    """Authenticated user requests are not tracked."""
    mock_client = AsyncMock()
    with patch("backend.services.analytics_service._get_http_client", return_value=mock_client):
        await record_hit(
            session=db_session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user="admin",  # non-None means authenticated
        )
    mock_client.post.assert_not_called()


@pytest.mark.anyio
async def test_record_hit_skips_bots(db_session: AsyncSession) -> None:
    """Bot requests detected by crawlerdetect are not tracked."""
    mock_client = AsyncMock()
    with patch("backend.services.analytics_service._get_http_client", return_value=mock_client):
        await record_hit(
            session=db_session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Googlebot/2.1 (+http://www.google.com/bot.html)",
            user=None,
        )
    mock_client.post.assert_not_called()


@pytest.mark.anyio
async def test_record_hit_skips_when_disabled(db_session: AsyncSession) -> None:
    """Hits are not sent when analytics is disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(db_session, analytics_enabled=False)
    mock_client = AsyncMock()
    with patch("backend.services.analytics_service._get_http_client", return_value=mock_client):
        await record_hit(
            session=db_session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )
    mock_client.post.assert_not_called()


@pytest.mark.anyio
async def test_record_hit_network_error_is_silent(db_session: AsyncSession) -> None:
    """Network errors are logged but don't raise."""
    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("Connection refused")
    with patch("backend.services.analytics_service._get_http_client", return_value=mock_client):
        # Should not raise
        await record_hit(
            session=db_session,
            path="/post/hello-world",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            user=None,
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_services/test_analytics_hit_recording.py -v`
Expected: ImportError — `record_hit` not defined

- [ ] **Step 4: Implement hit recording in analytics_service.py**

Add to `backend/services/analytics_service.py`:

```python
import httpx
from crawlerdetect import CrawlerDetect

GOATCOUNTER_URL = "http://goatcounter:8080"
GOATCOUNTER_TOKEN_PATH = "/data/goatcounter/token"
_HIT_TIMEOUT = 2.0

_crawler_detect = CrawlerDetect()
_http_client: httpx.AsyncClient | None = None
_goatcounter_token: str | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_HIT_TIMEOUT)
    return _http_client


def _load_token() -> str | None:
    global _goatcounter_token
    if _goatcounter_token is not None:
        return _goatcounter_token
    try:
        with open(GOATCOUNTER_TOKEN_PATH) as f:
            _goatcounter_token = f.read().strip()
        return _goatcounter_token
    except FileNotFoundError:
        logger.warning("GoatCounter token not found at %s", GOATCOUNTER_TOKEN_PATH)
        return None


async def record_hit(
    *,
    session: AsyncSession,
    path: str,
    client_ip: str,
    user_agent: str,
    user: str | None,
) -> None:
    """Record a page hit to GoatCounter. Fire-and-forget — never raises."""
    try:
        # Skip authenticated users
        if user is not None:
            return

        # Skip bots
        if _crawler_detect.isCrawler(user_agent):
            return

        # Check if analytics is enabled
        settings = await get_analytics_settings(session)
        if not settings.analytics_enabled:
            return

        # Load token (lazy)
        token = _load_token()
        if token is None:
            return

        client = _get_http_client()
        await client.post(
            f"{GOATCOUNTER_URL}/api/v0/count",
            json={
                "no_sessions": False,
                "hits": [{"path": path, "ip": client_ip, "user_agent": user_agent}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        logger.warning("Failed to record analytics hit for %s", path, exc_info=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_services/test_analytics_hit_recording.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/analytics_service.py \
  tests/test_services/test_analytics_hit_recording.py \
  pyproject.toml  # or requirements file with crawlerdetect
git commit -m "feat: add analytics hit recording with bot filtering"
```

---

### Task 5: Analytics Service — Stats Proxy

**Files:**
- Modify: `backend/services/analytics_service.py`
- Test: `tests/test_services/test_analytics_stats.py`

This task adds methods that proxy GoatCounter's stats API endpoints.

- [ ] **Step 1: Write failing tests for stats proxy**

Test with mocked httpx responses. Cover:
- `fetch_total_stats(session, start, end)` — returns total views/unique
- `fetch_path_hits(session, start, end)` — returns per-path data
- `fetch_path_referrers(session, path_id)` — referrer breakdown
- `fetch_breakdown(session, category, start, end)` — browser/OS data
- `fetch_view_count(session, path)` — single path view count for public endpoint
- All methods return graceful error responses when GoatCounter is unavailable

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_analytics_stats.py -v`
Expected: ImportError — functions not defined

- [ ] **Step 3: Implement stats proxy methods**

Add to `backend/services/analytics_service.py`:

```python
_STATS_TIMEOUT = 5.0


async def _stats_request(endpoint: str, params: dict[str, str] | None = None) -> dict | None:
    """Make an authenticated GET request to GoatCounter stats API.

    Returns parsed JSON or None if unavailable.
    """
    token = _load_token()
    if token is None:
        return None
    try:
        client = _get_http_client()
        resp = await client.get(
            f"{GOATCOUNTER_URL}{endpoint}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_STATS_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.warning("GoatCounter stats request failed: %s", endpoint, exc_info=True)
        return None


async def fetch_total_stats(
    session: AsyncSession, start: str, end: str
) -> TotalStatsResponse:
    """Fetch total pageview stats for a date range."""
    data = await _stats_request("/api/v0/stats/total", {"start": start, "end": end})
    if data is None:
        return TotalStatsResponse(total_views=0, total_unique=0)
    # Transform GoatCounter response to our schema
    return TotalStatsResponse(
        total_views=data.get("total", 0),
        total_unique=data.get("total_unique", 0),
    )


async def fetch_path_hits(
    session: AsyncSession, start: str, end: str
) -> PathHitsResponse:
    """Fetch per-path hit statistics."""
    data = await _stats_request("/api/v0/stats/hits", {"start": start, "end": end})
    if data is None:
        return PathHitsResponse()
    # Transform from GoatCounter's response shape
    paths = [
        PathHit(path=p.get("path", ""), views=p.get("count", 0), unique=p.get("count_unique", 0))
        for p in data.get("paths", [])
    ]
    return PathHitsResponse(paths=paths)


async def fetch_path_referrers(
    session: AsyncSession, path_id: int
) -> PathReferrersResponse:
    """Fetch referrer breakdown for a specific path."""
    data = await _stats_request(f"/api/v0/stats/hits/{path_id}")
    if data is None:
        return PathReferrersResponse(path_id=path_id)
    refs = [
        ReferrerEntry(referrer=r.get("ref", ""), count=r.get("count", 0))
        for r in data.get("refs", [])
    ]
    return PathReferrersResponse(path_id=path_id, referrers=refs)


async def fetch_breakdown(
    session: AsyncSession, category: str, start: str, end: str
) -> BreakdownResponse:
    """Fetch browser/OS/etc. breakdown."""
    data = await _stats_request(f"/api/v0/stats/{category}", {"start": start, "end": end})
    if data is None:
        return BreakdownResponse(category=category)
    entries = [
        BreakdownEntry(
            name=e.get("name", ""),
            count=e.get("count", 0),
            percent=e.get("percent", 0.0),
        )
        for e in data.get("entries", [])
    ]
    return BreakdownResponse(category=category, entries=entries)


async def fetch_view_count(session: AsyncSession, path: str) -> int | None:
    """Fetch view count for a single path. Returns None if unavailable."""
    settings = await get_analytics_settings(session)
    if not settings.show_views_on_posts:
        return None
    data = await _stats_request("/api/v0/stats/hits", {"filter": path})
    if data is None:
        return None
    paths = data.get("paths", [])
    if not paths:
        return 0
    return paths[0].get("count", 0)
```

Note: The exact GoatCounter response shape may need adjustment during implementation. Check GoatCounter's `/api.json` OpenAPI spec for the precise field names.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_services/test_analytics_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/analytics_service.py tests/test_services/test_analytics_stats.py
git commit -m "feat: add analytics stats proxy methods"
```

---

### Task 6: Analytics API Router — Admin Endpoints

**Files:**
- Create: `backend/api/analytics.py`
- Modify: `backend/main.py` (register router)
- Test: `tests/test_api/test_analytics_api.py`

- [ ] **Step 1: Write failing integration tests**

Test the admin analytics API endpoints. Use the existing `create_test_client` pattern from `tests/conftest.py`. Tests should:
- Verify admin auth is required (401/403 for unauthenticated/non-admin)
- Verify settings GET returns defaults
- Verify settings PUT updates and persists
- Verify stats endpoints return data (with mocked GoatCounter)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_analytics_api.py -v`
Expected: FAIL — router not registered, endpoints not found

- [ ] **Step 3: Create the analytics API router**

Create `backend/api/analytics.py`:

```python
"""Analytics API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_session, require_admin
from backend.models.user import User
from backend.schemas.analytics import (
    AnalyticsSettingsResponse,
    AnalyticsSettingsUpdate,
    BreakdownResponse,
    PathHitsResponse,
    PathReferrersResponse,
    TotalStatsResponse,
    ViewCountResponse,
)
from backend.services.analytics_service import (
    fetch_breakdown,
    fetch_path_hits,
    fetch_path_referrers,
    fetch_total_stats,
    fetch_view_count,
    get_analytics_settings,
    update_analytics_settings,
)

admin_router = APIRouter(prefix="/api/admin/analytics", tags=["analytics-admin"])
public_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@admin_router.get("/settings", response_model=AnalyticsSettingsResponse)
async def get_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> AnalyticsSettingsResponse:
    """Get current analytics settings."""
    return await get_analytics_settings(session)


@admin_router.put("/settings", response_model=AnalyticsSettingsResponse)
async def put_settings(
    body: AnalyticsSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> AnalyticsSettingsResponse:
    """Update analytics settings."""
    return await update_analytics_settings(
        session,
        analytics_enabled=body.analytics_enabled,
        show_views_on_posts=body.show_views_on_posts,
    )


@admin_router.get("/stats/total", response_model=TotalStatsResponse)
async def stats_total(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> TotalStatsResponse:
    """Get total pageview statistics."""
    return await fetch_total_stats(session, start, end)


@admin_router.get("/stats/hits", response_model=PathHitsResponse)
async def stats_hits(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> PathHitsResponse:
    """Get per-path hit statistics."""
    return await fetch_path_hits(session, start, end)


@admin_router.get("/stats/hits/{path_id}", response_model=PathReferrersResponse)
async def stats_referrers(
    path_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
) -> PathReferrersResponse:
    """Get referrer breakdown for a specific path."""
    return await fetch_path_referrers(session, path_id)


@admin_router.get("/stats/{category}", response_model=BreakdownResponse)
async def stats_breakdown(
    category: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_admin)],
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> BreakdownResponse:
    """Get browser/OS/etc. breakdown."""
    return await fetch_breakdown(session, category, start, end)


@public_router.get("/views/{file_path:path}", response_model=ViewCountResponse)
async def post_view_count(
    file_path: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ViewCountResponse:
    """Get view count for a single post.

    Returns views only when show_views_on_posts is enabled.
    Returns the same response for non-existent and draft posts
    to avoid information disclosure.
    """
    views = await fetch_view_count(session, f"/post/{file_path}")
    return ViewCountResponse(views=views)
```

- [ ] **Step 4: Register the routers in `backend/main.py`**

Add imports and `app.include_router()` calls for both `admin_router` and `public_router` from `backend.api.analytics`. Place them alongside the existing router registrations (around line 502-511).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api/test_analytics_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/analytics.py backend/main.py tests/test_api/test_analytics_api.py
git commit -m "feat: add analytics API endpoints"
```

---

### Task 7: Hit Recording Integration — Post & Page Endpoints

**Files:**
- Modify: `backend/api/posts.py` (add hit recording to `get_post_endpoint`)
- Modify: `backend/api/pages.py` (add hit recording to `get_page_endpoint`)
- Test: `tests/test_api/test_analytics_hit_integration.py`

- [ ] **Step 1: Write failing integration tests**

Test that viewing a post/page fires a hit to GoatCounter:
- `GET /api/posts/{slug}` as unauthenticated reader → hit recorded
- `GET /api/posts/{slug}` as authenticated admin → hit NOT recorded
- `GET /api/pages/{id}` as unauthenticated reader → hit recorded

Use `create_test_client` and mock the GoatCounter HTTP call.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_analytics_hit_integration.py -v`
Expected: FAIL — no hit recording in endpoints yet

- [ ] **Step 3: Add hit recording to `get_post_endpoint`**

Modify `backend/api/posts.py` — add `Request` to the handler's parameters, and after successfully resolving a post (before returning), add a background task to record the hit:

```python
from starlette.background import BackgroundTask
from backend.services.analytics_service import record_hit

# Inside get_post_endpoint, after resolving the post:
# Extract client info from the request
client_ip = request.client.host if request.client else "unknown"
user_agent = request.headers.get("user-agent", "")
username = user.username if user else None

# Return with background task for fire-and-forget hit recording
# Use Starlette's BackgroundTask or asyncio.create_task
```

The key integration points in `get_post_endpoint` (line 690 and 698):
- After `if post is not None: return post` — wrap the return in a Response with a background task, or use `asyncio.create_task` to fire the hit asynchronously.

The preferred approach: use `asyncio.create_task` since the endpoint returns Pydantic models, not raw Responses. Call `record_hit` in a fire-and-forget task after the post is found but within the endpoint.

- [ ] **Step 4: Add hit recording to `get_page_endpoint`**

Same pattern in `backend/api/pages.py` — add `Request` parameter, fire hit after successful page resolution (line 41-46).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api/test_analytics_hit_integration.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/posts.py backend/api/pages.py \
  tests/test_api/test_analytics_hit_integration.py
git commit -m "feat: integrate hit recording into post and page endpoints"
```

---

### Task 8: Frontend — Analytics API Client

**Files:**
- Create: `frontend/src/api/analytics.ts`
- Modify: `frontend/src/api/client.ts` (add type interfaces)

- [ ] **Step 1: Add TypeScript interfaces to `frontend/src/api/client.ts`**

Add to the exports in `client.ts`:

```typescript
export interface AnalyticsSettings {
  analytics_enabled: boolean
  show_views_on_posts: boolean
}

export interface PathHit {
  path: string
  views: number
  unique: number
}

export interface PathHitsResponse {
  paths: PathHit[]
}

export interface TotalStatsResponse {
  total_views: number
  total_unique: number
}

export interface ReferrerEntry {
  referrer: string
  count: number
}

export interface PathReferrersResponse {
  path_id: number
  referrers: ReferrerEntry[]
}

export interface BreakdownEntry {
  name: string
  count: number
  percent: number
}

export interface BreakdownResponse {
  category: string
  entries: BreakdownEntry[]
}

export interface ViewCountResponse {
  views: number | null
}
```

- [ ] **Step 2: Create analytics API functions**

Create `frontend/src/api/analytics.ts`:

```typescript
import api from './client'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  PathReferrersResponse,
  BreakdownResponse,
  ViewCountResponse,
} from './client'

export async function fetchAnalyticsSettings(): Promise<AnalyticsSettings> {
  return api.get('admin/analytics/settings').json<AnalyticsSettings>()
}

export async function updateAnalyticsSettings(
  settings: Partial<AnalyticsSettings>,
): Promise<AnalyticsSettings> {
  return api.put('admin/analytics/settings', { json: settings }).json<AnalyticsSettings>()
}

export async function fetchTotalStats(start: string, end: string): Promise<TotalStatsResponse> {
  return api
    .get('admin/analytics/stats/total', { searchParams: { start, end } })
    .json<TotalStatsResponse>()
}

export async function fetchPathHits(start: string, end: string): Promise<PathHitsResponse> {
  return api
    .get('admin/analytics/stats/hits', { searchParams: { start, end } })
    .json<PathHitsResponse>()
}

export async function fetchPathReferrers(pathId: number): Promise<PathReferrersResponse> {
  return api.get(`admin/analytics/stats/hits/${pathId}`).json<PathReferrersResponse>()
}

export async function fetchBreakdown(
  category: string,
  start: string,
  end: string,
): Promise<BreakdownResponse> {
  return api
    .get(`admin/analytics/stats/${category}`, { searchParams: { start, end } })
    .json<BreakdownResponse>()
}

export async function fetchViewCount(filePath: string): Promise<ViewCountResponse> {
  return api.get(`analytics/views/${filePath}`).json<ViewCountResponse>()
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/analytics.ts frontend/src/api/client.ts
git commit -m "feat: add analytics API client and TypeScript types"
```

---

### Task 9: Frontend — Install Recharts

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install Recharts**

```bash
cd frontend && npm install recharts
```

- [ ] **Step 2: Verify build still works**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add recharts dependency for analytics dashboard"
```

---

### Task 10: Frontend — Analytics Dashboard Component

**Files:**
- Create: `frontend/src/components/admin/AnalyticsPanel.tsx`
- Test: `frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx`

This is the main dashboard component with date range selector, summary cards, charts, tables, and breakdown panels. Recharts is imported normally within this component — code-splitting is handled at the component level by Task 11 (which lazy-loads the entire `AnalyticsPanel`).

- [ ] **Step 1: Write the AnalyticsPanel component**

Create `frontend/src/components/admin/AnalyticsPanel.tsx`. Structure:

```typescript
import { useCallback, useEffect, useState } from 'react'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type {
  AnalyticsSettings,
  PathHit,
  BreakdownEntry,
  ReferrerEntry,
} from '@/api/client'
import {
  fetchAnalyticsSettings,
  updateAnalyticsSettings,
  fetchTotalStats,
  fetchPathHits,
  fetchPathReferrers,
  fetchBreakdown,
} from '@/api/analytics'

type DateRange = '7d' | '30d' | '90d'
```

Key implementation details:
- **Date range selector**: 7d/30d/90d buttons, calculates ISO date strings for `start`/`end`
- **Settings toggles**: analytics enabled, show views on posts — call `updateAnalyticsSettings` on toggle
- **Summary cards**: display `totalViews`, `totalUnique`, top page from `pathHits`
- **Area chart**: views over time (use Recharts `AreaChart` with `ResponsiveContainer`)
- **Top pages table**: sorted by views, clickable rows to show referrers
- **Breakdown bars**: horizontal bars for browser/OS percentages
- **Loading states**: show loading spinner while fetching data
- **Error state**: show "Analytics unavailable" message if all requests fail
- **Disable controls while saving**

The component receives `busy: boolean` and `onBusyChange: (busy: boolean) => void` props to integrate with the admin panel's busy state.

- [ ] **Step 2: Write component tests**

Test with vitest and React Testing Library. Mock the API calls. Verify:
- Dashboard renders with loading state then shows data
- Date range buttons trigger data refetch
- Settings toggles call the update API
- Top pages table renders rows
- Clicking a row shows referrer detail
- Error state shows appropriate message

- [ ] **Step 3: Run tests**

Run: `just test-frontend`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/AnalyticsPanel.tsx \
  frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx
git commit -m "feat: add analytics dashboard component with charts"
```

---

### Task 11: Frontend — Register Analytics Tab in AdminPage

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

- [ ] **Step 1: Add the Analytics tab**

In `frontend/src/pages/AdminPage.tsx`:

1. Add `'analytics'` to `ADMIN_TABS`:
   ```typescript
   const ADMIN_TABS = [
     { key: 'settings', label: 'Settings' },
     { key: 'pages', label: 'Pages' },
     { key: 'account', label: 'Account' },
     { key: 'social', label: 'Social' },
     { key: 'analytics', label: 'Analytics' },
   ] as const
   ```

2. Import `AnalyticsPanel` (lazy import for code splitting):
   ```typescript
   const AnalyticsPanel = lazy(() => import('@/components/admin/AnalyticsPanel'))
   ```

3. Add the tab content rendering (after the social tab block, around line 176):
   ```typescript
   {activeTab === 'analytics' && (
     <Suspense fallback={<LoadingSpinner />}>
       <AnalyticsPanel busy={busy} onBusyChange={setAnalyticsBusy} />
     </Suspense>
   )}
   ```

4. Add state for analytics busy tracking and wire it into the `busy` computed value.

- [ ] **Step 2: Update AdminPage tests**

Update `frontend/src/pages/__tests__/AdminPage.test.tsx` if it tests tab rendering — add the Analytics tab to expected tabs.

- [ ] **Step 3: Run tests**

Run: `just test-frontend`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/AdminPage.tsx \
  frontend/src/pages/__tests__/AdminPage.test.tsx
git commit -m "feat: add Analytics tab to admin panel"
```

---

### Task 12: Frontend — Post View Count Display

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx`
- Test: `frontend/src/pages/__tests__/PostPage.test.tsx`

- [ ] **Step 1: Add view count display to PostPage**

In `frontend/src/pages/PostPage.tsx`:

1. Import `fetchViewCount` from `@/api/analytics`
2. Add state for view count: `const [viewCount, setViewCount] = useState<number | null>(null)`
3. Fetch view count alongside the post data (in the existing `useEffect` or a separate one):
   ```typescript
   fetchViewCount(slug).then((res) => setViewCount(res.views)).catch(() => {})
   ```
4. Display near the post title/metadata when `viewCount !== null`:
   ```typescript
   {viewCount !== null && (
     <span className="text-muted text-sm">{viewCount.toLocaleString()} views</span>
   )}
   ```

- [ ] **Step 2: Update PostPage tests**

Add a test that verifies view count is displayed when the API returns a count, and not displayed when the API returns `null`.

- [ ] **Step 3: Run tests**

Run: `just test-frontend`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PostPage.tsx frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "feat: display view count on post pages when enabled"
```

---

### Task 13: GoatCounter Docker Container & Entrypoint

**Files:**
- Create: `goatcounter/entrypoint.sh`
- Create: `goatcounter/Dockerfile` (if needed, or use official image with custom entrypoint)
- Modify: `docker-compose.yml`

- [ ] **Step 1: Create GoatCounter entrypoint script**

Create `goatcounter/entrypoint.sh`:

```bash
#!/bin/sh
set -e

GOATCOUNTER_DB="/data/goatcounter/goatcounter.db"
TOKEN_FILE="/data/goatcounter/token"

# First-boot provisioning
if [ ! -f "$TOKEN_FILE" ]; then
    echo "First boot: creating GoatCounter site and API token..."
    mkdir -p /data/goatcounter

    # Create site with database
    goatcounter db create site \
        -createdb \
        -db "sqlite+$GOATCOUNTER_DB" \
        -vhost stats.internal \
        -user.email admin@localhost \
        -user.password "$(head -c 32 /dev/urandom | base64)"

    # Create API token (permission level 2 = read+write)
    TOKEN=$(goatcounter db create-apitoken \
        -db "sqlite+$GOATCOUNTER_DB" \
        -site-id 1 \
        -perm 2)

    echo "$TOKEN" > "$TOKEN_FILE"
    echo "GoatCounter provisioned. Token written to $TOKEN_FILE"
fi

# Start GoatCounter server
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none
```

Note: The exact `goatcounter` CLI flags may need adjustment. Check the GoatCounter Docker image docs and `goatcounter help` for the correct invocation. The token output format from `create-apitoken` may also need parsing.

- [ ] **Step 2: Add GoatCounter to docker-compose.yml**

Add to `docker-compose.yml`:

```yaml
  goatcounter:
    image: arp242/goatcounter:latest  # or build from goatcounter/Dockerfile
    expose:
      - "8080"
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    volumes:
      - goatcounter-data:/data/goatcounter
      - ./goatcounter/entrypoint.sh:/entrypoint.sh:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080/api/v0/count"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3
    networks:
      default:
        ipv4_address: 172.30.0.4
```

Add the shared volume to the `agblogger` service:
```yaml
    volumes:
      - ./content:/data/content
      - agblogger-db:/data/db
      - goatcounter-data:/data/goatcounter  # shared token file
```

Add to volumes section:
```yaml
  goatcounter-data:
```

Note: The GoatCounter container does NOT have a `depends_on` in `agblogger` — AgBlogger treats it as a soft dependency per the spec.

- [ ] **Step 3: Verify the compose file is valid**

```bash
docker compose config
```

- [ ] **Step 4: Commit**

```bash
git add goatcounter/entrypoint.sh docker-compose.yml
git commit -m "feat: add GoatCounter sidecar container to docker-compose"
```

---

### Task 14: Deployment Helper Updates

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Study the deployment helper**

Read `cli/deploy_production.py` to understand how compose files are generated. Look for:
- How services are defined in the generated compose
- How volumes are managed
- How `setup.sh` handles container startup

- [ ] **Step 2: Add GoatCounter to deployment compose generation**

Update `cli/deploy_production.py`:
- Add `GOATCOUNTER_STATIC_IP = "172.30.0.4"` alongside existing static IPs
- Add GoatCounter service definition to generated compose files
- Add `goatcounter-data` volume
- Add shared volume mount to agblogger service
- Include `goatcounter/entrypoint.sh` in deployment bundles

- [ ] **Step 3: Update deployment tests**

Update `tests/test_cli/test_deploy_production.py`:
- Verify generated compose includes the goatcounter service
- Verify the goatcounter-data volume is present
- Verify the shared volume mount is on the agblogger service

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cli/test_deploy_production.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add GoatCounter to deployment helper"
```

---

### Task 15: Architecture Docs Update

**Files:**
- Modify: `docs/arch/backend.md`
- Modify: `docs/arch/deployment.md`
- Modify: `docs/arch/frontend.md`

- [ ] **Step 1: Update backend.md**

Add a section about the analytics service: hit recording, stats proxy, settings management. Mention the GoatCounter integration pattern (server-internal, fire-and-forget).

- [ ] **Step 2: Update deployment.md**

Add GoatCounter container to the runtime topology description. Mention the shared volume for token provisioning and that GoatCounter is a soft dependency.

- [ ] **Step 3: Update frontend.md**

Mention the Analytics tab in the admin panel, Recharts dependency (lazy-loaded), and the view count display on PostPage.

- [ ] **Step 4: Commit**

```bash
git add docs/arch/backend.md docs/arch/deployment.md docs/arch/frontend.md
git commit -m "docs: update architecture docs for GoatCounter analytics"
```

---

### Task 16: Final Verification

- [ ] **Step 1: Run full check**

```bash
just check
```

Expected: All static checks and tests pass.

- [ ] **Step 2: Review all changes**

```bash
git log --oneline main..HEAD
```

Verify the commit history is clean and focused.

- [ ] **Step 3: Manual smoke test (if dev server available)**

Start the dev server with `just start`, navigate to the admin panel, verify the Analytics tab renders (it will show "Analytics unavailable" without a GoatCounter instance, which is expected).
