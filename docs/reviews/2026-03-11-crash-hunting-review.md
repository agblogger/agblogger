# Crash Hunting Review — 2026-03-11

Systematic review of the backend for server crash risks, unhandled exceptions, race conditions, and external service failure handling.

## HIGH Severity

### 1. `scan_posts` missing `KeyError`/`TypeError` in exception handler

**File:** `backend/filesystem/content_manager.py:96`

`scan_posts` catches `(UnicodeDecodeError, ValueError, yaml.YAMLError, OSError)` but not `KeyError` or `TypeError`. A single malformed post with unexpected YAML types can abort the entire cache rebuild. During startup, this crashes the server since it runs outside request handling.

### 2. `_load_existing()` `OSError` not caught in atproto OAuth keypair loading

**File:** `backend/crosspost/atproto_oauth.py:110, 140-142`

TOCTOU race between `path.exists()` and `path.read_text()` — the file can be deleted between the two calls. The `OSError` is not in the catch tuple, so it propagates and crashes startup. The lock file is also orphaned.

### 3. Rare httpx exceptions from Pandoc not wrapped in `RenderError`

**File:** `backend/pandoc/renderer.py:317-328`, `backend/services/cache_service.py:102`

`_render_markdown` only catches `httpx.NetworkError` and `httpx.TimeoutException`. Other httpx exceptions (`ProtocolError`, `DecodingError`) propagate unwrapped. During cache rebuild at startup, these bypass `except RuntimeError` and crash the server.

## MEDIUM Severity — Data Consistency / Orphaned State

### 4. `upload_post` leaves orphaned asset files on disk

**File:** `backend/api/posts.py:333-380`

If DB flush or label replacement fails after asset files are written to disk, the assets are not cleaned up. Only `write_post` `OSError` triggers cleanup.

### 5. `delete_post_endpoint` deletes file before commit

**File:** `backend/api/posts.py:960-979`

The post file is deleted from disk before `session.commit()`. If commit fails, the file is gone but the DB still references it, creating DB-filesystem inconsistency.

### 6. `session.rollback()` after `session.commit()` is a no-op in `update_profile`

**File:** `backend/api/auth.py:548`

When cache rebuild fails after a profile update, `session.rollback()` is called but the user changes were already committed. The username change is not actually reverted.

### 7. `delete_page` deletes file before updating config

**File:** `backend/services/admin_service.py:180-185`

If `write_site_config` fails after file deletion, the file is gone but the config still references it.

### 8. `update_page` non-atomic config+file update

**File:** `backend/services/admin_service.py:121-159`

Writes config (title) then file (content). On file write failure, config rollback can itself fail, leaving inconsistent state.

### 9. `reload_config` non-atomic assignment

**File:** `backend/services/admin_service.py:42-43`, `backend/filesystem/content_manager.py:59-62`

Assigns `_site_config` then `_labels` sequentially. If `parse_labels_config` raises, site config is updated but labels are stale.

## MEDIUM Severity — Error Handling Gaps

### 10. Cross-post loop aborts on unexpected exception types

**File:** `backend/services/crosspost_service.py:235-253`

Per-platform try/except doesn't catch `KeyError`, `TypeError` from poster plugins. An unexpected exception aborts the loop, losing the commit of all prior successful cross-posts.

### 11. `fm.dumps` in `merge_post_file` can raise `yaml.YAMLError`

**File:** `backend/services/sync_service.py:439`

After merging front matter and body, serialization can raise `yaml.YAMLError` on exotic metadata types. Not caught by the sync endpoint's `except (CalledProcessError, OSError)`. Aborts the sync commit.

### 12. `merge_file_content` can raise `subprocess.TimeoutExpired`

**File:** `backend/services/sync_service.py:431`

The sync endpoint catches `CalledProcessError` and `OSError` but not `TimeoutExpired`, so a git merge timeout aborts the sync commit.

### 13. `update_label` checks cycles against stale edges

**File:** `backend/services/label_service.py:186-198`

Cycle detection runs against stale edges (old parent edges not yet deleted), causing false positive cycle detection for valid updates.

### 14. `session.flush()` in create/upload paths lacks rollback

**File:** `backend/api/posts.py:362, 698`

No rollback or asset cleanup on DB exceptions during post creation.

## MEDIUM Severity — Process / Runtime

### 15. Blocking `time.sleep()` in async context

**File:** `backend/crosspost/atproto_oauth.py:152`

`load_or_create_keypair()` uses `time.sleep(0.01)` in a loop (up to 5s). Currently startup-only but would freeze the event loop if called at request time.

### 16. `PandocServer.start()` is public but not lock-protected

**File:** `backend/pandoc/server.py:160-176`

If `start()` were called from multiple coroutines, it could spawn multiple pandoc processes. Currently only called from locked `ensure_running()` and single-caller startup.

### 17. Pandoc stderr always empty due to `DEVNULL`

**File:** `backend/pandoc/server.py:124-127`

`_spawn()` sets `stderr=asyncio.subprocess.DEVNULL` but `_wait_for_ready` tries to read stderr for error messages. Diagnostic information is always empty.

### 18. `mkdir()` without `exist_ok=True` in `ensure_content_dir`

**File:** `backend/main.py:89, 93`

TOCTOU race between `exists()` check and `mkdir()` call can crash startup with `FileExistsError`.

### 19. `os.unlink` in `except BaseException` can mask original exception

**File:** `backend/crosspost/atproto_oauth.py:84-86`

If cleanup `os.unlink` fails, the original exception is replaced by the new `OSError`.

## MEDIUM Severity — Information / Behavior

### 20. `ValueError` handler exposes `str(exc)` to clients

**File:** `backend/main.py:573-580`

Library-originated `ValueError` exceptions (from `int()`, `datetime.fromisoformat()`, etc.) may leak internal implementation details to clients.

### 21. Rate-limit stale keys never cleaned

**File:** `backend/services/rate_limit_service.py:18-57`

Stale keys with expired timestamps are never cleaned unless re-accessed. Distributed brute-force attacks accumulate unbounded stale entries (memory leak).

### 22. Multiple accounts on same platform silently collapse

**File:** `backend/services/crosspost_service.py:171`

Last wins in dict comprehension when multiple accounts exist on the same platform.

### 23. `DuplicateAccountError` swallowed by `ValueError` catch

**File:** `backend/api/crosspost.py:148-160`

`DuplicateAccountError` is a subclass of `ValueError`, so it returns 400 instead of the intended 409.
