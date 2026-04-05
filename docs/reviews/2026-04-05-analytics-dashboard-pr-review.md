# Analytics Dashboard PR Review (Last 12 Commits)

> **GoatCounter API validation:** All GoatCounter API claims verified against live `api.json` spec
> (fetched April 2026). See [GoatCounter API](https://www.goatcounter.com/api).

## Scope

12 commits adding a full analytics dashboard: backend service/schema/API
(`analytics_service.py`, `analytics.py`, `schemas/analytics.py`), frontend components
(`AnalyticsPanel`, 6 sub-components, hooks), and tests on both sides.

---

## Critical Issues (Must Fix Before Merge)

### 1. `fetch_views_over_time` reads non-existent `"days"` field — chart always empty
**`backend/services/analytics_service.py:629-637`**

GoatCounter's `HitListStat` has no `days` field. Confirmed by `api.json`:
actual fields are `day` (date string), `daily` (int), `hourly` (array), `weekly`, `monthly`.
The code iterates `stat_block.get("days", [])` which always returns `[]`, making the
Views Over Time chart permanently empty. The tests fabricate a `"days"` key that never
exists in real responses.

**Fix:** Iterate `data["hits"]` entries, then their `stats` array, and accumulate
`stat_block.get("daily", 0)` keyed by `stat_block["day"]`:

```python
for entry in data.get("hits", []):
    for stat_block in entry.get("stats", []):
        day = stat_block.get("day", "")
        if not day:
            continue
        daily_count = stat_block.get("daily", 0)
        if isinstance(daily_count, int):
            day_totals[day] = day_totals.get(day, 0) + daily_count
```

Update existing tests to use the correct GoatCounter response shape.

---

### 2. Breakdown drill-down uses array index instead of GoatCounter entry ID
**`frontend/src/components/admin/analytics/BreakdownBarChart.tsx:92`**,
**`backend/schemas/analytics.py:127-161`**

GoatCounter `HitStat` entries have an `id` field (string, confirmed by `api.json`:
`"ID for selecting more details"`). `BreakdownEntry` discards it; the frontend falls back
to `entryId = index` (0-based display rank). GoatCounter's
`GET /api/v0/stats/{category}/{entry_id}` expects the actual entry ID — passing an
array index returns wrong or missing data for almost every drill-down.

**Note:** The GoatCounter `id` field is a **string**, not an integer. The current
backend uses `int` for `entry_id` — this needs to change to `str` end-to-end.

**Fix:** Add `gc_id: str | None = None` to `BreakdownEntry` schema and populate it from
`entry.get("id")`. Change `fetch_breakdown_detail(entry_id: int)` → `entry_id: str`.
Change the API path param from `int` to `str`. Update frontend types, hook, and
`BreakdownBarChart` to use `entry.gcId` instead of `index`.

---

### 3. `_offset_date` raises unhandled `ValueError` on malformed GoatCounter dates
**`backend/services/analytics_service.py:603-608`**

`date.fromisoformat(base_date)` raises `ValueError` on any non-empty malformed string
from GoatCounter (e.g., `"N/A"`, future API format changes). The exception propagates
through `fetch_views_over_time` uncaught, producing an opaque 500 with no analytics
context in the log.

**Fix:** Wrap in try/except, log a warning, return `None`; skip `None` results:

```python
def _offset_date(base_date: str, offset: int) -> str | None:
    from datetime import date, timedelta
    try:
        d = date.fromisoformat(base_date)
        return (d + timedelta(days=offset)).isoformat()
    except (ValueError, OverflowError):
        logger.warning("Invalid day value %r from GoatCounter stats block", base_date)
        return None
```

*(Now moot after fix #1 — no more offset arithmetic needed — but still good defensive code.)*

---

### 4. Comment in `BreakdownBarChart.tsx` is self-contradictory and misleading
**`frontend/src/components/admin/analytics/BreakdownBarChart.tsx:89-91`**

The 3-line comment claims `count` can proxy for a GoatCounter ID, then says index is the
fallback "per the API shape." The GoatCounter API shape has nothing to do with 0-based
array indices. The comment obscures a design bug rather than documenting it.

**Fix:** Remove the comment block entirely. The underlying bug (issue 2) should be fixed.

---

## Important Issues (Should Fix)

### 5. N+1 HTTP requests in `fetch_site_referrers`
**`backend/services/analytics_service.py:471-512`**

Issues 1 + N requests per call. GoatCounter's `GET /api/v0/stats/toprefs` (confirmed
valid by `api.json`) returns aggregated site-wide referrers in a single call.
`CLAUDE.md` rule: "Avoid N+1 query problems."

**Fix:** Replace the fan-out with:
```python
data = await _stats_request("/api/v0/stats/toprefs", params or None)
referrers = [
    ReferrerEntry.from_goatcounter(entry)
    for entry in data.get("stats", [])
    if isinstance(entry, dict)
]
return SiteReferrersResponse(referrers=sorted(referrers, key=lambda r: r.count, reverse=True))
```

---

### 6. `daily=true` parameter is deprecated in GoatCounter API
**`backend/services/analytics_service.py:622`**

Confirmed by `api.json`: *"Deprecated: identical to `group=day` and will be removed in
the future."*

**Fix:** `params["group"] = "day"` instead of `params["daily"] = "true"`.

*(Now only applies if offset-based aggregation is kept; after fix #1 this is moot since
`group=day` / `daily=true` is no longer needed for the new daily-integer approach. The
`daily` integer field is always present in `HitListStat` regardless of `group`.)*

---

### 7. `create_export` / `get_export_status` / `download_export` — ambiguous `None` for disabled vs. failed
**`backend/api/analytics.py:253-292`**

Both "analytics disabled" and "GoatCounter unavailable" produce 503. An admin who
disabled analytics and clicks Export sees "Analytics service unavailable" rather than
a meaningful error. In practice the Export button is already disabled when analytics is
off, so this is defense-in-depth rather than a UX regression.

**Suggested fix:** Distinguish with an `AnalyticsDisabledError` exception and 409 at the
API layer. Lower priority since the UI guard prevents the case in normal usage.

---

### 8. `fetch_site_referrers` silently drops all exceptions from parallel requests
**`backend/services/analytics_service.py:494-505`** *(moot after fix #5)*

`asyncio.gather(..., return_exceptions=True)` + silent discard means programming errors
(`TypeError`, etc.) are swallowed with no log entry. If fix #5 (toprefs) is applied
this code is removed entirely. If N+1 is kept, add:

```python
if isinstance(ref_data, BaseException):
    logger.warning("Referrer fetch failed for one path", exc_info=ref_data)
    continue
```

---

### 9. `ExportButton` catch block discards all errors and conflates 401/503/network
**`frontend/src/components/admin/analytics/ExportButton.tsx:53-55`**

`catch {}` has no bound variable — the error is completely discarded. A 401 (session
expired) shows "Export failed. Please try again." — retrying never works.

**Fix:**
```typescript
} catch (err) {
  if (err instanceof HTTPError && err.response.status === 401) {
    setError('Session expired. Please log in again.')
  } else {
    setError('Export failed. Please try again.')
  }
}
```

---

### 10. `useSiteReferrers` error discarded in `AnalyticsPanel`
**`frontend/src/components/admin/AnalyticsPanel.tsx:74-77`**

The `error` field is not destructured. On failure, `TopReferrersPanel` shows
"No referrer data for selected range" — indistinguishable from legitimate empty data.

**Fix:** Destructure `error`, pass it to `TopReferrersPanel`, display a distinct error
message.

---

### 11. `useAnalyticsDashboard` uses `Promise.all` — one failing endpoint kills the whole dashboard
**`frontend/src/hooks/useAnalyticsDashboard.ts:132-165`**

One 503 (e.g., locations endpoint) discards all other fetched data and shows the entire
dashboard as unavailable.

**Fix:** Use `Promise.allSettled` and handle per-section failures independently.

---

### 12. `ExportCreateResponse` defaults export ID to `0` on missing field
**`backend/services/analytics_service.py:665`**

`data.get("id", 0)` silently fabricates a fake ID with no log. The frontend then polls
`/export/0/status` for 60 seconds before timing out.

**Fix:** Validate `id` is a positive int; log an error and return `None` if absent.

---

### 13. Invalid date range fires API requests anyway
**`frontend/src/hooks/useAnalyticsDashboard.ts:100-104`**,
**`frontend/src/components/admin/analytics/DateRangePicker.tsx`**

Visual validation fires but `onChange` still propagates, triggering all API requests
with an inverted date window.

**Fix:** Add guard in `getDateRange` — return a sentinel or suppress SWR key when
`start > end`.

---

## Test Gaps

| Gap | File |
|-----|------|
| Analytics-disabled gating not tested for `fetch_views_over_time`, `fetch_site_referrers`, `fetch_breakdown_detail`, `get_export_status`, `download_export` | `test_analytics_stats.py` |
| No 503 tests at API layer for `breakdown_detail`, `export_create`, `export_status`, `export_download` (using service-boundary patch, not `_stats_request`) | `test_analytics_api.py` |
| No happy-path test for `ExportButton` (create → poll → download → anchor trigger) | `ExportButton.test.tsx` |
| `BreakdownDetailEntry.from_goatcounter` has no unit tests | `test_analytics_stats.py` |
| `_offset_date` pure function has no tests (Hypothesis candidate) | `test_analytics_stats.py` |
| Date validation not tested for `views-over-time` and `referrers` endpoints | `test_analytics_api.py` |
| `fetch_site_referrers` partial-failure path not tested | `test_analytics_stats.py` |
| Existing 503 tests for `views-over-time` and `referrers` patch internal `_stats_request` instead of service boundary | `test_analytics_api.py` |

---

## Strengths

- All admin endpoints correctly use `require_admin` — security solid
- `_stats_request` sentinel pattern with `exc_info=True` logging is clean
- `_load_token` correctly distinguishes `FileNotFoundError` from `OSError`
- `fire_background_hit` strong-reference task set prevents GC of fire-and-forget tasks
- Component extraction into `analytics/` sub-components is well-structured
- `TopPagesPanel` tests are behavior-focused and cover 5+ distinct states
- `DateRangePicker` tests cover all visual states including `start > end`
- `AnalyticsPanel` correctly distinguishes 401 from 503 for session expiry
- Architecture docs (`docs/arch/analytics.md`) are accurate and in sync
