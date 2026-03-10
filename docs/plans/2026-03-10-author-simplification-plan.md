# Author Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the dual `author`/`author_username` front matter pattern with a single `author` field containing the username, resolving display names at query time via a JOIN against the users table.

**Architecture:** Posts store only `author` (username) in YAML front matter. The `PostCache` table stores this username. API responses resolve display names by LEFT JOINing `PostCache.author` to `users.username`, falling back to the raw username for deleted users. `default_author`, `post_owner_service`, `update_user_display_name()`, and `sync_default_author_from_admin()` are all deleted.

**Tech Stack:** Python/FastAPI, SQLAlchemy, SQLite, pytest, React/TypeScript

**Design doc:** `docs/plans/2026-03-10-author-simplification-design.md`

---

### Task 1: Update PostData and frontmatter parser

Remove `author_username` from the front matter parser and serializer. Keep `author` as the sole author field.

**Files:**
- Modify: `backend/filesystem/frontmatter.py` (lines 14–24: RECOGNIZED_FIELDS, lines 36–37: PostData, lines 161–176: parse_post author logic, lines 200–203: serialize_post)
- Test: `tests/test_filesystem/test_frontmatter.py`

**Step 1: Update existing tests**

Find and update any tests that use `author_username` in PostData or front matter assertions. Remove `author_username` from expected outputs and inputs. Update tests that rely on `default_author` fallback in `parse_post()` — the `default_author` parameter is being removed, so tests should pass `None` or omit it.

**Step 2: Write failing tests**

Add a test that verifies:
- `author_username` is NOT in `RECOGNIZED_FIELDS`
- `PostData` has no `author_username` attribute
- `parse_post()` ignores `author_username` in YAML (treats it as an unrecognized field)
- `serialize_post()` does not write `author_username`
- `parse_post()` no longer accepts a `default_author` parameter

**Step 3: Run tests to verify they fail**

Run: `just test-backend`

**Step 4: Implement changes**

In `backend/filesystem/frontmatter.py`:
- Remove `"author_username"` from `RECOGNIZED_FIELDS` (line 20)
- Remove `author_username: str | None = None` from `PostData` (line 37)
- In `parse_post()`: remove `default_author` parameter, remove all `author_username` logic (lines 169–176), simplify `author` to just read from front matter with no fallback
- In `serialize_post()`: remove `author_username` serialization (lines 200–203 area)

**Step 5: Run tests to verify they pass**

Run: `just test-backend`

**Step 6: Commit**

```
feat: remove author_username from front matter parser
```

---

### Task 2: Update PostCache model

Remove `author_username` column and its index from PostCache. Since PostCache is a regenerable cache table (dropped and rebuilt on startup via `rebuild_cache()`), no Alembic migration is needed.

**Files:**
- Modify: `backend/models/post.py` (lines 26, 41)

**Step 1: Remove author_username from PostCache**

In `backend/models/post.py`:
- Delete line 26: `author_username: Mapped[str | None] = mapped_column(String, nullable=True)`
- Delete line 41: `Index("idx_posts_author_username", "author_username"),`

**Step 2: Run tests to see what breaks**

Run: `just test-backend`

Fix any test that references `PostCache.author_username`.

**Step 3: Commit**

```
refactor: remove author_username column from PostCache
```

---

### Task 3: Delete post_owner_service and its tests

**Files:**
- Delete: `backend/services/post_owner_service.py`
- Delete: `tests/test_services/test_post_owner_service.py`

**Step 1: Delete both files**

**Step 2: Remove imports**

Search for all imports of `build_owner_lookup`, `resolve_owner_username`, or `post_owner_service` and remove them. Key location:
- `backend/services/cache_service.py` line 18

**Step 3: Run tests to confirm no import errors remain**

Run: `just test-backend`

(Tests will still fail due to cache_service using the deleted functions — that's expected, fixed in Task 5.)

**Step 4: Commit**

```
refactor: delete post_owner_service
```

---

### Task 4: Remove default_author from SiteConfig and index.toml

**Files:**
- Modify: `backend/filesystem/toml_manager.py` (lines 25, 34, 110, 185)
- Modify: `backend/schemas/admin.py` (lines 15, 33)
- Modify: `content/index.toml` (line 9)
- Test: `tests/test_filesystem/test_toml_manager.py`
- Test: update any admin schema tests

**Step 1: Update tests**

Remove `default_author` from all test assertions for SiteConfig parsing, writing, and admin schema validation.

**Step 2: Implement changes**

In `backend/filesystem/toml_manager.py`:
- Remove `default_author: str = ""` from `SiteConfig` (line 25)
- Remove `default_author` from `to_response()` method (line 34)
- Remove `default_author` from `parse_site_config()` (line 110)
- Remove `default_author` from `write_site_config()` (line 185)

In `backend/schemas/admin.py`:
- Remove `default_author` from `SiteSettingsUpdate` (line 15)
- Remove `default_author` from `SiteSettingsResponse` (line 33)

In `content/index.toml`:
- Remove the `default_author = "Admin"` line

**Step 3: Run tests**

Run: `just test-backend`

**Step 4: Commit**

```
refactor: remove default_author from site config and admin schemas
```

---

### Task 5: Simplify rebuild_cache in cache_service

Remove the owner resolution logic from `rebuild_cache()`. The function should store `post_data.author` directly into `PostCache.author` without any resolution.

**Files:**
- Modify: `backend/services/cache_service.py` (lines 18, 90, 93–107, 129)
- Modify: `backend/filesystem/content_manager.py` (line 95 — `default_author` parameter)
- Test: `tests/test_services/test_cache_service.py`

**Step 1: Update tests**

Update cache rebuild tests to not expect owner resolution. Posts with `author: someuser` should store `someuser` in cache without any lookup.

**Step 2: Implement changes**

In `backend/services/cache_service.py`:
- Remove import of `build_owner_lookup`, `resolve_owner_username` (line 18)
- Remove `usernames, unique_display_names = await build_owner_lookup(session)` (line 90)
- Remove the `resolve_owner_username()` call and the if-block that rewrites posts on disk (lines 93–107)
- Change cache insertion to use `post_data.author` directly instead of `owner_username` (line 129)

In `backend/filesystem/content_manager.py`:
- Remove `default_author` parameter from `scan_posts()` and `read_post()` calls (these call `parse_post()` which no longer has that parameter)

**Step 3: Run tests**

Run: `just test-backend`

**Step 4: Commit**

```
refactor: simplify rebuild_cache to store author directly
```

---

### Task 6: Delete update_user_display_name and sync_default_author_from_admin

**Files:**
- Modify: `backend/services/admin_service.py` (lines 225–336)
- Modify: `backend/main.py` (lines 217, 223–227)
- Delete: `tests/test_api/test_admin_display_name.py`
- Modify: `tests/test_services/test_admin_service.py`

**Step 1: Delete the display name test file**

Delete `tests/test_api/test_admin_display_name.py` entirely.

**Step 2: Update admin_service tests**

Remove tests for `update_user_display_name()` and `sync_default_author_from_admin()` from `tests/test_services/test_admin_service.py`. Also remove any tests that assert `default_author` behavior.

**Step 3: Remove from admin_service.py**

Delete `update_user_display_name()` (lines 225–315) and `sync_default_author_from_admin()` (lines 318–336) from `backend/services/admin_service.py`.

**Step 4: Remove startup call in main.py**

In `backend/main.py`:
- Remove import of `sync_default_author_from_admin` (line 217)
- Remove the call at lines 223–227

**Step 5: Run tests**

Run: `just test-backend`

**Step 6: Commit**

```
refactor: delete display name sync and default author startup logic
```

---

### Task 7: Remove display-name API endpoint

**Files:**
- Modify: `backend/api/admin.py` (lines 221–245)
- Modify: `backend/schemas/admin.py` (remove `DisplayNameUpdate`, `DisplayNameResponse` if they exist)
- Modify: Frontend components that call this endpoint (if any)

**Step 1: Check frontend usage**

Search frontend for `/api/admin/display-name` or `displayName` API calls. Remove any frontend code that calls this endpoint.

**Step 2: Remove the endpoint**

In `backend/api/admin.py`:
- Delete the `PUT /display-name` endpoint (lines 221–245)
- Remove any related imports (`update_user_display_name`, display name schemas)

In `backend/schemas/admin.py`:
- Remove `DisplayNameUpdate` and `DisplayNameResponse` schemas if they exist

**Step 3: Run tests**

Run: `just check`

**Step 4: Commit**

```
refactor: remove display-name API endpoint
```

---

### Task 8: Add JOIN for display name resolution in post queries

This is the core new behavior. Post queries resolve display names at query time by joining PostCache to users.

**Files:**
- Modify: `backend/services/post_service.py` (lines 54–199)
- Test: `tests/test_services/test_post_service.py` or `tests/test_api/test_posts.py`

**Step 1: Write failing tests**

Write tests that verify:
- A post by `author: admin` where the admin user has `display_name: "John Smith"` returns `author: "John Smith"` in the API response
- A post by `author: deleteduser` where no user exists returns `author: "deleteduser"` (fallback)
- A post by `author: nodisplay` where the user has `display_name: None` returns `author: "nodisplay"` (fallback)
- Filtering by `author=John` matches the display name, not the username
- Sorting by author uses the resolved display name

**Step 2: Run tests to verify they fail**

Run: `just test-backend`

**Step 3: Implement the JOIN**

In `backend/services/post_service.py`, in `list_posts()`:
- Import `User` model
- Import `func` and `case` from SQLAlchemy if not already imported
- Add a LEFT JOIN from `PostCache` to `User` on `PostCache.author == User.username`
- Use `func.coalesce(User.display_name, PostCache.author)` as the resolved author expression
- Use this expression for filtering (the `author` query param should ILIKE against the resolved name)
- Use this expression for sorting when `sort_by == "author"`
- Include the resolved author in the query result and map it into PostSummary/PostDetail responses

Similarly update `get_post()` to resolve the display name.

**Step 4: Run tests to verify they pass**

Run: `just test-backend`

**Step 5: Commit**

```
feat: resolve author display names at query time via JOIN
```

---

### Task 9: Update draft visibility and access checks

Change draft ownership checks from `author_username` to `author`.

**Files:**
- Modify: `backend/services/post_service.py` (lines 74–84)
- Modify: `backend/api/content.py` (line 113)
- Test: existing draft access tests

**Step 1: Update post_service.py draft filter**

In `list_posts()`, change:
- `PostCache.author_username == draft_owner_username` → `PostCache.author == draft_owner_username`

**Step 2: Update content.py draft access check**

In `backend/api/content.py` `_check_draft_access()`:
- Change `post.author_username != user.username` → `post.author != user.username`

**Step 3: Run tests**

Run: `just test-backend`

**Step 4: Commit**

```
refactor: use PostCache.author for draft ownership checks
```

---

### Task 10: Update post creation to set author from username

Currently, post creation sets `author` to the user's display name. Change it to set `author` to the username.

**Files:**
- Modify: `backend/api/posts.py` (lines 299, 648)
- Test: post creation tests

**Step 1: Write/update tests**

Verify that creating a post sets `author` to `user.username`, not `user.display_name`.

**Step 2: Implement changes**

In `backend/api/posts.py`:
- Line 299 (upload): change `post_data.author = user.display_name or user.username` → `post_data.author = user.username`
- Line 648 (create): change `author = user.display_name or user.username` → `author = user.username`

**Step 3: Run tests**

Run: `just test-backend`

**Step 4: Commit**

```
refactor: set post author to username on creation
```

---

### Task 11: Update sync merge_frontmatter

Remove `author_username` from the sync merge conflict detection field list.

**Files:**
- Modify: `backend/services/sync_service.py` (lines 308, 537–548)
- Test: `tests/test_services/test_sync_merge_integration.py`

**Step 1: Update tests**

Remove any test assertions about `author_username` in merge results.

**Step 2: Implement changes**

In `backend/services/sync_service.py`:
- Line 308: remove `"author_username"` from the conflict detection tuple
- Lines 537–548: remove any logic that sets `author_username` from `default_author_username`

**Step 3: Run tests**

Run: `just test-backend`

**Step 4: Commit**

```
refactor: remove author_username from sync merge logic
```

---

### Task 12: Update admin site settings endpoint

The `update_site_settings()` function in admin_service.py currently preserves `default_author`. Remove that logic.

**Files:**
- Modify: `backend/services/admin_service.py` (around line 50)
- Modify: `backend/api/admin.py` — site settings GET/POST endpoints
- Test: admin settings tests

**Step 1: Update tests**

Remove assertions about `default_author` in site settings responses and requests.

**Step 2: Implement changes**

In `backend/services/admin_service.py`:
- Remove the line that preserves `default_author` from existing config (line 50 area)

In `backend/api/admin.py`:
- Update GET `/api/admin/site` to not return `default_author`
- Update POST `/api/admin/site` to not accept `default_author`

**Step 3: Run tests**

Run: `just test-backend`

**Step 4: Commit**

```
refactor: remove default_author from admin site settings
```

---

### Task 13: Update frontend admin settings UI

Remove `default_author` from the site settings form.

**Files:**
- Modify: `frontend/src/components/admin/SiteSettingsSection.tsx`
- Modify: `frontend/src/api/admin.ts`
- Test: `frontend/src/pages/__tests__/AdminPage.test.tsx`

**Step 1: Update tests**

Remove `default_author` from test fixtures and assertions in admin page tests.

**Step 2: Implement changes**

In `frontend/src/api/admin.ts`:
- Remove `default_author` from the site settings request/response types

In `frontend/src/components/admin/SiteSettingsSection.tsx`:
- Remove the `default_author` form field

**Step 3: Run tests**

Run: `just test-frontend`

**Step 4: Commit**

```
refactor: remove default_author from frontend admin settings
```

---

### Task 14: Update example content and architecture docs

**Files:**
- Modify: `content/index.toml`
- Modify: `docs/arch/index.md` (lines 79, 87, 121)
- Modify: `docs/arch/backend.md` (lines 33, 82)
- Modify: `README.md` (content authoring section)

**Step 1: Update content/index.toml**

Remove the `default_author = "Admin"` line.

**Step 2: Update docs/arch/index.md**

- Line 79: Remove `author_username: admin` from the example front matter
- Line 87: Replace the ownership description. New text: "`author` stores the username of the post creator. Display names are resolved at query time via a JOIN against the users table."
- Line 121: Remove mention of `default_author`

**Step 3: Update docs/arch/backend.md**

- Line 33: Remove the sentence about synchronizing `default_author`
- Line 82: Replace `stable owner username (author_username)` with description of the simplified `author` field

**Step 4: Update README.md**

The content authoring front matter example should match the new format (already updated in earlier commit — just verify `author_username` is absent).

**Step 5: Commit**

```
docs: update architecture docs for author simplification
```

---

### Task 15: Final cleanup and full check

**Step 1: Search for any remaining references**

Search the entire codebase for:
- `author_username` — should only appear in git history and the design doc
- `default_author` — should only appear in git history and the design doc
- `post_owner_service` — should not appear anywhere
- `sync_default_author_from_admin` — should not appear anywhere
- `update_user_display_name` — should not appear anywhere

**Step 2: Run the full quality gate**

Run: `just check`

Fix any remaining failures.

**Step 3: Commit any fixes**

```
fix: address remaining author simplification cleanup
```
