# Account/Profile PR Review (2026-03-10)

Review of `e2e-testing` branch against `main` covering the PATCH /api/auth/me endpoint, AccountSection component, and related changes.

## Critical Issues

### 1. Race condition: filesystem writes outside `content_write_lock`
- **File:** `backend/api/auth.py:482-488`
- `_update_author_in_posts()` writes to markdown files before acquiring the lock. Every other content-mutating endpoint acquires the lock for the entire mutation. Concurrent post edits during a username change could cause silent data loss.

### 2. No error handling around filesystem I/O in `_update_author_in_posts`
- **File:** `backend/api/auth.py:446-456`
- `write_post()` called in a loop with no `try/except`. Every other `write_post()` call site wraps it in `try/except OSError`. A failure mid-loop leaves posts partially updated with no logging.

### 3. No atomicity between filesystem mutation and database commit
- **File:** `backend/api/auth.py:469-499`
- Code modifies `user.username`, writes files, rebuilds cache, then commits DB. If commit fails (e.g., `IntegrityError` from TOCTOU race), files are modified but DB has old username. No rollback. `IntegrityError` not caught (unlike `register` endpoint).

## Important Issues

### 4. `content_manager` accessed via `request.app.state` instead of dependency injection
- **File:** `backend/api/auth.py:483,487`
- Inconsistent with codebase pattern of using `Depends(get_content_manager)` and `Depends(get_content_write_lock)`.

### 5. `_update_author_in_posts` is synchronous, blocking the event loop
- **File:** `backend/api/auth.py:446-456`
- CLAUDE.md requires `async def` for all I/O. Sync function performs many file reads/writes, blocking concurrent requests.

### 6. No logging for destructive batch filesystem operation
- **File:** `backend/api/auth.py:446-456`
- Username change propagating to all authored content is a security-relevant event with zero log entries.

### 7. `RegisterRequest.display_name` missing `max_length`
- **File:** `backend/schemas/auth.py:30`
- `ProfileUpdate` enforces `max_length=100` but `RegisterRequest` has no limit.

### 8. Duplicated username validator logic
- **File:** `backend/schemas/auth.py`
- `RegisterRequest.validate_username_format` and `ProfileUpdate.validate_username_format` are copy-pasted.

### 9. Duplicate `auth` router row in architecture docs
- **File:** `docs/arch/backend.md:67,74`
- `auth` router appears twice in the API Routes table.

## Test Coverage Gaps

### 10. No frontend tests for the profile update flow
- `AccountSection.tsx` (336 lines) has zero test coverage for profile saving, error paths, or client-side validation. `mockUpdateProfile` and `mockSetUser` are set up but never exercised.

### 11. No backend test for updating both username and display_name simultaneously
- Tests cover each field separately but never in one request.

### 12. No backend test for CSRF token requirement on PATCH /api/auth/me
- Security-sensitive state-changing endpoint with no explicit CSRF bypass test.

### 13. No test for whitespace-only display name normalization
- `"   "` to `None` path via `strip() or None` is untested.
