# PR Review: GoatCounter Analytics Integration

**Date:** 2026-03-25
**Branch:** `feat/goatcounter-analytics`
**Scope:** ~3300 lines across 38 files
**Review agents:** code-reviewer, pr-test-analyzer, silent-failure-hunter, type-design-analyzer, comment-analyzer

---

## Critical Issues (4)

### 1. Background `_do_hit` tasks have no exception handling around session factory

**Files:** `backend/api/posts.py:754`, `backend/api/pages.py:60`

The `_do_hit()` coroutine has no try/except around `session_factory()`. If creating a session raises (pool exhausted, DB locked), the exception escapes the task entirely -- producing unstructured "Task exception was never retrieved" warnings. Violates CLAUDE.md reliability guidelines.

**Fix:** Wrap entire `_do_hit` body in try/except that logs via the module logger.

### 2. `record_hit` never checks HTTP response status from GoatCounter

**File:** `backend/services/analytics_service.py:183-197`

The POST to GoatCounter's `/api/v0/count` never calls `response.raise_for_status()`. If the token is invalid (401), every hit is silently discarded -- admin sees "0 views" with no indication the token is broken. Contrast with `_stats_request()` which correctly calls `raise_for_status()`.

**Fix:** Add `response.raise_for_status()` after the POST.

### 3. `_load_token` only catches `FileNotFoundError`, not other `OSError` subclasses

**File:** `backend/services/analytics_service.py:64-85`

`PermissionError`, `IsADirectoryError`, `UnicodeDecodeError` all go unhandled with no specific diagnostic message. A misconfigured deployment silently disables analytics with vague warnings.

**Fix:** Catch `OSError` broadly with a specific log message about the token file.

### 4. GoatCounter entrypoint `-perm 2` comment may be wrong

**File:** `goatcounter/entrypoint.sh:20`

Comment says permission level 2 = "read+write". GoatCounter's `-perm` uses a bitmask where 2 = record hits only, 3 = read+write. If this is wrong, stats proxy endpoints silently get 403s (swallowed by `except Exception`), and the admin dashboard shows all zeros.

**Action:** Verify the correct permission level. If both read and write are needed, use `-perm 3`.

---

## Important Issues (7)

### 5. Stats proxy returns zeros instead of signaling unavailability -- frontend "unavailable" UI is dead code

**Files:** `backend/services/analytics_service.py:228-317`, `frontend/src/components/admin/AnalyticsPanel.tsx:138`

When GoatCounter is down, endpoints return 200 with zero data. The frontend `unavailable` state can never be reached since the backend never errors. Admin sees "0 views" and thinks nobody is visiting.

**Fix:** Return 503 or add an `available` flag when GoatCounter is unreachable.

### 6. No input validation on `start`/`end` date parameters

**File:** `backend/api/analytics.py:75-114`

Raw strings forwarded to GoatCounter without format validation. Should use `Query(pattern=r"^\d{4}-\d{2}-\d{2}$")`.

### 7. Empty `.catch(() => {})` on view count fetch

**File:** `frontend/src/pages/PostPage.tsx:98-100`

Violates CLAUDE.md "empty catch blocks are never acceptable." At minimum log to `console.warn`.

### 8. `handlePathClick` silently clears referrers on error

**File:** `frontend/src/components/admin/AnalyticsPanel.tsx:164-175`

Network errors are indistinguishable from "no referrer data." Should show error feedback.

### 9. Singleton `AnalyticsSettings` not enforced at DB level

**File:** `backend/models/analytics.py`

Nothing prevents multiple rows. `autoincrement=True` undermines singleton intent. Concurrent first-use could create duplicate rows (check-then-act race condition).

**Fix:** Add `CheckConstraint("id = 1")`, remove `autoincrement=True`.

### 10. `_load_token` behavior is untested

**File:** `backend/services/analytics_service.py:54-85`

All tests mock `_load_token`. No test covers: cached token, empty file, `FileNotFoundError`, warning deduplication. Regression risk.

### 11. `_stats_request` error handling untested

**File:** `backend/services/analytics_service.py:205-225`

No test verifies that HTTP errors, timeouts, or invalid JSON are caught and return `None`. This is the function responsible for the "server may never crash" guarantee.

---

## Medium Issues (6)

### 12. Auth errors shown as "analytics unavailable"

**File:** `AnalyticsPanel.tsx:138`

A 401 session expiry triggers the same "analytics unavailable" message as a network timeout. Misleading for the admin.

### 13. Missing `ge=0` constraints on count fields

**File:** `backend/schemas/analytics.py`

All count/stat fields lack non-negativity constraints, unlike `PostListResponse.total` and `AssetResponse.size` elsewhere in the codebase.

### 14. `BreakdownCategory` should be a `Literal` type

`category` is `str` in schemas and frontend, but constrained by runtime `frozenset` in the API. A `Literal` union would make valid values self-documenting and eliminate the runtime check.

### 15. Entrypoint boot loop risk

**File:** `goatcounter/entrypoint.sh:13-28`

If `create-apitoken` fails after `create-site` succeeds, restart creates a loop since the site already exists. Guard with `if [ ! -f "$GOATCOUNTER_DB" ]` or check for existing site.

### 16. Shared HTTP client connect timeout too low for stats

**File:** `backend/services/analytics_service.py:46-51`

Client created with 2s hit timeout; stats requests override to 5s but connect timeout stays at 2s.

### 17. `record_hit` with `_load_token` returning `None` is untested

No test verifies graceful skip when token is unavailable (cold start scenario).

---

## Suggestions

### Comments and documentation

- Fix `fetch_breakdown` docstring: "browser, OS, country" should use actual category names ("browsers, systems, locations").
- `record_hit` docstring "Fire-and-forget" is a caller concern -- reword to describe the function's own behavior.
- Add comment on `GOATCOUNTER_URL` linking it to docker-compose service name.
- Remove redundant inline comments in `record_hit` (keep only the "skip authenticated users" one which explains *why*).
- Architecture docs: "when the backend serves a post" should be "when a reader fetches a post through the API."
- Frontend docs: "since it pulls in the Recharts charting library" -- make library name non-load-bearing: "since it pulls in a charting library (currently Recharts)."

### Type design

- Add `Field(ge=0)` to all count/stat fields in Pydantic schemas (`ViewCountResponse.views`, `TotalStatsResponse.total_views`, `TotalStatsResponse.total_unique`, `PathHit.views`, `PathHit.unique`, `ReferrerEntry.count`, `BreakdownEntry.count`).
- Add `Field(ge=0, le=100)` to `BreakdownEntry.percent`.
- Add a model validator to `AnalyticsSettingsUpdate` to reject empty payloads where both fields are `None`.
- Define a `BreakdownCategory` string literal union on the frontend for `fetchBreakdown`'s `category` parameter.

### Test coverage

- Add test for `record_hit` when `_load_token()` returns `None` -- verify `post` is never called.
- Add direct tests for `_load_token`: cached token, empty file, `FileNotFoundError`, warning deduplication.
- Add tests for `_stats_request`: HTTP 500, network timeout, invalid JSON -- all should return `None`.
- Add test for `_fire_post_hit` with non-canonical `file_path` that triggers `ValueError` from `file_path_to_slug`.
- Add test for `close_analytics_client` function path.
- Add test for AnalyticsPanel "Close" button on referrer drill-down.
- Add test for `busy` prop disabling controls in AnalyticsPanel.

---

## Strengths

- Clean separation between API layer and analytics service.
- Proper admin authorization on all admin endpoints with thorough auth gate tests (401/403).
- Bot/crawler filtering with CrawlerDetect.
- Fire-and-forget background tasks with GC prevention via `_background_tasks` set.
- Graceful degradation design (analytics is a soft dependency).
- Good frontend test coverage for loading/error/empty states.
- Deployment tests verify compose file builders include GoatCounter.
- Information disclosure prevention on view count endpoint.
- Progressive logging in `_load_token` (warning on first miss, debug on subsequent).
- Strong cross-boundary type alignment -- every field name, type, and nullability matches between backend Pydantic schemas and frontend TypeScript interfaces.
