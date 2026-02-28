# Exception Handling Review

**Date:** 2026-02-28

Review of exception handling across the entire backend codebase, assessing error handling completeness, internal vs business logic error separation, information leakage, error message clarity, and crash resilience.

---

## 1. Are all errors handled properly?

**Overall: Good, with gaps.** The project has a well-designed layered error handling architecture:
- Global exception handlers in `backend/main.py` catch 12+ exception types as a safety net
- Services raise `ValueError` (business logic) or `InternalServerError` (sensitive errors)
- Route handlers translate service errors to HTTP responses

### Gaps

| Location | Issue |
|---|---|
| `backend/pandoc/renderer.py:323` | Retry after pandoc restart only catches `httpx.HTTPError`, not `httpx.NetworkError` — a second network failure escapes unhandled |
| `backend/services/page_service.py:42` | `render_markdown()` call has no error handling — if pandoc fails, exception escapes to global handler rather than being handled locally |
| `backend/api/pages.py:36` | `get_page()` has no try/except — rendering or I/O errors propagate unhandled |
| `backend/api/render.py:39-43` | Only catches `RenderError`, not other possible exceptions from `render_markdown()` |
| `backend/crosspost/{x,facebook,mastodon}.py` | OAuth exchange functions make HTTP calls without service-level error handling, relying entirely on API-layer catch blocks |

---

## 2. Are internal server errors correctly distinguished from business logic errors?

**Overall: Well-designed convention, mostly followed.** The codebase has a clear two-tier system documented in `backend/exceptions.py`:

- **`InternalServerError`** — for sensitive internal details (decryption failures, config errors, infrastructure issues). Global handler returns generic `"Internal server error"`.
- **`ValueError`** — for business logic validation safe to forward to clients. Global handler forwards `str(exc)`.

### Issues with the distinction

| Location | Issue |
|---|---|
| `backend/api/labels.py:52-57, 62-71` | Catches bare `except Exception` instead of specific types — conflates all failures as 500 errors |
| `backend/api/posts.py:289, 472, 614` | Multiple bare `except Exception` blocks — treats all errors identically regardless of cause |
| `backend/api/crosspost.py:131-139` | Uses fragile `str(exc).startswith("Post not found")` string matching to route between 404 and 400 |
| `backend/api/admin.py:187-189` | Uses `"built-in" in str(exc)` to decide between 400 and 404 — fragile string-based dispatch |

---

## 3. Do internal server errors incorrectly leak error details to clients?

**This is the most significant category of issues.** Multiple locations forward raw exception messages to clients:

| Location | Leaked Detail | Severity |
|---|---|---|
| `backend/api/crosspost.py:245-246` | `detail=str(exc)` for `ATProtoOAuthError` — exposes OAuth internals | High |
| `backend/api/crosspost.py:317-318` | `detail=f"Token exchange failed: {exc}"` — OAuth error details | High |
| `backend/api/crosspost.py:440-443` | `detail=f"Could not connect to Mastodon instance: {exc}"` — raw httpx error | High |
| `backend/api/crosspost.py:523-529` | `detail=f"Mastodon OAuth HTTP error: {exc}"` — raw httpx error | High |
| `backend/api/crosspost.py:691-692` | `detail=f"X OAuth HTTP error: {exc}"` — raw httpx error | High |
| `backend/api/sync.py:209-210` | `detail=f"Invalid metadata JSON: {exc}"` — raw JSON parse error | Medium |
| `backend/services/crosspost_service.py:229-236` | `error=str(exc)` in `CrossPostResult` for bare `except Exception` — any error message | Medium |

These all violate the project's own guideline: *"Never expose internal server error details to clients."*

---

## 4. Do business logic errors correctly propagate understandable error messages?

**Mostly yes**, with some concerns.

### Well-handled examples

- `label_service.py` — "Adding parent '{parent_id}' would create a cycle" (clear, actionable)
- `datetime_service.py` — "Cannot parse date from: {value_str}" (user-friendly)
- `post_service.py` — "Invalid 'from' date format: {from_date!r}. Expected YYYY-MM-DD." (prescriptive)
- Auth endpoints — "Not authenticated", "Admin access required", "Too many failed attempts" (appropriate)

### Concerns

| Location | Issue |
|---|---|
| `backend/api/admin.py:118` | `detail=str(exc)` for `ValueError` — forwards raw error which _could_ be fine, but relies on every `ValueError` in the call chain having a client-safe message |
| `backend/api/admin.py:188-189` | Same pattern — forwards ValueError messages without sanitization |
| `backend/api/crosspost.py:138` | `detail=str(exc)` for generic ValueError catch-all — any ValueError from any nested call gets forwarded |

The risk is that a future code change could introduce a `ValueError` with internal details, and it would be automatically forwarded to clients.

---

## 5. Can an error ever crash the server?

**The server is well-protected against crashes, with one notable gap.**

### Protected

- Global exception handlers catch all major exception categories (`RuntimeError`, `OSError`, `ValueError`, `TypeError`, `OperationalError`, `subprocess.CalledProcessError`, etc.)
- Startup validation failures in `backend/config.py` are intentionally fatal (correct — better to refuse to start than run insecurely)
- Shutdown errors are caught and logged without re-raising
- Async database operations are properly awaited
- The pandoc server has restart-on-failure with locking

### Potential crash paths

| Location | Scenario |
|---|---|
| `backend/pandoc/renderer.py:323-324` | If the pandoc retry after restart raises `httpx.NetworkError` (not `httpx.HTTPError`), the exception escapes. The global `RuntimeError` handler in `main.py` would catch it since `RenderError` extends `RuntimeError`, but the pandoc-specific error context is lost. If it raises a raw `httpx.NetworkError` (not `RenderError`), it would not match any specific global handler and would fall through to a generic handler depending on the subclass hierarchy. |
| `backend/main.py:410` | The `OSError` handler explicitly re-raises `ConnectionError` and `TimeoutError` — these would propagate as unhandled 500s. FastAPI/Starlette middleware should still catch them, but the behavior is undocumented. |

**Verdict:** The server will not crash from user requests. The global handlers in `main.py` form a comprehensive safety net. The worst case is an unhandled exception type returning a generic 500 response via Starlette's default handler.

---

## Summary of Priorities

| Priority | Count | Category |
|---|---|---|
| **High** | 5 | Error detail leakage to clients in crosspost routes |
| **Medium** | 7 | Bare `except Exception` blocks, fragile string-based error dispatch, missing local error handling |
| **Low** | 3 | Missing service-level error handling for external calls (covered by API layer), style issues |

### Recommended fixes

1. **Fix error detail leakage in `backend/api/crosspost.py`** (5 locations) — log details server-side and return generic messages like `"External service error"` or `"OAuth authentication failed"`.
2. **Replace bare `except Exception` blocks** in `labels.py`, `posts.py` with specific exception types (`OSError`, `ValueError`, etc.).
3. **Replace string-based error dispatch** in `crosspost.py:131-139` and `admin.py:187-189` with typed exceptions (e.g., `PostNotFoundError`, `BuiltinPageError`).
4. **Fix pandoc retry exception coverage** in `renderer.py:323-324` — catch `httpx.NetworkError` in addition to `httpx.HTTPError`.
5. **Add local error handling** for `render_markdown()` calls in `page_service.py:42` and `pages.py:36`.
6. **Sanitize crosspost service error messages** in `crosspost_service.py:229-236` — don't forward raw `str(exc)` to clients.
