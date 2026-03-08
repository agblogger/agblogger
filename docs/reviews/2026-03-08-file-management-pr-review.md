# PR Review: feat/file-management

**Date:** 2026-03-08
**Branch:** `feat/file-management` vs `origin/main`
**Scope:** 64 files changed, ~7,500 lines added across backend, frontend, CLI, tests, and docs

## Critical Issues (2)

### 1. Silent partial failure in `update_user_display_name`

**File:** `backend/services/admin_service.py:237-248`

File write failures are logged but swallowed; the DB transaction commits as if all succeeded. Since files are the source of truth, the next `rebuild_cache()` on restart silently reverts un-updated posts to the old author name. The user sees "Settings saved" but has permanent data inconsistency.

**Recommendation:** Track failed file paths and either (a) return them as warnings in the response, or (b) do not commit the DB transaction if any file write fails.

### 2. `list_assets` returns wrong results for flat-file posts

**File:** `backend/api/posts.py:461`

For a flat post like `posts/hello.md`, `post_file.parent` is the entire `posts/` directory. The endpoint would iterate over ALL files in `posts/`, listing other posts and directories as "assets." This could expose other users' post filenames.

**Recommendation:** Return an empty asset list for flat-file posts, or raise a 400 error explaining that asset management requires a directory-style post.

## Important Issues (6)

### 3. `body.replaceAll(oldName, newName)` is naive string replacement

**File:** `frontend/src/components/editor/FileStrip.tsx:100`

Renaming `a.png` would corrupt `banana.png` into `bannewname.png`. Needs targeted replacement within markdown link/image syntax only (e.g., replace only within `![...](oldName)` and `[...](oldName)` patterns).

### 4. Frontend errors show raw HTTP status codes

**Files:** `frontend/src/components/editor/FileStrip.tsx:38,85,104,123`

Users see "Failed to rename: 409" instead of the backend's "A file with that name already exists." Should use `parseErrorDetail` to extract the backend's detail message.

### 5. `Promise.all` for site settings + display name risks partial updates

**File:** `frontend/src/components/admin/SiteSettingsSection.tsx:49-52`

If one request succeeds and the other fails, `Promise.all` rejects with a generic error. The user doesn't know which operation failed. Use sequential calls or `Promise.allSettled` with per-operation feedback.

### 6. Unprotected `new_path.stat()` after rename

**File:** `backend/api/posts.py:578`

If stat fails after a successful rename, the user sees a 500 but retrying fails because the old name is gone. Retrieve the file size before the rename, or wrap the stat in try/except.

### 7. Clipboard copy error silently discarded

**File:** `frontend/src/components/editor/FileCard.tsx:67`

`void navigator.clipboard.writeText()` discards the Promise rejection. User gets no feedback if copy fails. At minimum catch the error to prevent unhandled promise rejections.

### 8. `load_config` has no JSON parse error handling

**File:** `cli/sync_client.py:110-116`

Corrupted config file produces raw Python traceback instead of a user-friendly error. Wrap in try/except for `json.JSONDecodeError`, `OSError`, and `UnicodeDecodeError`.

## Suggestions (12)

### 9. Suppressed `chmod` on `.env.production`

**File:** `cli/deploy_production.py:283`

Log a warning when permission restriction fails on secrets files instead of silently suppressing with `contextlib.suppress`.

### 10. `PostListParams` uses bare strings

**File:** `frontend/src/api/posts.ts:11-22`

Use union literal types for `sort`, `order`, `labelMode` (e.g., `sort?: 'created_at' | 'modified_at' | 'title' | 'author'`) for free compile-time safety.

### 11. No label validation in `PostSave`

**File:** `backend/schemas/post.py:56`

Labels accept arbitrary strings; should enforce the `#id` pattern or at minimum `min_length=1`.

### 12. `DisplayNameUpdate` doesn't strip whitespace

**File:** `backend/schemas/admin.py:81`

Inconsistent with `PostSave.strip_title` which strips at the schema level. The handler does `.strip() or None` but the schema should own this normalization.

### 13. `AssetInfo` lacks field constraints

**File:** `backend/schemas/post.py:87-92`

Add `Field(ge=0)` on `size` and `Field(min_length=1)` on `name` for self-documenting contracts.

### 14. Preview catch block discards error context

**File:** `frontend/src/pages/EditorPage.tsx:141-144`

Bare `catch` with no variable binding. At least log to console for debugging.

### 15. Add global `TokenExpiredError` handler

**File:** `backend/main.py`

Safety net if the exception is raised outside the `get_current_user` dependency layer in future code.

### 16. `FileCard.disabled` optionality inconsistency

`FileCardProps` declares `disabled?: boolean` (optional) while `FileStripProps` declares `disabled: boolean` (required). Make both required for consistency.

### 17. Design docs have stale details

- `docs/plans/2026-03-08-file-management-design.md:48` — Rename endpoint response says `{ name }` but actually returns `{ name, size, is_image }`.
- `docs/plans/2026-03-08-file-management-design.md:40-41` — "View post" described as three-option dialog but implementation uses browser `window.confirm`.
- `docs/plans/2026-03-08-file-management-design.md:48` — Says endpoints "respect draft access control" but they use `require_admin`, not draft ownership.
- `docs/plans/2026-03-08-timezone-dropdown-design.md:20` — Says "No backend schema changes" but a timezone field_validator was added.

### 18. `resolvedPath` is unused indirection

**File:** `frontend/src/components/editor/FileStrip.tsx:57`

`const resolvedPath = filePath` is a no-op alias. Use `filePath` directly.

### 19. Backend route table missing display-name endpoint

**File:** `docs/arch/backend.md:72`

The admin route row doesn't mention the new `display-name` endpoint.

### 20. `requires-python` should be bumped to `>=3.14`

**File:** `pyproject.toml:5`

The codebase uses PEP 758 syntax (`except A, B:`) and all tooling targets Python 3.14. Update `requires-python` to match.

## Test Coverage Gaps

- **No test for partial file write failure** in `update_user_display_name` (services/admin_service.py).
- **FileStrip rename/upload error handling paths untested** (FileStrip.test.tsx) — no coverage for rename flow, upload flow, or error state rendering.
- **PostPage 401 error path untested** (PostPage.test.tsx) — publish failure test uses generic `Error`, not `HTTPError`.
- **`list_assets` does not test dotfile exclusion** — no test creates a `.DS_Store` to verify filtering.
- **`AssetRenameRequest` Pydantic boundary untested** — empty/overlong `new_name` not tested at the schema level.
- **`confirm_sync` `EOFError` path untested** (test_sync_client_ux.py) — only `KeyboardInterrupt` is tested.

## Strengths

- **Asset management endpoints** are well-designed with proper locking, input validation (`_validate_asset_filename`), path traversal prevention, and auth guards.
- **`PostSave` unification** cleanly eliminates duplication between `PostCreate`/`PostUpdate`.
- **TimezoneCombobox** has thorough ARIA support, keyboard navigation, and excellent test coverage.
- **Auth hardening tests** are production-grade (CSRF, PAT lifecycle, rate limiting, credential rotation).
- **Sync client UX tests** comprehensively cover config permissions, env var auth, confirmation flow.
- **Three-state `FilterPanelState`** properly handles CSS animation coordination.
- **Backend timezone validation** via Pydantic field validator is clean and well-placed.
- **Deploy production tests** comprehensively cover all configurations, Trivy scan, backup, dry run masking.
- **Good "why" comments** in `posts.py` (rename/symlink asymmetry, two-phase rendering, pre-lock I/O).
