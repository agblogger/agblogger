# Crash-Hunting Review — 2026-03-10

## Overview

Systematic review of the backend for code that could crash the server, cause data corruption, or produce incorrect behavior. The backend has strong global exception handlers in `main.py` covering most exception types, making a true server crash unlikely, but several gaps remain.

## HIGH Severity

### 1. Missing global handlers for `AttributeError`, `IndexError`
- **Location**: `main.py`
- **Issue**: These exception types bypass all custom handlers, producing raw Starlette 500 responses instead of structured JSON.
- **Impact**: Unstructured error responses; potential internal detail leakage.

### 2. `RecursionError` / `NotImplementedError` re-raised from RuntimeError handler
- **Location**: `main.py:460-462`
- **Issue**: The `RuntimeError` handler explicitly re-raises `RecursionError` and `NotImplementedError`, which have no other registered handler.
- **Impact**: Raw 500 response without structured JSON.

### 3. `update_profile` partial failure leaves filesystem/DB inconsistent
- **Location**: `api/auth.py:504-533`
- **Issue**: Post files are rewritten with the new author on disk, but if `rebuild_cache` or the final commit fails, the DB rolls back while the filesystem retains the new author name.
- **Impact**: Filesystem and database permanently out of sync on author names.

### 4. `rebuild_cache` empties cache tables during rebuild
- **Location**: `services/cache_service.py:33-45`
- **Issue**: Cache tables are deleted and repopulated non-atomically. Concurrent readers see empty post lists and search results during sync or profile updates.
- **Impact**: Visible data loss for active readers during cache rebuild window.

### 5. Directory rename + commit failure can orphan posts
- **Location**: `api/posts.py:857-902`
- **Issue**: If `shutil.move` succeeds but DB commit fails, the rollback of the move can also fail, leaving the post inaccessible from both old and new paths.
- **Impact**: Post becomes permanently inaccessible.

### 6. Unbounded `while True` loop in slug generation
- **Location**: `services/slug_service.py:72-77`, `api/posts.py:805-812`
- **Issue**: No upper limit on collision counter. Pathological conditions cause CPU exhaustion / denial of service.
- **Impact**: Request hangs indefinitely; CPU exhaustion.

### 7. Asset upload can overwrite `index.md`
- **Location**: `api/posts.py:436,451`
- **Issue**: `_validate_asset_filename` is called for delete/rename but NOT for upload. Uploading an asset named `index.md` corrupts post content.
- **Impact**: Post content corruption.

## MEDIUM Severity

### 8. `PageOrderItem.file` has no path validation
- **Location**: `schemas/admin.py:65-70`
- **Issue**: Admin can set arbitrary paths into `index.toml`. On read, files within content_dir (including OAuth keypair) could be exposed as page content.
- **Impact**: Information disclosure of sensitive files within content directory.

### 9. `shutil.rmtree` on symlinked post directory
- **Location**: `filesystem/content_manager.py:195`
- **Issue**: When deleting a post whose directory is a symlink (created during rename), `shutil.rmtree` follows the symlink and deletes the target directory contents instead of just the symlink.
- **Impact**: Unintended deletion of the renamed post's actual data.

### 10. `sync_status` reads filesystem without `content_write_lock`
- **Location**: `api/sync.py:119-168`
- **Issue**: The sync plan can become stale due to concurrent mutations between scan and client action.
- **Impact**: Stale sync plan leading to incorrect overwrites or lost edits.

### 11. `_upsert_social_account` delete-then-retry race
- **Location**: `api/crosspost.py:97-132`
- **Issue**: If retry create fails after deleting the existing account, the user's social account is lost.
- **Impact**: User loses social account connection with no recovery.

### 12. `scan_content_files` blocks the event loop
- **Location**: `services/sync_service.py:111-133`
- **Issue**: Synchronous `os.walk` + file hashing without `asyncio.to_thread`.
- **Impact**: Event loop blocked during content scan; degraded responsiveness under load.

### 13. `Content-Disposition` header not RFC 6266 safe
- **Location**: `api/content.py:152`
- **Issue**: Filenames with `"` characters break the Content-Disposition header format.
- **Impact**: Malformed HTTP headers; potential header injection.

### 14. Non-iterable `parents` in labels.toml causes `TypeError`
- **Location**: `filesystem/toml_manager.py:142`
- **Issue**: `parents = 42` in TOML causes `TypeError` when iterating. Caught by global handler but produces a generic error.
- **Impact**: Label parsing fails silently for affected label.

### 15. Some httpx exceptions unhandled in pandoc renderer
- **Location**: `pandoc/renderer.py:317-328`
- **Issue**: `httpx.WriteError`, `httpx.PoolTimeout` not caught, propagate as unhandled exceptions.
- **Impact**: Unstructured 500 response instead of proper 502.

### 16. Pandoc non-200 with valid JSON silently produces empty HTML
- **Location**: `pandoc/renderer.py:330-337`
- **Issue**: Non-200 response from pandoc with valid JSON that lacks an "error" key produces empty rendered output.
- **Impact**: Silent incorrect behavior — valid markdown renders as empty HTML.

### 17. Regex backtracking risk in `get_plain_excerpt`
- **Location**: `filesystem/content_manager.py:241-244`
- **Issue**: The regex `[*_]{1,3}([^*_]+)[*_]{1,3}` could exhibit quadratic behavior on adversarial input.
- **Impact**: CPU spike for crafted content.

### 18. `facebook_callback` accesses `result["pages"]` on external data
- **Location**: `api/crosspost.py:902`
- **Issue**: Direct dict key access on external service response instead of `.get()`. Should return 502 on missing key, not 500 via global KeyError handler.
- **Impact**: Returns 500 instead of 502 for Facebook API response changes.

## LOW Severity (not addressed)

- Dict key access on state store data in OAuth callbacks (caught by global KeyError handler)
- `pendulum.parse(strict=False)` accepts loose date strings
- `PageOrderUpdate` allows config corruption (admin only, validated on read)
- Pandoc renderer globals race during startup/shutdown (brief window)
- Read-without-lock patterns (graceful 404 on failure)
