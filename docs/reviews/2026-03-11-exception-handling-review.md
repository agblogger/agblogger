# Exception Handling Review

Date: 2026-03-11

## Overview

Review of exception handling across the entire backend: API routes, services, filesystem, pandoc, and crosspost modules. Assessed whether errors are handled properly, internal errors are distinguished from business logic errors, details leak to clients, and whether errors can crash the server.

## Findings

### 1. Are all errors handled properly?

**Mostly yes, with gaps.** The global exception handler system in `main.py` is comprehensive, covering ~18 exception types. However:

**Missing: `httpx.HTTPError` global handler.** The OAuth exchange functions in `backend/crosspost/facebook.py`, `x.py`, `mastodon.py`, and `bluesky.py` make HTTP requests that can throw `httpx.ConnectError`, `httpx.ReadTimeout`, etc. These do NOT extend `RuntimeError` or `OSError`, so they fall through all registered global handlers to Starlette's default 500 — which means they are not logged through the application's structured logging and return `500` instead of the more appropriate `502`.

**Missing: catch-all `Exception` handler.** There is no fallback handler for exception types not explicitly registered. Any novel exception type (e.g., from a new library) would bypass all application logging.

**Unprotected file I/O in `content_manager.py:write_post()` (lines 163-164).** No try/except around `mkdir()` and `write_text()`. The global `OSError` handler prevents a crash, but leaves no opportunity for caller-level cleanup.

**Unprotected file I/O in `api/posts.py:upload_post` (lines 332-338).** Asset writes (`post_dir.mkdir()`, `dest.write_bytes()`) happen before the try/except at line 363. A failure partway through leaves orphaned asset files without cleanup.

**Unprotected file I/O in `content_manager.py:delete_post()` (lines 189, 202, 204).** `raw_post_dir.unlink()`, `shutil.rmtree()`, and `full_path.unlink()` are unprotected — the global handler prevents a crash but the caller gets no chance to handle partial failure.

### 2. Are internal server errors correctly distinguished from business logic errors?

**Yes, well-designed.** The convention is clean:
- `InternalServerError` -> 500 with generic message
- `ExternalServiceError` -> 502 with generic message
- `ValueError` -> 422 with `str(exc)` forwarded to client (business logic)

The type hierarchy is correct: `InternalServerError(Exception)`, `ExternalServiceError(RuntimeError)`, OAuth errors extend `ExternalServiceError`. Services correctly avoid importing `HTTPException`.

### 3. Do internal server errors leak details to clients?

**No significant leaks.** All `InternalServerError`, `RuntimeError`, `OSError`, `TypeError`, `KeyError`, `AttributeError`, `IndexError`, `OperationalError`, and `CalledProcessError` handlers return generic messages. Internal paths, SQL queries, and stack traces are logged server-side only.

**One minor gap:** In debug mode (`settings.debug=True`), Starlette's default handler for uncaught exceptions returns an HTML traceback. This only affects exception types with no registered handler (see the `httpx.HTTPError` gap above). This is acceptable since debug mode is blocked in production by `validate_runtime_security()`.

### 4. Do business logic errors correctly propagate understandable messages to clients?

**Mostly yes.** The `ValueError` global handler at `main.py:561-568` forwards `str(exc)` to clients, and most ValueError messages are clear user-facing text.

**One minor info leak:** `crosspost_service.py:56-57` raises `ValueError(f"Unknown platform: {data.platform!r}. Available: {available}")` — this exposes the full list of available platforms. Not sensitive, but unnecessarily verbose.

### 5. Can an error crash the server?

**No.** Between the registered global handlers and Starlette's built-in `ServerErrorMiddleware`, all exceptions during request handling are caught. The lifespan function correctly re-raises startup failures (which is correct — a failed startup should prevent serving). The shutdown sequence in the `finally` block wraps each cleanup step in its own try/except.

**One theoretical concern:** `crosspost_service.py:245` catches bare `except Exception:` which is too broad — it could mask `SystemExit` or `KeyboardInterrupt` in edge cases. In practice, `asyncio.CancelledError` (Python 3.9+) inherits from `BaseException`, not `Exception`, so it's not affected.

## Issues to Fix

| # | Category | Location | Issue | Severity |
|---|----------|----------|-------|----------|
| 1 | Missing global handler | `main.py` | No `httpx.HTTPError` handler — OAuth transport errors bypass structured logging, return 500 instead of 502 | High |
| 2 | Missing global handler | `main.py` | No catch-all `Exception` handler — novel exception types bypass application logging | High |
| 3 | Unprotected file I/O | `content_manager.py:write_post()` | `mkdir()` and `write_text()` not wrapped in try/except | Medium |
| 4 | Unprotected file I/O | `content_manager.py:delete_post()` | `unlink()` and `rmtree()` not wrapped in try/except | Medium |
| 5 | Unprotected file I/O | `api/posts.py:upload_post` | Asset writes before try/except leave orphaned files on failure | Medium |
| 6 | Info leak in ValueError | `crosspost_service.py:56-57` | Exposes full platform list in error message | Low |
| 7 | Overly broad catch | `crosspost_service.py:245` | Bare `except Exception:` should be specific types | Low |
