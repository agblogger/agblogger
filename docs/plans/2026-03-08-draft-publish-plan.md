# Draft Publish UX Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add prominent draft indicators and a one-click Publish button on the post page, with `created_at` updated on draft-to-published transitions.

**Architecture:** The existing `PUT /api/posts/{file_path}` update endpoint gains draft-to-published transition detection (3 lines). The frontend PostPage gets a draft badge + Publish button that calls `fetchPostForEdit` then `updatePost` with `is_draft: false`.

**Tech Stack:** Python/FastAPI backend, React/TypeScript frontend, pytest + vitest tests.

---

### Task 1: Backend — Write failing tests for draft-to-published `created_at` transition

**Files:**
- Create: `tests/test_api/test_publish_transition.py`

**Step 1: Write the failing tests**

```python
"""Tests for draft-to-published created_at transition."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestPublishTransition:
    """Tests for created_at behavior during draft/publish transitions."""

    @pytest.mark.asyncio
    async def test_publish_updates_created_at(self, client: AsyncClient) -> None:
        """Publishing a draft should set created_at to the publish time."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a draft post
        resp = await client.post(
            "/api/posts",
            json={"title": "Draft Post", "body": "Content.\n", "is_draft": True, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]
        original_created_at = resp.json()["created_at"]

        # Publish it (draft -> non-draft)
        resp = await client.put(
            f"/api/posts/{file_path}",
            json={"title": "Draft Post", "body": "Content.\n", "is_draft": False, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 200
        published_created_at = resp.json()["created_at"]

        # created_at should have changed (updated to publish time)
        assert published_created_at != original_created_at

    @pytest.mark.asyncio
    async def test_non_transition_update_preserves_created_at(
        self, client: AsyncClient
    ) -> None:
        """Updating a published post without draft change should preserve created_at."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create and publish a post
        resp = await client.post(
            "/api/posts",
            json={"title": "Published Post", "body": "Content.\n", "is_draft": False, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]
        original_created_at = resp.json()["created_at"]

        # Update without changing draft status
        resp = await client.put(
            f"/api/posts/{file_path}",
            json={
                "title": "Published Post",
                "body": "Updated content.\n",
                "is_draft": False,
                "labels": [],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["created_at"] == original_created_at

    @pytest.mark.asyncio
    async def test_redraft_and_republish_updates_created_at(
        self, client: AsyncClient
    ) -> None:
        """Re-drafting and re-publishing should update created_at again."""
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Create and publish
        resp = await client.post(
            "/api/posts",
            json={"title": "Cycle Post", "body": "Content.\n", "is_draft": True, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        resp = await client.put(
            f"/api/posts/{file_path}",
            json={"title": "Cycle Post", "body": "Content.\n", "is_draft": False, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 200
        first_publish_created_at = resp.json()["created_at"]

        # Re-draft
        resp = await client.put(
            f"/api/posts/{file_path}",
            json={"title": "Cycle Post", "body": "Content.\n", "is_draft": True, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 200

        # Re-publish
        resp = await client.put(
            f"/api/posts/{file_path}",
            json={"title": "Cycle Post", "body": "Content.\n", "is_draft": False, "labels": []},
            headers=headers,
        )
        assert resp.status_code == 200
        second_publish_created_at = resp.json()["created_at"]

        # created_at should have updated again
        assert second_publish_created_at != first_publish_created_at
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api/test_publish_transition.py -v`
Expected: `test_publish_updates_created_at` FAILS (created_at unchanged), other two may pass or fail.

**Step 3: Commit failing tests**

```
git add tests/test_api/test_publish_transition.py
git commit -m "test: add failing tests for publish transition created_at"
```

---

### Task 2: Backend — Implement draft-to-published `created_at` transition

**Files:**
- Modify: `backend/api/posts.py:584` (after `now = now_utc()`)

**Step 1: Add transition detection**

In `update_post_endpoint`, after line 584 (`now = now_utc()`) and before `title = body.title` (line 585), add:

```python
        # Draft → published transition: update created_at to publish time
        if existing.is_draft and not body.is_draft:
            created_at = now
```

This goes between the existing `now = now_utc()` line and `title = body.title`.

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_api/test_publish_transition.py -v`
Expected: All 3 tests PASS.

**Step 3: Run full backend tests to verify no regressions**

Run: `just test-backend`
Expected: All tests pass.

**Step 4: Commit**

```
git add backend/api/posts.py
git commit -m "feat: update created_at on draft-to-published transition"
```

---

### Task 3: Frontend — Write failing tests for PostPage draft badge and Publish button

**Files:**
- Modify: `frontend/src/pages/__tests__/PostPage.test.tsx`

**Step 1: Update mocks and add test fixtures**

Add `updatePost` and `fetchPostForEdit` to the mock at the top of the file. Update the mock setup:

```typescript
// In the vi.mock('@/api/posts') block, add the new functions:
vi.mock('@/api/posts', () => ({
  fetchPost: vi.fn(),
  deletePost: vi.fn(),
  updatePost: vi.fn(),
  fetchPostForEdit: vi.fn(),
}))
```

Add imports and mock references after existing ones:

```typescript
import { fetchPost, deletePost, updatePost, fetchPostForEdit } from '@/api/posts'
// ...
const mockUpdatePost = vi.mocked(updatePost)
const mockFetchPostForEdit = vi.mocked(fetchPostForEdit)
```

Add a draft post fixture alongside the existing `postDetail`:

```typescript
const draftPost: PostDetail = {
  id: 2,
  file_path: 'posts/2026-03-08-draft/index.md',
  title: 'My Draft',
  author: 'Admin',
  created_at: '2026-03-08 10:00:00+00:00',
  modified_at: '2026-03-08 10:00:00+00:00',
  is_draft: true,
  rendered_excerpt: '<p>Draft excerpt</p>',
  labels: ['tech'],
  rendered_html: '<p>Draft content</p>',
  content: null,
}
```

Add to the `beforeEach`:

```typescript
mockUpdatePost.mockReset()
mockFetchPostForEdit.mockReset()
```

**Step 2: Write failing tests**

Add these tests inside the `describe('PostPage', ...)` block:

```typescript
  it('shows draft badge and publish button for draft post when authenticated', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
  })

  it('does not show draft badge or publish button for published post', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(postDetail)
    renderPostPage()

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /publish/i })).not.toBeInTheDocument()
  })

  it('does not show draft badge or publish button for unauthenticated user', async () => {
    mockFetchPost.mockResolvedValue(draftPost)
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

    await waitFor(() => {
      expect(screen.getByText('My Draft')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /publish/i })).not.toBeInTheDocument()
  })

  it('publish button calls update API with is_draft false', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    mockFetchPostForEdit.mockResolvedValue({
      file_path: 'posts/2026-03-08-draft/index.md',
      title: 'My Draft',
      body: 'Draft content.\n',
      labels: ['tech'],
      is_draft: true,
      created_at: '2026-03-08 10:00:00+00:00',
      modified_at: '2026-03-08 10:00:00+00:00',
      author: 'Admin',
    })
    const publishedPost = { ...draftPost, is_draft: false }
    mockUpdatePost.mockResolvedValue(publishedPost)
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(mockUpdatePost).toHaveBeenCalledWith(
        'posts/2026-03-08-draft/index.md',
        expect.objectContaining({ is_draft: false }),
      )
    })
  })

  it('publish button is disabled during API call', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
    mockFetchPost.mockResolvedValue(draftPost)
    // Make fetchPostForEdit hang to test loading state
    mockFetchPostForEdit.mockImplementation(
      () => new Promise(() => {}),
    )
    renderPostPage('/post/posts/2026-03-08-draft/index.md')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /publish/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /publish/i })).toBeDisabled()
    })
  })
```

**Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/PostPage.test.tsx`
Expected: New tests FAIL (no Draft badge or Publish button rendered).

**Step 4: Commit failing tests**

```
git add frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "test: add failing tests for PostPage draft badge and publish button"
```

---

### Task 4: Frontend — Implement draft badge and Publish button on PostPage

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx`

**Step 1: Add imports and state**

Add to imports at the top:

```typescript
import { fetchPost, deletePost, fetchPostForEdit, updatePost } from '@/api/posts'
```

Add state variable after the existing state declarations (around line 24-25):

```typescript
const [publishing, setPublishing] = useState(false)
```

**Step 2: Add handlePublish function**

Add after the `handleDelete` function (after line 48):

```typescript
  async function handlePublish() {
    if (filePath === undefined) return
    setPublishing(true)
    try {
      const editData = await fetchPostForEdit(filePath)
      const updated = await updatePost(filePath, {
        title: editData.title,
        body: editData.body,
        labels: editData.labels,
        is_draft: false,
      })
      setPost(updated)
    } catch {
      // Publish failed — user can retry
    } finally {
      setPublishing(false)
    }
  }
```

**Step 3: Add draft badge and Publish button to the header**

In the `<header>` section, between the `<h1>` title and the metadata `<div>` (between lines 131 and 133), add:

```tsx
        {user && post.is_draft && (
          <div className="flex items-center justify-between mt-3">
            <span className="text-xs px-2 py-0.5 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded-full font-medium">
              Draft
            </span>
            <button
              onClick={() => void handlePublish()}
              disabled={publishing}
              className="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent/90 rounded-lg transition-colors disabled:opacity-50"
            >
              {publishing ? 'Publishing...' : 'Publish'}
            </button>
          </div>
        )}
```

**Step 4: Run frontend tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/PostPage.test.tsx`
Expected: All tests PASS.

**Step 5: Commit**

```
git add frontend/src/pages/PostPage.tsx
git commit -m "feat: add draft badge and publish button on post page"
```

---

### Task 5: Full verification

**Step 1: Run full static checks + tests**

Run: `just check`
Expected: All checks pass.

**Step 2: Fix any issues found by static analysis**

If ruff, eslint, knip, or type checks flag anything, fix it.

**Step 3: Final commit if needed**

Commit any fixes from step 2.
