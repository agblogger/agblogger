# Analytics Dashboard Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between GoatCounter's built-in dashboard and the AgBlogger admin analytics panel by adding views-over-time, site-wide referrers, version drill-downs, four missing breakdown panels, a custom date picker, and CSV export.

**Architecture:** Extend the existing backend proxy layer with new service functions and API endpoints, then extract the monolithic `AnalyticsPanel.tsx` into focused sub-components. The backend aggregates data server-side to avoid N+1 frontend fetches. All new endpoints follow existing patterns (admin-only, 503 on GoatCounter unavailability).

**Tech Stack:** Python/FastAPI/Pydantic (backend), React/TypeScript/Recharts/SWR (frontend), vitest + pytest (tests)

**Spec:** `docs/specs/2026-04-05-analytics-dashboard-parity-design.md`

---

## File Map

### Backend — new/modified

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/schemas/analytics.py` | Modify | Add schemas: `DailyViewCount`, `ViewsOverTimeResponse`, `SiteReferrersResponse`, `BreakdownDetailEntry`, `BreakdownDetailResponse`, `ExportCreateResponse`, `ExportStatusResponse` |
| `backend/services/analytics_service.py` | Modify | Add: `fetch_views_over_time`, `fetch_site_referrers`, `fetch_breakdown_detail`, `create_export`, `get_export_status`, `download_export` |
| `backend/api/analytics.py` | Modify | Add endpoints: views-over-time, site-wide referrers, breakdown detail, export CRUD |
| `tests/test_services/test_analytics_stats.py` | Modify | Add tests for new service functions |
| `tests/test_api/test_analytics_api.py` | Modify | Add tests for new endpoints |

### Frontend — new/modified

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/api/client.ts` | Modify | Add types: `DailyViewCount`, `ViewsOverTimeResponse`, `SiteReferrersResponse`, `BreakdownDetailEntry`, `BreakdownDetailResponse`, `ExportCreateResponse`, `ExportStatusResponse` |
| `frontend/src/api/analytics.ts` | Modify | Add fetch functions for new endpoints |
| `frontend/src/hooks/useAnalyticsDashboard.ts` | Modify | Extend composite hook to fetch new data; add `useSiteReferrers`, `useBreakdownDetail` hooks; support custom date range |
| `frontend/src/components/admin/AnalyticsPanel.tsx` | Rewrite | Orchestrator that renders extracted sub-components |
| `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx` | Create | Bar chart with auto-granularity (daily/weekly) |
| `frontend/src/components/admin/analytics/TopPagesPanel.tsx` | Create | Top pages table with inline referrer expansion |
| `frontend/src/components/admin/analytics/TopReferrersPanel.tsx` | Create | Site-wide referrers table |
| `frontend/src/components/admin/analytics/BreakdownBarChart.tsx` | Create | Reusable bar chart for browsers, OS, screen sizes; optional inline version drill-down |
| `frontend/src/components/admin/analytics/BreakdownTable.tsx` | Create | Reusable table for locations, languages, campaigns |
| `frontend/src/components/admin/analytics/DateRangePicker.tsx` | Create | Custom date range selector with preset integration |
| `frontend/src/components/admin/analytics/ExportButton.tsx` | Create | CSV export with async polling |
| `frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx` | Rewrite | Updated integration tests for orchestrator |
| `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx` | Create | Unit tests |
| `frontend/src/components/admin/analytics/__tests__/TopPagesPanel.test.tsx` | Create | Unit tests |
| `frontend/src/components/admin/analytics/__tests__/TopReferrersPanel.test.tsx` | Create | Unit tests |
| `frontend/src/components/admin/analytics/__tests__/BreakdownBarChart.test.tsx` | Create | Unit tests |
| `frontend/src/components/admin/analytics/__tests__/BreakdownTable.test.tsx` | Create | Unit tests |
| `frontend/src/components/admin/analytics/__tests__/DateRangePicker.test.tsx` | Create | Unit tests |
| `frontend/src/components/admin/analytics/__tests__/ExportButton.test.tsx` | Create | Unit tests |

---

## Task 1: Backend — Views Over Time Service + Schema

**Files:**
- Modify: `backend/schemas/analytics.py`
- Modify: `backend/services/analytics_service.py`
- Modify: `tests/test_services/test_analytics_stats.py`

- [ ] **Step 1: Add schemas for views-over-time response**

In `backend/schemas/analytics.py`, add after `PathHitsResponse`:

```python
class DailyViewCount(BaseModel):
    """View count for a single day."""

    date: str = Field(min_length=10, max_length=10)
    views: int = Field(ge=0)


class ViewsOverTimeResponse(BaseModel):
    """Daily view counts aggregated across all paths."""

    days: list[DailyViewCount] = Field(default_factory=list)
```

- [ ] **Step 2: Write failing test for `fetch_views_over_time`**

In `tests/test_services/test_analytics_stats.py`, add:

```python
async def test_fetch_views_over_time_aggregates_daily_counts(session: AsyncSession) -> None:
    """fetch_views_over_time sums per-path daily counts into daily totals."""
    fake_response = {
        "hits": [
            {
                "path_id": 1,
                "path": "/post/hello",
                "count": 10,
                "stats": [
                    {"day": "2026-04-01", "days": [5, 3, 2, 0, 0, 0, 0]},
                ],
            },
            {
                "path_id": 2,
                "path": "/post/world",
                "count": 6,
                "stats": [
                    {"day": "2026-04-01", "days": [2, 1, 3, 0, 0, 0, 0]},
                ],
            },
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_views_over_time(session, start="2026-04-01", end="2026-04-07")

    assert result is not None
    assert len(result.days) == 7
    assert result.days[0].date == "2026-04-01"
    assert result.days[0].views == 7  # 5 + 2
    assert result.days[1].views == 4  # 3 + 1
    assert result.days[2].views == 5  # 2 + 3


async def test_fetch_views_over_time_returns_none_when_unavailable(
    session: AsyncSession,
) -> None:
    """fetch_views_over_time returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_views_over_time(session)

    assert result is None


async def test_fetch_views_over_time_handles_empty_hits(session: AsyncSession) -> None:
    """fetch_views_over_time returns empty days when no hits exist."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"hits": []},
    ):
        result = await fetch_views_over_time(session)

    assert result is not None
    assert result.days == []


async def test_fetch_views_over_time_handles_missing_stats_field(
    session: AsyncSession,
) -> None:
    """Paths without a stats field are skipped gracefully."""
    fake_response = {
        "hits": [
            {"path_id": 1, "path": "/post/hello", "count": 10},
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_views_over_time(session)

    assert result is not None
    assert result.days == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `just test-backend` (unsandboxed)
Expected: FAIL — `fetch_views_over_time` not defined

- [ ] **Step 4: Implement `fetch_views_over_time`**

In `backend/services/analytics_service.py`, add the import for the new schema at the top and implement:

```python
from backend.schemas.analytics import (
    # ... existing imports ...
    DailyViewCount,
    ViewsOverTimeResponse,
)

async def fetch_views_over_time(
    session: AsyncSession,
    start: str | None = None,
    end: str | None = None,
) -> ViewsOverTimeResponse | None:
    """Aggregate per-path daily counts into daily totals across all paths.

    GoatCounter's /api/v0/stats/hits returns per-path entries with a ``stats``
    array containing ``{day, days}`` objects. This function sums the daily
    counts across all paths into a single daily total series.
    """
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    params = _build_goatcounter_date_params(start, end)
    params["daily"] = "true"
    data = await _stats_request("/api/v0/stats/hits", params or None)
    if data is None:
        return None

    day_totals: dict[str, int] = {}
    for entry in data.get("hits", []):
        for stat_block in entry.get("stats", []):
            start_day = stat_block.get("day", "")
            if not start_day:
                continue
            for offset, count in enumerate(stat_block.get("days", [])):
                if not isinstance(count, int):
                    continue
                day_date = _offset_date(start_day, offset)
                day_totals[day_date] = day_totals.get(day_date, 0) + count

    days = [
        DailyViewCount(date=d, views=v)
        for d, v in sorted(day_totals.items())
    ]
    return ViewsOverTimeResponse(days=days)


def _offset_date(base_date: str, offset: int) -> str:
    """Add offset days to a YYYY-MM-DD date string."""
    from datetime import date, timedelta

    d = date.fromisoformat(base_date)
    return (d + timedelta(days=offset)).isoformat()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend` (unsandboxed)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/analytics.py backend/services/analytics_service.py tests/test_services/test_analytics_stats.py
git commit -m "feat: add views-over-time backend service and schema"
```

---

## Task 2: Backend — Site-Wide Referrers Service

**Files:**
- Modify: `backend/schemas/analytics.py`
- Modify: `backend/services/analytics_service.py`
- Modify: `tests/test_services/test_analytics_stats.py`

- [ ] **Step 1: Add schema for site-wide referrers response**

In `backend/schemas/analytics.py`, add after `PathReferrersResponse`:

```python
class SiteReferrersResponse(BaseModel):
    """Aggregated referrer counts across all paths."""

    referrers: list[ReferrerEntry] = Field(default_factory=list)
```

- [ ] **Step 2: Write failing tests for `fetch_site_referrers`**

In `tests/test_services/test_analytics_stats.py`, add:

```python
async def test_fetch_site_referrers_aggregates_across_paths(session: AsyncSession) -> None:
    """fetch_site_referrers merges referrers from all paths."""
    path_hits = {
        "hits": [
            {"path_id": 1, "path": "/post/a", "count": 10},
            {"path_id": 2, "path": "/post/b", "count": 5},
        ]
    }
    refs_path_1 = {"refs": [{"name": "Google", "count": 5}, {"name": "Twitter", "count": 3}]}
    refs_path_2 = {"refs": [{"name": "Google", "count": 2}, {"name": "Reddit", "count": 1}]}

    async def mock_stats_request(endpoint: str, params: dict | None = None) -> dict | None:
        if endpoint == "/api/v0/stats/hits":
            return path_hits
        if endpoint == "/api/v0/stats/hits/1":
            return refs_path_1
        if endpoint == "/api/v0/stats/hits/2":
            return refs_path_2
        return None

    with patch(
        "backend.services.analytics_service._stats_request",
        side_effect=mock_stats_request,
    ):
        result = await fetch_site_referrers(session, start="2026-04-01", end="2026-04-07")

    assert result is not None
    refs = {r.referrer: r.count for r in result.referrers}
    assert refs["Google"] == 7
    assert refs["Twitter"] == 3
    assert refs["Reddit"] == 1
    # Sorted descending by count
    assert result.referrers[0].referrer == "Google"


async def test_fetch_site_referrers_returns_none_when_unavailable(
    session: AsyncSession,
) -> None:
    """fetch_site_referrers returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_site_referrers(session)

    assert result is None


async def test_fetch_site_referrers_handles_empty_paths(session: AsyncSession) -> None:
    """fetch_site_referrers returns empty list when no paths exist."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value={"hits": []},
    ):
        result = await fetch_site_referrers(session)

    assert result is not None
    assert result.referrers == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `just test-backend` (unsandboxed)
Expected: FAIL — `fetch_site_referrers` not defined

- [ ] **Step 4: Implement `fetch_site_referrers`**

In `backend/services/analytics_service.py`, add:

```python
from backend.schemas.analytics import (
    # ... existing imports ...
    SiteReferrersResponse,
)

async def fetch_site_referrers(
    session: AsyncSession,
    start: str | None = None,
    end: str | None = None,
) -> SiteReferrersResponse | None:
    """Aggregate referrers across all paths into a single ranked list.

    Fetches the path list, then fetches referrers for each path concurrently.
    Merges and deduplicates referrer counts, returning a sorted list.
    """
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    params = _build_goatcounter_date_params(start, end)
    path_data = await _stats_request("/api/v0/stats/hits", params or None)
    if path_data is None:
        return None

    path_ids = [
        entry.get("path_id", entry.get("id"))
        for entry in path_data.get("hits", [])
        if entry.get("path_id", entry.get("id"))
    ]
    if not path_ids:
        return SiteReferrersResponse(referrers=[])

    import asyncio

    ref_results = await asyncio.gather(
        *[_stats_request(f"/api/v0/stats/hits/{pid}") for pid in path_ids],
        return_exceptions=True,
    )

    totals: dict[str, int] = {}
    for ref_data in ref_results:
        if not isinstance(ref_data, dict):
            continue
        for ref_entry in ref_data.get("refs", []):
            entry = ReferrerEntry.from_goatcounter(ref_entry)
            totals[entry.referrer] = totals.get(entry.referrer, 0) + entry.count

    referrers = sorted(
        [ReferrerEntry(referrer=name, count=count) for name, count in totals.items()],
        key=lambda r: r.count,
        reverse=True,
    )
    return SiteReferrersResponse(referrers=referrers)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend` (unsandboxed)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/analytics.py backend/services/analytics_service.py tests/test_services/test_analytics_stats.py
git commit -m "feat: add site-wide referrers aggregation service"
```

---

## Task 3: Backend — Breakdown Detail (Version Drill-Down) Service

**Files:**
- Modify: `backend/schemas/analytics.py`
- Modify: `backend/services/analytics_service.py`
- Modify: `tests/test_services/test_analytics_stats.py`

- [ ] **Step 1: Add schemas for breakdown detail response**

In `backend/schemas/analytics.py`, add after `BreakdownResponse`:

```python
BreakdownDetailCategory = Literal["browsers", "systems"]


class BreakdownDetailEntry(BaseModel):
    """A version entry within a breakdown category (e.g. Chrome 120)."""

    name: str
    count: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)

    @classmethod
    def from_goatcounter(
        cls,
        entry: dict[str, Any],
        *,
        total_count: int | None = None,
    ) -> BreakdownDetailEntry:
        """Construct from a raw GoatCounter detail entry."""
        name = entry.get("name", "")
        if not isinstance(name, str) or not name.strip():
            name = "Unknown"
        raw_count = entry.get("count", 0)
        count = raw_count if isinstance(raw_count, int) else 0
        percent = entry.get("percent")
        if percent is None:
            percent = (count / total_count * 100.0) if total_count and total_count > 0 else 0.0
        return cls(name=name, count=count, percent=percent)


class BreakdownDetailResponse(BaseModel):
    """Version detail for a breakdown entry (e.g. all Chrome versions)."""

    category: BreakdownDetailCategory
    entry_id: int = Field(ge=1)
    entries: list[BreakdownDetailEntry] = Field(default_factory=list)
```

- [ ] **Step 2: Write failing tests for `fetch_breakdown_detail`**

In `tests/test_services/test_analytics_stats.py`, add:

```python
async def test_fetch_breakdown_detail_returns_versions(session: AsyncSession) -> None:
    """fetch_breakdown_detail returns version entries for a browser/OS."""
    fake_response = {
        "stats": [
            {"name": "Chrome 120", "count": 50},
            {"name": "Chrome 119", "count": 30},
        ]
    }
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await fetch_breakdown_detail(session, "browsers", 3)

    assert result is not None
    assert result.category == "browsers"
    assert result.entry_id == 3
    assert len(result.entries) == 2
    assert result.entries[0].name == "Chrome 120"
    assert result.entries[0].count == 50


async def test_fetch_breakdown_detail_returns_none_when_unavailable(
    session: AsyncSession,
) -> None:
    """fetch_breakdown_detail returns None when GoatCounter is unavailable."""
    with patch(
        "backend.services.analytics_service._stats_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_breakdown_detail(session, "browsers", 3)

    assert result is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `just test-backend` (unsandboxed)
Expected: FAIL — `fetch_breakdown_detail` not defined

- [ ] **Step 4: Implement `fetch_breakdown_detail`**

In `backend/services/analytics_service.py`, add:

```python
from backend.schemas.analytics import (
    # ... existing imports ...
    BreakdownDetailCategory,
    BreakdownDetailEntry,
    BreakdownDetailResponse,
)

async def fetch_breakdown_detail(
    session: AsyncSession,
    category: BreakdownDetailCategory,
    entry_id: int,
) -> BreakdownDetailResponse | None:
    """Proxy GoatCounter version drill-down for a breakdown entry.

    Uses ``/api/v0/stats/{category}/{entry_id}`` to get sub-entries
    (e.g. Chrome 120, Chrome 119 under "Chrome").
    """
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    data = await _stats_request(f"/api/v0/stats/{category}/{entry_id}")
    if data is None:
        return None

    stats = data.get("stats", [])
    total_count = sum(
        e.get("count", 0)
        for e in stats
        if isinstance(e, dict) and isinstance(e.get("count", 0), int)
    )
    entries = [
        BreakdownDetailEntry.from_goatcounter(e, total_count=total_count)
        for e in stats
        if isinstance(e, dict)
    ]
    return BreakdownDetailResponse(category=category, entry_id=entry_id, entries=entries)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend` (unsandboxed)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/analytics.py backend/services/analytics_service.py tests/test_services/test_analytics_stats.py
git commit -m "feat: add breakdown version drill-down service"
```

---

## Task 4: Backend — CSV Export Service

**Files:**
- Modify: `backend/schemas/analytics.py`
- Modify: `backend/services/analytics_service.py`
- Modify: `tests/test_services/test_analytics_stats.py`

- [ ] **Step 1: Add schemas for export**

In `backend/schemas/analytics.py`, add:

```python
class ExportCreateResponse(BaseModel):
    """Response after creating a CSV export job."""

    id: int = Field(ge=0)


class ExportStatusResponse(BaseModel):
    """Status of a CSV export job."""

    id: int = Field(ge=0)
    finished: bool
```

- [ ] **Step 2: Write failing tests for export service functions**

In `tests/test_services/test_analytics_stats.py`, add:

```python
async def test_create_export_returns_id(session: AsyncSession) -> None:
    """create_export returns the export job id from GoatCounter."""
    fake_post_response = MagicMock()
    fake_post_response.status_code = 202
    fake_post_response.json.return_value = {"id": 42}
    fake_post_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_post_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await create_export(session)

    assert result is not None
    assert result.id == 42


async def test_create_export_returns_none_when_disabled(session: AsyncSession) -> None:
    """create_export returns None when analytics is disabled."""
    from backend.services.analytics_service import update_analytics_settings

    await update_analytics_settings(session, analytics_enabled=False)
    result = await create_export(session)
    assert result is None


async def test_get_export_status_finished(session: AsyncSession) -> None:
    """get_export_status returns finished=True when finished_at is set."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"id": 42, "finished_at": "2026-04-05T12:00:00Z"}
    fake_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await get_export_status(session, 42)

    assert result is not None
    assert result.finished is True


async def test_get_export_status_not_finished(session: AsyncSession) -> None:
    """get_export_status returns finished=False when finished_at is null."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"id": 42, "finished_at": None}
    fake_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await get_export_status(session, 42)

    assert result is not None
    assert result.finished is False


async def test_download_export_returns_bytes(session: AsyncSession) -> None:
    """download_export returns raw bytes from GoatCounter."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = b"csv-data-here"
    fake_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("backend.services.analytics_service._load_token", return_value="test-token"),
        patch("backend.services.analytics_service._get_http_client", return_value=mock_client),
    ):
        result = await download_export(session, 42)

    assert result == b"csv-data-here"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `just test-backend` (unsandboxed)
Expected: FAIL — `create_export`, `get_export_status`, `download_export` not defined

- [ ] **Step 4: Implement export service functions**

In `backend/services/analytics_service.py`, add:

```python
from backend.schemas.analytics import (
    # ... existing imports ...
    ExportCreateResponse,
    ExportStatusResponse,
)

async def create_export(
    session: AsyncSession,
) -> ExportCreateResponse | None:
    """Create a CSV export job on GoatCounter."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    token = _load_token()
    if token is None:
        return None

    try:
        client = _get_http_client()
        response = await client.post(
            f"{GOATCOUNTER_URL}/api/v0/export",
            json={},
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return ExportCreateResponse(id=data.get("id", 0))
    except _STATS_ERRORS:
        logger.warning("Failed to create GoatCounter export", exc_info=True)
        return None


async def get_export_status(
    session: AsyncSession,
    export_id: int,
) -> ExportStatusResponse | None:
    """Check the status of a GoatCounter CSV export job."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    token = _load_token()
    if token is None:
        return None

    try:
        client = _get_http_client()
        response = await client.get(
            f"{GOATCOUNTER_URL}/api/v0/export/{export_id}",
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return ExportStatusResponse(
            id=data.get("id", export_id),
            finished=data.get("finished_at") is not None,
        )
    except _STATS_ERRORS:
        logger.warning("Failed to check GoatCounter export %d status", export_id, exc_info=True)
        return None


async def download_export(
    session: AsyncSession,
    export_id: int,
) -> bytes | None:
    """Download a completed GoatCounter CSV export."""
    settings = await get_analytics_settings(session)
    if not settings.analytics_enabled:
        return None

    token = _load_token()
    if token is None:
        return None

    try:
        client = _get_http_client()
        response = await client.get(
            f"{GOATCOUNTER_URL}/api/v0/export/{export_id}/download",
            headers=_goatcounter_headers(token),
            timeout=_STATS_TIMEOUT,
        )
        response.raise_for_status()
        return response.content
    except _STATS_ERRORS:
        logger.warning("Failed to download GoatCounter export %d", export_id, exc_info=True)
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend` (unsandboxed)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/analytics.py backend/services/analytics_service.py tests/test_services/test_analytics_stats.py
git commit -m "feat: add CSV export service functions"
```

---

## Task 5: Backend — New API Endpoints

**Files:**
- Modify: `backend/api/analytics.py`
- Modify: `tests/test_api/test_analytics_api.py`

- [ ] **Step 1: Write failing tests for new endpoints**

In `tests/test_api/test_analytics_api.py`, add a new test class:

```python
class TestNewAnalyticsEndpoints:
    """Tests for new analytics endpoints (dashboard parity)."""

    @pytest.mark.asyncio
    async def test_views_over_time_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/views-over-time")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_site_referrers_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/referrers")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_breakdown_detail_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/stats/browsers/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_create_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.post("/api/admin/analytics/export")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_status_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/export/1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_download_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/admin/analytics/export/1/download")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_views_over_time_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service._stats_request",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/views-over-time",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_site_referrers_503_when_unavailable(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        with patch(
            "backend.services.analytics_service._stats_request",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/admin/analytics/stats/referrers",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_breakdown_detail_invalid_category(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/locations/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_breakdown_detail_invalid_id(self, client: AsyncClient) -> None:
        token = await _get_admin_token(client)
        resp = await client.get(
            "/api/admin/analytics/stats/browsers/0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend` (unsandboxed)
Expected: FAIL — routes not found (404)

- [ ] **Step 3: Add new endpoints to `backend/api/analytics.py`**

Add these endpoints to the existing `admin_router`:

```python
from backend.schemas.analytics import (
    # ... existing imports ...
    BreakdownDetailCategory,
    BreakdownDetailResponse,
    ExportCreateResponse,
    ExportStatusResponse,
    ViewsOverTimeResponse,
    SiteReferrersResponse,
)
from backend.services.analytics_service import (
    # ... existing imports ...
    create_export,
    download_export,
    fetch_breakdown_detail,
    fetch_site_referrers,
    fetch_views_over_time,
    get_export_status,
)
from fastapi.responses import Response

@admin_router.get("/stats/views-over-time", response_model=ViewsOverTimeResponse)
async def get_views_over_time(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> ViewsOverTimeResponse:
    """Get daily view counts aggregated across all paths."""
    start = _validate_analytics_range_param(start, "start")
    end = _validate_analytics_range_param(end, "end")
    result = await fetch_views_over_time(session, start, end)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/referrers", response_model=SiteReferrersResponse)
async def get_site_referrers(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> SiteReferrersResponse:
    """Get aggregated referrer counts across all paths."""
    start = _validate_analytics_range_param(start, "start")
    end = _validate_analytics_range_param(end, "end")
    result = await fetch_site_referrers(session, start, end)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/stats/{category}/{entry_id}", response_model=BreakdownDetailResponse)
async def get_breakdown_detail(
    category: BreakdownDetailCategory,
    entry_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> BreakdownDetailResponse:
    """Get version detail for a breakdown entry (browsers/systems only)."""
    result = await fetch_breakdown_detail(session, category, entry_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.post("/export", response_model=ExportCreateResponse)
async def create_csv_export(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> ExportCreateResponse:
    """Create a CSV export job on GoatCounter."""
    result = await create_export(session)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/export/{export_id}", response_model=ExportStatusResponse)
async def get_csv_export_status(
    export_id: Annotated[int, Path(ge=0)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> ExportStatusResponse:
    """Check the status of a CSV export job."""
    result = await get_export_status(session, export_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return result


@admin_router.get("/export/{export_id}/download")
async def download_csv_export(
    export_id: Annotated[int, Path(ge=0)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[AdminUser, Depends(require_admin)],
) -> Response:
    """Download a completed CSV export."""
    data = await download_export(session, export_id)
    if data is None:
        raise HTTPException(status_code=503, detail="Analytics service unavailable")
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=analytics-export-{export_id}.csv"},
    )
```

**Important:** The `/stats/{category}/{entry_id}` route must be registered AFTER the fixed routes `/stats/views-over-time` and `/stats/referrers` to avoid the fixed paths being captured by the `{category}` parameter. Also ensure it's registered BEFORE the existing `/stats/{category}` route. Check registration order carefully.

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend` (unsandboxed)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/analytics.py tests/test_api/test_analytics_api.py
git commit -m "feat: add views-over-time, referrers, detail, and export endpoints"
```

---

## Task 6: Frontend — Types and API Client Functions

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/analytics.ts`

- [ ] **Step 1: Add types to `frontend/src/api/client.ts`**

Add after `ViewCountResponse`:

```typescript
export interface DailyViewCount {
  date: string
  views: number
}

export interface ViewsOverTimeResponse {
  days: DailyViewCount[]
}

export interface SiteReferrersResponse {
  referrers: ReferrerEntry[]
}

export interface BreakdownDetailEntry {
  name: string
  count: number
  percent: number
}

export type BreakdownDetailCategory = 'browsers' | 'systems'

export interface BreakdownDetailResponse {
  category: BreakdownDetailCategory
  entry_id: number
  entries: BreakdownDetailEntry[]
}

export interface ExportCreateResponse {
  id: number
}

export interface ExportStatusResponse {
  id: number
  finished: boolean
}
```

- [ ] **Step 2: Add fetch functions to `frontend/src/api/analytics.ts`**

Add the new imports and functions:

```typescript
import type {
  // ... existing imports ...
  ViewsOverTimeResponse,
  SiteReferrersResponse,
  BreakdownDetailCategory,
  BreakdownDetailResponse,
  ExportCreateResponse,
  ExportStatusResponse,
} from './client'

export async function fetchViewsOverTime(
  start: string,
  end: string,
): Promise<ViewsOverTimeResponse> {
  return api
    .get('admin/analytics/stats/views-over-time', { searchParams: { start, end } })
    .json<ViewsOverTimeResponse>()
}

export async function fetchSiteReferrers(
  start: string,
  end: string,
): Promise<SiteReferrersResponse> {
  return api
    .get('admin/analytics/stats/referrers', { searchParams: { start, end } })
    .json<SiteReferrersResponse>()
}

export async function fetchBreakdownDetail(
  category: BreakdownDetailCategory,
  entryId: number,
): Promise<BreakdownDetailResponse> {
  return api
    .get(`admin/analytics/stats/${category}/${entryId}`)
    .json<BreakdownDetailResponse>()
}

export async function fetchCreateExport(): Promise<ExportCreateResponse> {
  return api.post('admin/analytics/export').json<ExportCreateResponse>()
}

export async function fetchExportStatus(exportId: number): Promise<ExportStatusResponse> {
  return api.get(`admin/analytics/export/${exportId}`).json<ExportStatusResponse>()
}

export async function fetchExportDownload(exportId: number): Promise<Blob> {
  return api.get(`admin/analytics/export/${exportId}/download`).blob()
}
```

- [ ] **Step 3: Run static checks**

Run: `just check-frontend` (unsandboxed)
Expected: PASS (lint + type check)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/analytics.ts
git commit -m "feat: add frontend types and API functions for new analytics endpoints"
```

---

## Task 7: Frontend — Extended Hooks

**Files:**
- Modify: `frontend/src/hooks/useAnalyticsDashboard.ts`

- [ ] **Step 1: Extend composite hook and add new hooks**

Rewrite `frontend/src/hooks/useAnalyticsDashboard.ts` to:

1. Accept a custom date range (start/end strings) in addition to presets
2. Fetch the four new breakdown categories (languages, locations, sizes, campaigns) and views-over-time in the parallel fetch
3. Add `useSiteReferrers` hook
4. Add `useBreakdownDetail` hook

The `DateRange` type becomes a union: preset string or custom object. The `getDateRange` function handles both.

```typescript
import useSWR from 'swr'
import {
  fetchAnalyticsSettings,
  fetchTotalStats,
  fetchPathHits,
  fetchBreakdown,
  fetchPathReferrers,
  fetchViewsOverTime,
  fetchSiteReferrers,
  fetchBreakdownDetail,
} from '@/api/analytics'
import { localDateToUtcEnd, localDateToUtcStart } from '@/utils/date'
import type {
  AnalyticsSettings,
  TotalStatsResponse,
  PathHitsResponse,
  BreakdownResponse,
  PathReferrersResponse,
  ViewsOverTimeResponse,
  SiteReferrersResponse,
  BreakdownDetailCategory,
  BreakdownDetailResponse,
} from '@/api/client'

export type DateRangePreset = '7d' | '30d' | '90d'
export interface CustomDateRange {
  start: string  // YYYY-MM-DD
  end: string    // YYYY-MM-DD
}
export type DateRange = DateRangePreset | CustomDateRange

const RANGE_DAYS: Record<DateRangePreset, number> = { '7d': 7, '30d': 30, '90d': 90 }

// ... keep existing AnalyticsDashboardStatsData but extend it ...
```

Extend `AnalyticsDashboardStatsData` to include:

```typescript
interface AnalyticsDashboardStatsData {
  stats: TotalStatsResponse
  paths: PathHitsResponse
  browsers: BreakdownResponse
  operatingSystems: BreakdownResponse
  languages: BreakdownResponse
  locations: BreakdownResponse
  sizes: BreakdownResponse
  campaigns: BreakdownResponse
  viewsOverTime: ViewsOverTimeResponse
}
```

Update `AnalyticsDashboardData` to include the new fields too. Update `getDisabledDashboardStats` to include zeroed versions of all new fields. Update `getDateRange` to handle `CustomDateRange`:

```typescript
function getDateRange(range: DateRange): { start: string; end: string } {
  if (typeof range === 'object') {
    return {
      start: localDateToUtcStart(range.start),
      end: localDateToUtcEnd(range.end),
    }
  }
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - RANGE_DAYS[range])
  return {
    start: localDateToUtcStart(formatLocalDate(start)),
    end: localDateToUtcEnd(formatLocalDate(end)),
  }
}
```

Update the fetcher in `useAnalyticsDashboard` to also fetch languages, locations, sizes, campaigns, and viewsOverTime in the `Promise.all`:

```typescript
const [stats, paths, browsersData, osData, languagesData, locationsData, sizesData, campaignsData, viewsOverTimeData] = await Promise.all([
  fetchTotalStats(start, end),
  fetchPathHits(start, end),
  fetchBreakdown('browsers', start, end),
  fetchBreakdown('systems', start, end),
  fetchBreakdown('languages', start, end),
  fetchBreakdown('locations', start, end),
  fetchBreakdown('sizes', start, end),
  fetchBreakdown('campaigns', start, end),
  fetchViewsOverTime(start, end),
])
```

Add new hooks:

```typescript
export function useSiteReferrers(range: DateRange, enabled: boolean) {
  const { start, end } = getDateRange(range)
  return useSWR<SiteReferrersResponse, Error>(
    enabled ? ['site-referrers', start, end] : null,
    () => fetchSiteReferrers(start, end),
  )
}

export function useBreakdownDetail(
  category: BreakdownDetailCategory | null,
  entryId: number | null,
) {
  return useSWR<BreakdownDetailResponse, Error>(
    category !== null && entryId !== null ? ['breakdown-detail', category, entryId] : null,
    ([, cat, id]: [string, BreakdownDetailCategory, number]) => fetchBreakdownDetail(cat, id),
  )
}
```

- [ ] **Step 2: Run static checks**

Run: `just check-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useAnalyticsDashboard.ts
git commit -m "feat: extend analytics hooks with new data sources and custom date range"
```

---

## Task 8: Frontend — DateRangePicker Component

**Files:**
- Create: `frontend/src/components/admin/analytics/DateRangePicker.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/DateRangePicker.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/DateRangePicker.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import DateRangePicker from '../DateRangePicker'

describe('DateRangePicker', () => {
  it('renders preset buttons and date inputs', () => {
    render(
      <DateRangePicker
        value="7d"
        onChange={vi.fn()}
        disabled={false}
      />,
    )
    expect(screen.getByRole('button', { name: /7 days/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /30 days/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /90 days/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Start date')).toBeInTheDocument()
    expect(screen.getByLabelText('End date')).toBeInTheDocument()
  })

  it('highlights active preset', () => {
    render(
      <DateRangePicker
        value="30d"
        onChange={vi.fn()}
        disabled={false}
      />,
    )
    const btn = screen.getByRole('button', { name: /30 days/i })
    expect(btn.className).toContain('bg-accent')
  })

  it('calls onChange with preset on button click', async () => {
    const onChange = vi.fn()
    render(
      <DateRangePicker
        value="7d"
        onChange={onChange}
        disabled={false}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /90 days/i }))
    expect(onChange).toHaveBeenCalledWith('90d')
  })

  it('calls onChange with custom range when dates change', async () => {
    const onChange = vi.fn()
    render(
      <DateRangePicker
        value="7d"
        onChange={onChange}
        disabled={false}
      />,
    )
    const startInput = screen.getByLabelText('Start date')
    const endInput = screen.getByLabelText('End date')
    await userEvent.clear(startInput)
    await userEvent.type(startInput, '2026-03-01')
    await userEvent.clear(endInput)
    await userEvent.type(endInput, '2026-03-15')
    // Trigger change by blurring or form submission
    await userEvent.tab()
    expect(onChange).toHaveBeenCalledWith({ start: '2026-03-01', end: '2026-03-15' })
  })

  it('disables all controls when disabled', () => {
    render(
      <DateRangePicker
        value="7d"
        onChange={vi.fn()}
        disabled={true}
      />,
    )
    expect(screen.getByRole('button', { name: /7 days/i })).toBeDisabled()
    expect(screen.getByLabelText('Start date')).toBeDisabled()
    expect(screen.getByLabelText('End date')).toBeDisabled()
  })

  it('shows error for invalid range (start after end)', async () => {
    const onChange = vi.fn()
    render(
      <DateRangePicker
        value={{ start: '2026-04-15', end: '2026-04-01' }}
        onChange={onChange}
        disabled={false}
      />,
    )
    expect(screen.getByText(/start date must be before end/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: FAIL — module not found

- [ ] **Step 3: Implement DateRangePicker**

Create `frontend/src/components/admin/analytics/DateRangePicker.tsx`:

```typescript
import { useMemo } from 'react'
import type { DateRange, DateRangePreset, CustomDateRange } from '@/hooks/useAnalyticsDashboard'

interface DateRangePickerProps {
  value: DateRange
  onChange: (range: DateRange) => void
  disabled: boolean
}

const PRESETS: { key: DateRangePreset; label: string }[] = [
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
  { key: '90d', label: '90 days' },
]

const RANGE_DAYS: Record<DateRangePreset, number> = { '7d': 7, '30d': 30, '90d': 90 }

function formatLocalDate(date: Date): string {
  const year = String(date.getFullYear())
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function presetToDateRange(preset: DateRangePreset): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - RANGE_DAYS[preset])
  return { start: formatLocalDate(start), end: formatLocalDate(end) }
}

export default function DateRangePicker({ value, onChange, disabled }: DateRangePickerProps) {
  const activePreset = typeof value === 'string' ? value : null
  const { start, end } = useMemo(() => {
    if (typeof value === 'object') return value
    return presetToDateRange(value)
  }, [value])

  const today = formatLocalDate(new Date())
  const validationError = start > end ? 'Start date must be before end date' : null

  function handleDateChange(field: 'start' | 'end', newValue: string) {
    const custom: CustomDateRange = {
      start: field === 'start' ? newValue : start,
      end: field === 'end' ? newValue : end,
    }
    onChange(custom)
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1">
        {PRESETS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onChange(key)}
            disabled={disabled}
            aria-label={`Last ${label}`}
            className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              activePreset === key
                ? 'bg-accent text-white'
                : 'text-muted hover:text-ink border border-border hover:bg-surface'
            }`}
          >
            {key}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <input
          type="date"
          aria-label="Start date"
          value={start}
          max={today}
          disabled={disabled}
          onChange={(e) => handleDateChange('start', e.target.value)}
          className="px-2 py-1.5 text-sm border border-border rounded-lg bg-surface text-ink disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <span className="text-muted text-sm">&ndash;</span>
        <input
          type="date"
          aria-label="End date"
          value={end}
          max={today}
          disabled={disabled}
          onChange={(e) => handleDateChange('end', e.target.value)}
          className="px-2 py-1.5 text-sm border border-border rounded-lg bg-surface text-ink disabled:opacity-50 disabled:cursor-not-allowed"
        />
      </div>
      {validationError !== null && (
        <p className="text-xs text-red-600 dark:text-red-400">{validationError}</p>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/analytics/DateRangePicker.tsx frontend/src/components/admin/analytics/__tests__/DateRangePicker.test.tsx
git commit -m "feat: add DateRangePicker component with presets and custom range"
```

---

## Task 9: Frontend — ExportButton Component

**Files:**
- Create: `frontend/src/components/admin/analytics/ExportButton.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/ExportButton.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/ExportButton.test.tsx`:

```typescript
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

const mockFetchCreateExport = vi.fn()
const mockFetchExportStatus = vi.fn()
const mockFetchExportDownload = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchCreateExport: (...args: unknown[]) => mockFetchCreateExport(...args) as unknown,
  fetchExportStatus: (...args: unknown[]) => mockFetchExportStatus(...args) as unknown,
  fetchExportDownload: (...args: unknown[]) => mockFetchExportDownload(...args) as unknown,
}))

import ExportButton from '../ExportButton'

describe('ExportButton', () => {
  it('renders Export CSV button', () => {
    render(<ExportButton disabled={false} />)
    expect(screen.getByRole('button', { name: /export csv/i })).toBeInTheDocument()
  })

  it('disables button when disabled prop is true', () => {
    render(<ExportButton disabled={true} />)
    expect(screen.getByRole('button', { name: /export csv/i })).toBeDisabled()
  })

  it('shows Exporting state during export', async () => {
    mockFetchCreateExport.mockResolvedValue({ id: 1 })
    mockFetchExportStatus.mockResolvedValue({ id: 1, finished: false })

    render(<ExportButton disabled={false} />)
    await userEvent.click(screen.getByRole('button', { name: /export csv/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /exporting/i })).toBeDisabled()
    })
  })

  it('shows error message on failure', async () => {
    mockFetchCreateExport.mockRejectedValue(new Error('fail'))

    render(<ExportButton disabled={false} />)
    await userEvent.click(screen.getByRole('button', { name: /export csv/i }))

    await waitFor(() => {
      expect(screen.getByText(/export failed/i)).toBeInTheDocument()
    })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: FAIL — module not found

- [ ] **Step 3: Implement ExportButton**

Create `frontend/src/components/admin/analytics/ExportButton.tsx`:

```typescript
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchCreateExport, fetchExportStatus, fetchExportDownload } from '@/api/analytics'

interface ExportButtonProps {
  disabled: boolean
}

const POLL_INTERVAL = 2000
const MAX_POLLS = 30

export default function ExportButton({ disabled }: ExportButtonProps) {
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleExport() {
    setExporting(true)
    setError(null)

    try {
      const { id } = await fetchCreateExport()

      for (let i = 0; i < MAX_POLLS; i++) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL))
        const status = await fetchExportStatus(id)
        if (status.finished) {
          const blob = await fetchExportDownload(id)
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `analytics-export-${id}.csv`
          a.click()
          URL.revokeObjectURL(url)
          return
        }
      }
      setError('Export timed out. Please try again.')
    } catch {
      setError('Export failed. Please try again.')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => void handleExport()}
        disabled={disabled || exporting}
        aria-label={exporting ? 'Exporting...' : 'Export CSV'}
        className="px-3 py-1.5 text-sm font-medium rounded-lg border border-border text-muted hover:text-ink hover:bg-surface transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
      >
        {exporting && <Loader2 size={14} className="animate-spin" />}
        {exporting ? 'Exporting...' : 'Export CSV'}
      </button>
      {error !== null && (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/analytics/ExportButton.tsx frontend/src/components/admin/analytics/__tests__/ExportButton.test.tsx
git commit -m "feat: add ExportButton component with async polling"
```

---

## Task 10: Frontend — ViewsOverTimeChart Component

**Files:**
- Create: `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ViewsOverTimeChart from '../ViewsOverTimeChart'

// Recharts uses ResizeObserver
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

describe('ViewsOverTimeChart', () => {
  it('renders chart heading', () => {
    render(<ViewsOverTimeChart days={[]} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('shows empty message when no data', () => {
    render(<ViewsOverTimeChart days={[]} />)
    expect(screen.getByText(/no data/i)).toBeInTheDocument()
  })

  it('renders chart with data', () => {
    const days = [
      { date: '2026-04-01', views: 10 },
      { date: '2026-04-02', views: 20 },
      { date: '2026-04-03', views: 15 },
    ]
    render(<ViewsOverTimeChart days={days} />)
    // Recharts renders SVG — verify the container exists
    expect(screen.getByText('Views over time')).toBeInTheDocument()
    expect(screen.queryByText(/no data/i)).not.toBeInTheDocument()
  })

  it('buckets into weekly when more than 30 days', () => {
    const days = Array.from({ length: 60 }, (_, i) => ({
      date: `2026-${String(Math.floor(i / 28) + 2).padStart(2, '0')}-${String((i % 28) + 1).padStart(2, '0')}`,
      views: i + 1,
    }))
    render(<ViewsOverTimeChart days={days} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: FAIL — module not found

- [ ] **Step 3: Implement ViewsOverTimeChart**

Create `frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx`:

```typescript
import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import type { DailyViewCount } from '@/api/client'

interface ViewsOverTimeChartProps {
  days: DailyViewCount[]
}

interface ChartDataPoint {
  label: string
  views: number
}

function bucketWeekly(days: DailyViewCount[]): ChartDataPoint[] {
  const buckets: ChartDataPoint[] = []
  for (let i = 0; i < days.length; i += 7) {
    const week = days.slice(i, i + 7)
    const views = week.reduce((sum, d) => sum + d.views, 0)
    const label = week[0]?.date.slice(5) ?? ''
    buckets.push({ label, views })
  }
  return buckets
}

function formatDaily(days: DailyViewCount[]): ChartDataPoint[] {
  return days.map((d) => ({ label: d.date.slice(5), views: d.views }))
}

export default function ViewsOverTimeChart({ days }: ViewsOverTimeChartProps) {
  const chartData = useMemo(
    () => (days.length > 30 ? bucketWeekly(days) : formatDaily(days)),
    [days],
  )

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">Views over time</h3>
      {chartData.length === 0 ? (
        <p className="text-muted text-sm">No data for selected range.</p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData} margin={{ left: 0, right: 8, top: 0, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => [v as number, 'Views']} />
            <Bar
              dataKey="views"
              fill="var(--color-accent, #6366f1)"
              fillOpacity={0.75}
              radius={[2, 2, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/analytics/ViewsOverTimeChart.tsx frontend/src/components/admin/analytics/__tests__/ViewsOverTimeChart.test.tsx
git commit -m "feat: add ViewsOverTimeChart with auto daily/weekly bucketing"
```

---

## Task 11: Frontend — TopPagesPanel Component

**Files:**
- Create: `frontend/src/components/admin/analytics/TopPagesPanel.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/TopPagesPanel.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/TopPagesPanel.test.tsx`:

```typescript
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { SWRConfig } from 'swr'
import TopPagesPanel from '../TopPagesPanel'

const mockFetchPathReferrers = vi.fn()
vi.mock('@/api/analytics', () => ({
  fetchPathReferrers: (...args: unknown[]) => mockFetchPathReferrers(...args) as unknown,
}))

const paths = [
  { path_id: 1, path: '/post/hello', views: 100 },
  { path_id: 2, path: '/post/world', views: 50 },
]

function renderPanel() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <TopPagesPanel paths={paths} />
    </SWRConfig>,
  )
}

describe('TopPagesPanel', () => {
  it('renders page paths sorted by views', () => {
    renderPanel()
    expect(screen.getByText('/post/hello')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('/post/world')).toBeInTheDocument()
  })

  it('shows empty message when no paths', () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <TopPagesPanel paths={[]} />
      </SWRConfig>,
    )
    expect(screen.getByText(/no page data/i)).toBeInTheDocument()
  })

  it('expands inline referrers on row click', async () => {
    mockFetchPathReferrers.mockResolvedValue({
      path_id: 1,
      referrers: [{ referrer: 'Google', count: 40 }],
    })
    renderPanel()
    await userEvent.click(screen.getByText('/post/hello'))
    await waitFor(() => {
      expect(screen.getByText('Google')).toBeInTheDocument()
      expect(screen.getByText('40')).toBeInTheDocument()
    })
  })

  it('collapses referrers when clicking same row again', async () => {
    mockFetchPathReferrers.mockResolvedValue({
      path_id: 1,
      referrers: [{ referrer: 'Google', count: 40 }],
    })
    renderPanel()
    await userEvent.click(screen.getByText('/post/hello'))
    await waitFor(() => expect(screen.getByText('Google')).toBeInTheDocument())
    await userEvent.click(screen.getByText('/post/hello'))
    await waitFor(() => expect(screen.queryByText('Google')).not.toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend` (unsandboxed)
Expected: FAIL

- [ ] **Step 3: Implement TopPagesPanel**

Create `frontend/src/components/admin/analytics/TopPagesPanel.tsx`:

```typescript
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { usePathReferrers } from '@/hooks/useAnalyticsDashboard'
import type { PathHit } from '@/api/client'

interface TopPagesPanelProps {
  paths: PathHit[]
}

export default function TopPagesPanel({ paths }: TopPagesPanelProps) {
  const [expandedPathId, setExpandedPathId] = useState<number | null>(null)
  const { data: referrerData, isLoading: referrersLoading, error: referrerError } = usePathReferrers(expandedPathId)

  const sorted = [...paths].sort((a, b) => b.views - a.views)

  function handleRowClick(pathId: number) {
    setExpandedPathId(expandedPathId === pathId ? null : pathId)
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">Top pages</h3>
      {sorted.length === 0 ? (
        <p className="text-muted text-sm">No page data for selected range.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted font-medium">Page path</th>
                <th className="text-right py-2 text-muted font-medium">Views</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <>
                  <tr
                    key={p.path}
                    role="button"
                    tabIndex={0}
                    className={`border-b border-border last:border-0 cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40 ${
                      expandedPathId === p.path_id ? 'bg-accent/5' : 'hover:bg-base'
                    }`}
                    onClick={() => handleRowClick(p.path_id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleRowClick(p.path_id)
                      }
                    }}
                    aria-label={`View referrers for ${p.path}`}
                    aria-expanded={expandedPathId === p.path_id}
                  >
                    <td className={`py-2 pr-4 font-mono text-xs ${expandedPathId === p.path_id ? 'text-accent font-semibold' : 'text-ink'}`}>
                      {p.path}
                    </td>
                    <td className="py-2 text-right text-ink">{p.views.toLocaleString()}</td>
                  </tr>
                  {expandedPathId === p.path_id && (
                    <tr key={`${p.path}-refs`}>
                      <td colSpan={2} className="p-0">
                        <div className="ml-3 border-l-2 border-accent pl-3 py-2">
                          {referrersLoading ? (
                            <div className="flex items-center py-2" role="status" aria-label="Loading">
                              <Loader2 size={14} className="text-accent animate-spin" />
                            </div>
                          ) : referrerError !== undefined ? (
                            <p className="text-xs text-red-600 dark:text-red-400">Failed to load referrers.</p>
                          ) : (referrerData?.referrers.length ?? 0) === 0 ? (
                            <p className="text-muted text-xs">No referrers for this page.</p>
                          ) : (
                            <table className="w-full text-xs">
                              <tbody>
                                {referrerData?.referrers.map((r) => (
                                  <tr key={r.referrer} className="border-b border-border/50 last:border-0">
                                    <td className="py-1 text-ink">{r.referrer}</td>
                                    <td className="py-1 text-right text-muted">{r.count.toLocaleString()}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/analytics/TopPagesPanel.tsx frontend/src/components/admin/analytics/__tests__/TopPagesPanel.test.tsx
git commit -m "feat: add TopPagesPanel with inline referrer expansion"
```

---

## Task 12: Frontend — TopReferrersPanel Component

**Files:**
- Create: `frontend/src/components/admin/analytics/TopReferrersPanel.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/TopReferrersPanel.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/TopReferrersPanel.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TopReferrersPanel from '../TopReferrersPanel'

describe('TopReferrersPanel', () => {
  it('renders referrers sorted by count', () => {
    const referrers = [
      { referrer: 'Google', count: 100 },
      { referrer: 'Twitter', count: 50 },
    ]
    render(<TopReferrersPanel referrers={referrers} isLoading={false} />)
    expect(screen.getByText('Google')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('Twitter')).toBeInTheDocument()
  })

  it('shows empty message when no referrers', () => {
    render(<TopReferrersPanel referrers={[]} isLoading={false} />)
    expect(screen.getByText(/no referrer data/i)).toBeInTheDocument()
  })

  it('shows loading spinner', () => {
    render(<TopReferrersPanel referrers={[]} isLoading={true} />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Implement TopReferrersPanel**

Create `frontend/src/components/admin/analytics/TopReferrersPanel.tsx`:

```typescript
import { Loader2 } from 'lucide-react'
import type { ReferrerEntry } from '@/api/client'

interface TopReferrersPanelProps {
  referrers: ReferrerEntry[]
  isLoading: boolean
}

export default function TopReferrersPanel({ referrers, isLoading }: TopReferrersPanelProps) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">Top referrers</h3>
      {isLoading ? (
        <div className="flex items-center justify-center py-6" role="status" aria-label="Loading">
          <Loader2 size={16} className="text-accent animate-spin" />
        </div>
      ) : referrers.length === 0 ? (
        <p className="text-muted text-sm">No referrer data for selected range.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted font-medium">Referrer</th>
                <th className="text-right py-2 text-muted font-medium">Count</th>
              </tr>
            </thead>
            <tbody>
              {referrers.map((r) => (
                <tr key={r.referrer} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-ink">{r.referrer}</td>
                  <td className="py-2 text-right text-ink">{r.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/analytics/TopReferrersPanel.tsx frontend/src/components/admin/analytics/__tests__/TopReferrersPanel.test.tsx
git commit -m "feat: add TopReferrersPanel component"
```

---

## Task 13: Frontend — BreakdownBarChart Component

**Files:**
- Create: `frontend/src/components/admin/analytics/BreakdownBarChart.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/BreakdownBarChart.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/BreakdownBarChart.test.tsx`:

```typescript
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { SWRConfig } from 'swr'
import BreakdownBarChart from '../BreakdownBarChart'

globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const mockFetchBreakdownDetail = vi.fn()
vi.mock('@/api/analytics', () => ({
  fetchBreakdownDetail: (...args: unknown[]) => mockFetchBreakdownDetail(...args) as unknown,
}))

const entries = [
  { name: 'Chrome', count: 500, percent: 72.3 },
  { name: 'Firefox', count: 192, percent: 27.7 },
]

function renderChart(props: { drillDown?: boolean } = {}) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <BreakdownBarChart
        title="Browsers"
        entries={entries}
        drillDownCategory={props.drillDown ? 'browsers' : undefined}
      />
    </SWRConfig>,
  )
}

describe('BreakdownBarChart', () => {
  it('renders title and entries', () => {
    renderChart()
    expect(screen.getByText('Browsers')).toBeInTheDocument()
  })

  it('shows empty message when no entries', () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <BreakdownBarChart title="Browsers" entries={[]} />
      </SWRConfig>,
    )
    expect(screen.getByText(/no data/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Implement BreakdownBarChart**

Create `frontend/src/components/admin/analytics/BreakdownBarChart.tsx`:

```typescript
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useBreakdownDetail } from '@/hooks/useAnalyticsDashboard'
import type { BreakdownEntry, BreakdownDetailCategory } from '@/api/client'

interface BreakdownBarChartProps {
  title: string
  entries: BreakdownEntry[]
  drillDownCategory?: BreakdownDetailCategory
}

export default function BreakdownBarChart({
  title,
  entries,
  drillDownCategory,
}: BreakdownBarChartProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  // GoatCounter uses 1-based IDs matching the entry order from the stats response.
  // The expanded entry's ID is its 1-based position in the original entries array.
  const expandedEntryId = expandedIndex !== null ? expandedIndex + 1 : null
  const { data: detailData, isLoading: detailLoading, error: detailError } = useBreakdownDetail(
    drillDownCategory ?? null,
    expandedEntryId,
  )

  const displayEntries = entries.slice(0, 8)

  function handleEntryClick(index: number) {
    if (!drillDownCategory) return
    setExpandedIndex(expandedIndex === index ? null : index)
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">{title}</h3>
      {displayEntries.length === 0 ? (
        <p className="text-muted text-sm">No data.</p>
      ) : (
        <div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart
              data={displayEntries}
              layout="vertical"
              margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
            >
              <XAxis type="number" tick={{ fontSize: 10 }} unit="%" />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 10, cursor: drillDownCategory ? 'pointer' : 'default' }}
                width={70}
                onClick={(_data: unknown, index: number) => handleEntryClick(index)}
              />
              <Tooltip formatter={(v) => [`${v as number}%`, 'Share']} />
              <Bar
                dataKey="percent"
                fill="var(--color-accent, #6366f1)"
                fillOpacity={0.75}
                cursor={drillDownCategory ? 'pointer' : 'default'}
                onClick={(_data: unknown, index: number) => handleEntryClick(index)}
              />
            </BarChart>
          </ResponsiveContainer>
          {drillDownCategory && expandedIndex !== null && (
            <div className="ml-3 border-l-2 border-accent pl-3 py-2 mt-2">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-ink">
                  {displayEntries[expandedIndex]?.name} versions
                </span>
                <button
                  onClick={() => setExpandedIndex(null)}
                  className="text-xs text-muted hover:text-ink transition-colors"
                >
                  Close
                </button>
              </div>
              {detailLoading ? (
                <div className="flex items-center py-2" role="status" aria-label="Loading">
                  <Loader2 size={14} className="text-accent animate-spin" />
                </div>
              ) : detailError !== undefined ? (
                <p className="text-xs text-red-600 dark:text-red-400">Failed to load versions.</p>
              ) : (detailData?.entries.length ?? 0) === 0 ? (
                <p className="text-muted text-xs">No version data.</p>
              ) : (
                <table className="w-full text-xs">
                  <tbody>
                    {detailData?.entries.map((e) => (
                      <tr key={e.name} className="border-b border-border/50 last:border-0">
                        <td className="py-1 text-ink">{e.name}</td>
                        <td className="py-1 text-right text-muted">{e.percent.toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/analytics/BreakdownBarChart.tsx frontend/src/components/admin/analytics/__tests__/BreakdownBarChart.test.tsx
git commit -m "feat: add BreakdownBarChart with optional version drill-down"
```

---

## Task 14: Frontend — BreakdownTable Component

**Files:**
- Create: `frontend/src/components/admin/analytics/BreakdownTable.tsx`
- Create: `frontend/src/components/admin/analytics/__tests__/BreakdownTable.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/admin/analytics/__tests__/BreakdownTable.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import BreakdownTable from '../BreakdownTable'

describe('BreakdownTable', () => {
  it('renders title and entries', () => {
    const entries = [
      { name: 'United States', count: 100, percent: 45.0 },
      { name: 'Germany', count: 50, percent: 22.7 },
    ]
    render(<BreakdownTable title="Locations" nameLabel="Country" entries={entries} />)
    expect(screen.getByText('Locations')).toBeInTheDocument()
    expect(screen.getByText('United States')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('45.0%')).toBeInTheDocument()
  })

  it('shows empty message when no entries', () => {
    render(<BreakdownTable title="Locations" nameLabel="Country" entries={[]} />)
    expect(screen.getByText(/no data/i)).toBeInTheDocument()
  })

  it('uses custom name label', () => {
    const entries = [{ name: 'English', count: 80, percent: 68.0 }]
    render(<BreakdownTable title="Languages" nameLabel="Language" entries={entries} />)
    expect(screen.getByText('Language')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Implement BreakdownTable**

Create `frontend/src/components/admin/analytics/BreakdownTable.tsx`:

```typescript
import type { BreakdownEntry } from '@/api/client'

interface BreakdownTableProps {
  title: string
  nameLabel: string
  entries: BreakdownEntry[]
}

export default function BreakdownTable({ title, nameLabel, entries }: BreakdownTableProps) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">{title}</h3>
      {entries.length === 0 ? (
        <p className="text-muted text-sm">No data.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted font-medium">{nameLabel}</th>
                <th className="text-right py-2 pr-4 text-muted font-medium">Visitors</th>
                <th className="text-right py-2 text-muted font-medium">%</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.name} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-ink">{e.name}</td>
                  <td className="py-2 pr-4 text-right text-ink">{e.count.toLocaleString()}</td>
                  <td className="py-2 text-right text-muted">{e.percent.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/analytics/BreakdownTable.tsx frontend/src/components/admin/analytics/__tests__/BreakdownTable.test.tsx
git commit -m "feat: add BreakdownTable component for locations, languages, campaigns"
```

---

## Task 15: Frontend — Rewrite AnalyticsPanel Orchestrator

**Files:**
- Rewrite: `frontend/src/components/admin/AnalyticsPanel.tsx`
- Rewrite: `frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx`

- [ ] **Step 1: Rewrite AnalyticsPanel.tsx as orchestrator**

Replace the contents of `frontend/src/components/admin/AnalyticsPanel.tsx`. The component now:

1. Owns `DateRange` state (starts as `'7d'`)
2. Calls `useAnalyticsDashboard(dateRange)` for the main composite fetch
3. Calls `useSiteReferrers(dateRange, analyticsEnabled)` for site-wide referrers
4. Renders `DateRangePicker`, toggles, and `ExportButton` in the top bar
5. Renders summary cards (unchanged logic)
6. Renders `ViewsOverTimeChart`
7. Renders `TopPagesPanel` + `TopReferrersPanel` side by side
8. Renders `BreakdownBarChart` for browsers and OS (with `drillDownCategory`)
9. Renders `BreakdownTable` for locations and languages
10. Renders `BreakdownBarChart` for screen sizes + `BreakdownTable` for campaigns

Keep the existing `ToggleSwitch` as a local component. Keep the existing error handling, loading, and unavailable states. Keep the `busy`/`onBusyChange` contract.

The key structural change: all panel-specific rendering is delegated to the extracted components. `AnalyticsPanel` handles only layout, state, and data flow.

- [ ] **Step 2: Update integration tests**

Rewrite `frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx` to:
- Mock the additional fetch functions (`fetchViewsOverTime`, `fetchSiteReferrers`)
- Add defaults for new breakdown categories and views-over-time data
- Test that new panels render (views-over-time chart, referrers panel, locations, languages, screen sizes, campaigns)
- Keep existing tests for: loading, settings toggles, error handling, 401, date range buttons
- Add tests for custom date range interaction
- Add test for Export CSV button presence

Update the `mockFetchBreakdown` implementation to handle all six categories:

```typescript
mockFetchBreakdown.mockImplementation((category: string) => {
  const responses: Record<string, unknown> = {
    browsers: DEFAULT_BROWSERS,
    systems: DEFAULT_SYSTEMS,
    languages: { category: 'languages', entries: [{ name: 'English', count: 80, percent: 68.0 }] },
    locations: { category: 'locations', entries: [{ name: 'US', count: 100, percent: 45.0 }] },
    sizes: { category: 'sizes', entries: [{ name: '1920x1080', count: 60, percent: 38.0 }] },
    campaigns: { category: 'campaigns', entries: [] },
  }
  return Promise.resolve(responses[category] ?? { category, entries: [] })
})
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `just test-frontend` (unsandboxed)
Expected: PASS

- [ ] **Step 4: Run full check**

Run: `just check` (unsandboxed)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin/AnalyticsPanel.tsx frontend/src/components/admin/__tests__/AnalyticsPanel.test.tsx
git commit -m "feat: rewrite AnalyticsPanel as orchestrator with extracted components"
```

---

## Task 16: Update Architecture Docs

**Files:**
- Modify: `docs/arch/analytics.md`
- Modify: `docs/arch/frontend.md`

- [ ] **Step 1: Update analytics.md**

Add a section about the enhanced dashboard panels, new backend endpoints, and export functionality. Update the "UI Placement" section to list all panels. Update "Code Entry Points" to include the new component directory.

- [ ] **Step 2: Update frontend.md**

Mention the extracted analytics component directory `frontend/src/components/admin/analytics/` and the extended hooks.

- [ ] **Step 3: Commit**

```bash
git add docs/arch/analytics.md docs/arch/frontend.md
git commit -m "docs: update architecture docs for analytics dashboard parity"
```

---

## Task 17: End-to-End Verification

- [ ] **Step 1: Run full static checks and tests**

Run: `just check` (unsandboxed)
Expected: All checks and tests pass

- [ ] **Step 2: Start dev server and visual verification**

Run: `just start` (unsandboxed)

Open the admin panel analytics tab. Verify:
- Date range presets and custom date picker work
- Views-over-time chart renders
- Top pages table shows inline referrer expansion on click
- Site-wide referrers panel shows data
- All six breakdown panels render (browsers, OS, locations, languages, screen sizes, campaigns)
- Browser/OS version drill-down works on click
- Export CSV button triggers download flow
- Analytics toggles still function correctly
- All panels show empty states gracefully when no data

- [ ] **Step 3: Stop dev server**

Run: `just stop` (unsandboxed)

- [ ] **Step 4: Clean up any screenshots**

Remove any leftover `.png` screenshot files from browser testing.
