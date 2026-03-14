# PR Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical/important issues and implement all suggestions from the 2026-03-14 comprehensive PR review.

**Architecture:** All fixes are isolated to existing files. No new files needed except tests. Each fix is small (1-10 lines) and can be committed independently.

**Tech Stack:** Python/FastAPI backend, pytest async tests, SQLite FTS5

---

## Chunk 1: Critical Fix — Whitespace-only search query

### Task 1: Guard against empty FTS5 query in `search_posts`

**Files:**
- Modify: `backend/services/post_service.py:271` (add empty-terms guard)
- Modify: `tests/test_api/test_api_integration.py` (add whitespace search test)

- [ ] **Step 1: Write the failing test**

Add to the `TestSearch` class in `tests/test_api/test_api_integration.py`, after the `test_search_empty_query_rejected` test:

```python
@pytest.mark.asyncio
async def test_search_whitespace_only_returns_empty(self, client: AsyncClient) -> None:
    """Whitespace-only search query should return empty results, not crash."""
    resp = await client.get("/api/posts/search", params={"q": "   "})
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_api/test_api_integration.py::TestSearch::test_search_whitespace_only_returns_empty -v`
Expected: FAIL with 500 Internal Server Error (FTS5 OperationalError)

- [ ] **Step 3: Write minimal implementation**

In `backend/services/post_service.py`, add an early return after the `terms = query.split()` line (line 271):

```python
    terms = query.split()
    if not terms:
        return []
    safe_query = " ".join('"' + t.replace('"', '""') + '"*' for t in terms if t)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_api/test_api_integration.py::TestSearch -v`
Expected: All search tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/post_service.py tests/test_api/test_api_integration.py
git commit -m "fix: guard against whitespace-only FTS5 search query"
```

---

## Chunk 2: Critical Fix — Security logging for path rejections

### Task 2: Add security logging to `_validate_path` in content.py

**Files:**
- Modify: `backend/api/content.py:1-6,51-56` (add logger + warning logs)
- Modify: `tests/test_api/test_content_api.py` (add log assertion tests)

- [ ] **Step 1: Write the failing tests**

Add to the `TestContentServing` class in `tests/test_api/test_content_api.py`:

```python
@pytest.mark.asyncio
async def test_path_traversal_logs_warning(
    self, client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Path traversal attempts should be logged at WARNING level."""
    with caplog.at_level(logging.WARNING, logger="backend.api.content"):
        await client.get("/api/content/posts/../index.toml")
    assert any("Path traversal" in r.message for r in caplog.records)

@pytest.mark.asyncio
async def test_disallowed_prefix_logs_warning(
    self, client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Disallowed prefix requests should be logged at WARNING level."""
    with caplog.at_level(logging.WARNING, logger="backend.api.content"):
        await client.get("/api/content/index.toml")
    assert any("Disallowed content prefix" in r.message for r in caplog.records)
```

Also add `import logging` to the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_content_api.py::TestContentServing::test_path_traversal_logs_warning tests/test_api/test_content_api.py::TestContentServing::test_disallowed_prefix_logs_warning -v`
Expected: FAIL (no log records matching)

- [ ] **Step 3: Write minimal implementation**

In `backend/api/content.py`, add `import logging` and create the logger after the existing imports:

```python
import logging

logger = logging.getLogger(__name__)
```

Then add logging before each `raise not_found` in `_validate_path`:

```python
    if ".." in file_path.split("/"):
        logger.warning("Path traversal attempt blocked: %s", file_path)
        raise not_found

    if not file_path.startswith(_ALLOWED_PREFIXES):
        logger.warning("Disallowed content prefix requested: %s", file_path)
        raise not_found

    full_path = (content_dir / file_path).resolve()

    if not full_path.is_relative_to(content_dir.resolve()):
        logger.warning("Resolved path escapes content directory: %s", file_path)
        raise not_found
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_content_api.py -v`
Expected: All content API tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/content.py tests/test_api/test_content_api.py
git commit -m "fix: add security logging for content path rejections"
```

---

## Chunk 3: Important Fix — Harden `_resolve_symlink_redirect`

### Task 3: Add path traversal check and OSError handling

**Files:**
- Modify: `backend/api/posts.py:634-653` (add `..` check, try/except, update docstring)
- Modify: `tests/test_api/test_post_rename.py` (add security + error tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api/test_post_rename.py` in the `TestPostRename` class:

```python
@pytest.mark.asyncio
async def test_symlink_redirect_rejects_path_traversal(
    self, client: AsyncClient
) -> None:
    """GET /api/posts/ with .. segments should return 404, not probe the filesystem."""
    resp = await client.get("/api/posts/posts/../../etc/passwd")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_symlink_redirect_handles_broken_symlink(
    self, client: AsyncClient, app_settings: Settings
) -> None:
    """A broken symlink at a post path should return 404, not 500."""
    posts_dir = app_settings.content_dir / "posts"
    broken_dir = posts_dir / "broken-link"
    broken_dir.symlink_to("nonexistent-target")

    resp = await client.get("/api/posts/posts/broken-link/index.md")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_post_rename.py::TestPostRename::test_symlink_redirect_rejects_path_traversal tests/test_api/test_post_rename.py::TestPostRename::test_symlink_redirect_handles_broken_symlink -v`
Expected: First may pass (FastAPI normalizes some paths), second should FAIL with 500

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_symlink_redirect` in `backend/api/posts.py` (lines 634-653):

```python
def _resolve_symlink_redirect(file_path: str, content_manager: ContentManager) -> str | None:
    """Check if a post path resolves through a symlink to a different canonical path.

    Returns the resolved canonical path if a symlink redirect is found, None otherwise.
    Returns None if the resolved path falls outside the content directory,
    preventing symlink-based traversal.
    """
    if ".." in file_path.split("/"):
        return None

    full_path = content_manager.content_dir / file_path
    try:
        if not full_path.exists():
            return None

        resolved = full_path.resolve()
        content_dir_resolved = content_manager.content_dir.resolve()

        if not resolved.is_relative_to(content_dir_resolved):
            logger.warning(
                "Symlink for %s resolves outside content directory", file_path
            )
            return None

        canonical = str(resolved.relative_to(content_dir_resolved))
    except OSError as exc:
        logger.warning("Symlink resolution failed for %s: %s", file_path, exc)
        return None

    if canonical == file_path:
        return None

    return canonical
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_post_rename.py -v`
Expected: All rename tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_post_rename.py
git commit -m "fix: harden symlink redirect with path traversal check and error handling"
```

---

## Chunk 4: Documentation and Comment Fixes

### Task 4: Fix stress testing report inaccuracies

**Files:**
- Modify: `docs/reviews/2026-03-14-stress-testing.md:10,82-85,96,109`

- [ ] **Step 1: Fix the request count**

In `docs/reviews/2026-03-14-stress-testing.md`, change line 10:
- Old: `**8,000+ total HTTP requests**`
- New: `**18,000+ total HTTP requests**`

Change line 96:
- Old: `Zero 5xx errors across all ~8,000+ requests from 11 agents`
- New: `Zero 5xx errors across all ~18,000+ requests from 9 active agents`

- [ ] **Step 2: Fix the author display name claim**

Change lines 82-85 from:
```
- Existing posts continue showing the **username** ("admin"), not the display name
- Display name change does **not** retroactively update the author field on existing posts
- Setting display_name to "" results in `null` in the API response
- **This is consistent with the architecture (posts store author username, not display name)**
```
To:
```
- The `author` column in the database stores the username, but API responses resolve the display name at query time via `COALESCE(display_name, username)` join
- Changing a user's display name takes effect immediately for all posts by that user in both list and detail responses
- Setting display_name to "" results in `null` in the API response (falls back to username)
- **This is consistent with the architecture (posts store author username; display name is resolved at read time)**
```

- [ ] **Step 3: Fix the observation about list responses**

Change line 109 from:
```
3. **Display name vs author field:** The `author` field on posts stores the username, not the display name. Changing display_name does not update existing posts. The display name is resolved at read time for the `PostDetail` response, but the `author` field in list responses shows the username.
```
To:
```
3. **Display name vs author field:** The `author` column in the database stores the username. The display name is resolved at read time via a `COALESCE(display_name, username)` join for both `PostDetail` and `PostSummary` (list) responses, so changing a user's display name takes effect immediately across all their posts.
```

- [ ] **Step 4: Commit**

```bash
git add docs/reviews/2026-03-14-stress-testing.md
git commit -m "docs: fix factual inaccuracies in stress testing report"
```

### Task 5: Fix page service comment

**Files:**
- Modify: `backend/services/page_service.py:32`

- [ ] **Step 1: Update the comment**

In `backend/services/page_service.py`, change line 32 from:
```python
        # Virtual pages (timeline, labels, etc.) are handled by the frontend
```
To:
```python
        # Pages without a backing file are handled entirely by the frontend
```

- [ ] **Step 2: Run tests to verify nothing broke**

Run: `just test-backend -- tests/test_services/test_page_service.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/services/page_service.py
git commit -m "docs: clarify page service comment to match actual condition"
```

### Task 6: Add response metadata for redirect in get_post_endpoint

**Files:**
- Modify: `backend/api/posts.py:656` (update response_model)

- [ ] **Step 1: Update the endpoint decorator**

In `backend/api/posts.py`, change the decorator on `get_post_endpoint` from:
```python
@router.get("/{file_path:path}", response_model=PostDetail)
```
To:
```python
@router.get(
    "/{file_path:path}",
    response_model=PostDetail,
    responses={301: {"description": "Redirects to the canonical post path after a rename"}},
)
```

- [ ] **Step 2: Run tests to verify nothing broke**

Run: `just test-backend -- tests/test_api/test_post_rename.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/api/posts.py
git commit -m "docs: add 301 redirect response metadata to get_post_endpoint"
```

---

## Chunk 5: Final Verification

### Task 7: Run full check

- [ ] **Step 1: Run the full gate**

Run: `just check`
Expected: All static checks and tests PASS

- [ ] **Step 2: Review the diff**

Run: `git diff origin/main...HEAD --stat` to verify all changes are accounted for.
