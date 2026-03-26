# Timezone UTC Normalization Design

## Problem

Date filtering by the user's chosen dates doesn't account for the user's timezone. The frontend sends bare `YYYY-MM-DD` strings, and the backend interprets them as UTC midnight boundaries. A user in UTC+5 filtering for "March 1" actually filters against UTC midnight — missing posts created during their local March 1 but before UTC March 1.

## Goals

- Filter dates should respect the user's local timezone.
- The backend should always operate on UTC internally.
- The frontend should handle all timezone conversion at the API boundary.
- Rename `default_tz` to `fallback_tz` in `parse_datetime` to clarify its purpose.

## Design

### Frontend: convert filter dates to UTC at the API call site

The `<input type="date">` gives `"2026-03-01"`. The filter panel state keeps these plain `YYYY-MM-DD` strings (they drive the date picker UI). At the point where the frontend builds the API request, it converts:

- **`fromDate`**: start of that day in the user's local timezone, converted to a UTC ISO string. Example: user in UTC+5 picks March 1 -> `"2026-02-28T19:00:00.000Z"`.
- **`toDate`**: end of that day in the user's local timezone, converted to a UTC ISO string. Example: `"2026-03-01T18:59:59.999Z"`.

Add a utility function in `frontend/src/utils/date.ts`:

```typescript
export function localDateToUtcStart(dateStr: string): string
export function localDateToUtcEnd(dateStr: string): string
```

These use the browser's native `Date` constructor (which interprets `YYYY-MM-DD` + time components in local timezone) and `.toISOString()` to produce UTC strings.

### Backend: simplified filter parsing in `post_service.py`

The filter code stops appending `00:00:00` / `23:59:59.999999` and hardcoding `"UTC"`. It parses the received value directly with `parse_datetime()`. If a bare date is sent (backwards compat), `fallback_tz="UTC"` still applies as a safe default.

### Backend: rename `default_tz` to `fallback_tz`

Rename the parameter in `parse_datetime()` and update all call sites:

- `backend/services/datetime_service.py` — function signature and docstring
- `backend/filesystem/frontmatter.py` — `parse_post()` passes site config timezone
- `backend/services/post_service.py` — filter parsing (will use default)
- `backend/services/sync_service.py` — `normalize_post_frontmatter()` (uses default UTC)

### No changes to

- **Date display**: `date-fns` `parseISO` already respects the offset in ISO strings from the API, and displays in the browser's local timezone.
- **Front matter parsing**: keeps using the site config timezone as `fallback_tz` for ambiguous date-only values.
- **API response serialization**: `format_iso()` already emits offset-aware ISO strings.
- **Database storage**: `DateTime(timezone=True)` columns remain unchanged.

## Files changed

| File | Change |
|------|--------|
| `backend/services/datetime_service.py` | Rename `default_tz` to `fallback_tz` |
| `backend/filesystem/frontmatter.py` | Update kwarg name |
| `backend/services/post_service.py` | Update kwarg name, simplify filter date parsing |
| `backend/services/sync_service.py` | Update kwarg name |
| `frontend/src/utils/date.ts` | Add `localDateToUtcStart`, `localDateToUtcEnd` |
| `frontend/src/utils/__tests__/date.test.ts` | Tests for new utilities |
| `frontend/src/hooks/usePosts.ts` (or equivalent API call site) | Apply conversion before sending filter params |
| `backend/filesystem/content_manager.py` | Update kwarg name |
| `tests/test_services/test_datetime_service.py` | Update parameter name in tests |
| `tests/test_services/test_datetime_service_hypothesis.py` | Update parameter name in tests |
| `tests/test_services/test_crash_hunting_high.py` | Update parameter name in tests |
| `tests/test_rendering/test_frontmatter_parsing_hypothesis.py` | Update parameter name in tests |
