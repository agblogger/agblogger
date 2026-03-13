# Post Delete UX: Simplification & Modal Visibility Fix — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the two-option delete dialog for directory posts (always delete with assets), and fix the confirmation modal appearing off-screen on long posts by rendering it via a React portal.

**Architecture:** Both changes are confined to a single component file (`PostPage.tsx`). The state is simplified from a `'post' | 'all' | null` union to a plain boolean. The modal JSX is lifted out of the `<article>` element via `createPortal` to bypass the CSS transform containing block created by `animate-fade-in`.

**Tech Stack:** React 18, react-dom (createPortal), Vitest + @testing-library/react

**Spec:** `docs/specs/2026-03-13-post-delete-ux-design.md`

---

## Chunk 1: Tests and implementation

### Task 1: Update and add tests

**Files:**
- Modify: `frontend/src/pages/__tests__/PostPage.test.tsx`

Context: The test file uses two fixtures — `postDetail` (flat `.md` post: `posts/hello.md`) and `draftPost` (directory post: `posts/2026-03-08-draft/index.md`). One existing assertion needs updating; one new test is required.

- [ ] **Step 1: Update the `'confirming delete navigates to home'` assertion**

In `frontend/src/pages/__tests__/PostPage.test.tsx`, find the test at line ~196 and change:

```ts
await waitFor(() => {
  expect(mockDeletePost).toHaveBeenCalledWith('posts/hello.md', false)
})
```

to:

```ts
await waitFor(() => {
  expect(mockDeletePost).toHaveBeenCalledWith('posts/hello.md', true)
})
```

- [ ] **Step 2: Add test — directory post shows unified single-button dialog**

Add this test after the existing `'cancel closes confirmation dialog'` test. Note: pass the directory post path to `renderPostPage` — the default path (`/post/posts/hello.md`) would load `postDetail` (flat post), not `draftPost`.

```ts
it('shows unified single-button confirmation dialog for directory-backed post', async () => {
  mockUser = { id: 1, username: 'admin', email: 'a@b.com', display_name: null, is_admin: true }
  mockFetchPost.mockResolvedValue(draftPost)
  renderPostPage('/post/posts/2026-03-08-draft/index.md')

  await waitFor(() => {
    expect(screen.getByText('My Draft')).toBeInTheDocument()
  })
  await userEvent.click(screen.getByText('Delete'))

  expect(screen.getByText('Delete post?')).toBeInTheDocument()
  // Unified warning message (same for all post types)
  expect(screen.getByText(/This will permanently delete/)).toBeInTheDocument()
  // Single confirm button — not the two-option UI
  expect(screen.getByTestId('confirm-delete')).toBeInTheDocument()
  expect(screen.queryByText('Delete post only')).not.toBeInTheDocument()
  expect(screen.queryByText('Delete with all files')).not.toBeInTheDocument()
})
```

- [ ] **Step 3: Run the tests and verify the two failures**

```bash
cd frontend && npx vitest run src/pages/__tests__/PostPage.test.tsx
```

Expected: 2 failures:
1. `'confirming delete navigates to home'` — `deletePost` called with `false` but expected `true`
2. New test — `confirm-delete` not found (two-option UI is still rendered for directory posts)

All other tests should pass.

- [ ] **Step 4: Commit failing tests**

Only the test assertions should fail — static analysis (TypeScript, ESLint) must still pass. The failing tests are the intentional TDD red state.

```bash
git add frontend/src/pages/__tests__/PostPage.test.tsx
git commit -m "test: update delete assertions and add directory post dialog test"
```

---

### Task 2: Implement changes in PostPage.tsx

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx`

- [ ] **Step 1: Add `createPortal` import**

At the top of `frontend/src/pages/PostPage.tsx`, add to the existing React import line or add a new import:

```ts
import { createPortal } from 'react-dom'
```

The file currently imports from `'react'` on line 1. Add the new import on line 2 (or alongside existing imports).

- [ ] **Step 2: Simplify state — replace `deleteMode` with `showDeleteConfirm`**

Replace:
```ts
const [deleteMode, setDeleteMode] = useState<'post' | 'all' | null>(null)
```
with:
```ts
const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
```

- [ ] **Step 3: Simplify `handleDelete` — always delete with assets**

Replace the entire `handleDelete` function. Key changes from the old version: (a) remove the `withAssets` parameter, (b) hardcode `true` in the `deletePost` call, (c) replace `setDeleteMode(null)` in the catch block with `setShowDeleteConfirm(false)`. Preserve `setDeleting(true/false)` and `setDeleteError(null)` — omitting these would leave the button permanently disabled after an error:

```ts
async function handleDelete() {
  if (filePath === undefined) return
  setDeleting(true)
  setDeleteError(null)
  try {
    await deletePost(filePath, true)
    void navigate('/', { replace: true })
  } catch (err) {
    if (err instanceof HTTPError && err.response.status === 401) {
      setDeleteError('Session expired. Please log in again.')
    } else {
      setDeleteError('Failed to delete post. Please try again.')
    }
    setShowDeleteConfirm(false)
  } finally {
    setDeleting(false)
  }
}
```

- [ ] **Step 4: Update the Delete button to use the new state**

Replace:
```tsx
<button
  onClick={() => setDeleteMode('post')}
  disabled={deleting}
  className="flex items-center gap-1 text-muted hover:text-red-600 dark:hover:text-red-400 transition-colors disabled:opacity-50"
>
```

with:
```tsx
<button
  onClick={() => setShowDeleteConfirm(true)}
  disabled={deleting}
  className="flex items-center gap-1 text-muted hover:text-red-600 dark:hover:text-red-400 transition-colors disabled:opacity-50"
>
```

- [ ] **Step 5: Replace the entire modal block**

Replace the entire `{deleteMode && (...)}` block at the bottom of the JSX (currently lines ~283–350) with a portal-rendered, simplified dialog:

```tsx
{showDeleteConfirm &&
  createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-paper border border-border rounded-xl shadow-xl p-6 max-w-sm mx-4 animate-fade-in">
        <h2 className="font-display text-xl text-ink mb-2">Delete post?</h2>
        <p className="text-sm text-muted mb-6">
          This will permanently delete &ldquo;{post.title}&rdquo;. This cannot be undone.
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={() => setShowDeleteConfirm(false)}
            disabled={deleting}
            className="px-4 py-2 text-sm font-medium text-muted hover:text-ink
                     border border-border rounded-lg transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => void handleDelete()}
            disabled={deleting}
            data-testid="confirm-delete"
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700
                     rounded-lg transition-colors disabled:opacity-50"
          >
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
        {deleting && (
          <p className="text-xs text-muted mt-3 text-center">Deleting...</p>
        )}
      </div>
    </div>,
    document.body,
  )}
```

Note: This replaces the old `{deleteMode && ...}` block including the `</article>` closing tag that was after it. The `</article>` closing tag remains unchanged — only the modal block changes.

- [ ] **Step 6: Run the tests and verify all pass**

```bash
cd frontend && npx vitest run src/pages/__tests__/PostPage.test.tsx
```

Expected: All tests pass.

- [ ] **Step 7: Run the full frontend check**

```bash
cd /path/to/repo && just check-frontend
```

Expected: All static checks and tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/PostPage.tsx
git commit -m "fix: simplify post delete dialog and fix modal visibility via React portal"
```

---

## Chunk 2: Browser verification

### Task 3: End-to-end browser smoke test

**Files:** None (read-only verification)

- [ ] **Step 1: Start the dev server**

```bash
just start
```

Wait for health check:
```bash
just health
```

- [ ] **Step 2: Open a long post in the browser**

Navigate to a post with enough content to require scrolling. Scroll to the bottom of the post. Click "Delete". Verify:
- The confirmation modal appears centered in the viewport (not off-screen)
- The modal shows a single "Delete" button and a "Cancel" button
- There is no "Delete post only" / "Delete with all files" choice

- [ ] **Step 3: Open a directory-backed post and verify the same unified dialog**

Navigate to a post whose URL path includes a directory (e.g., one created from a `index.md`). Click "Delete". Verify the same single-button dialog appears.

- [ ] **Step 4: Verify cancel works**

Click "Cancel" — the dialog should close without deleting.

- [ ] **Step 5: Stop the dev server**

```bash
just stop
```

- [ ] **Step 6: Remove any leftover screenshot files**

```bash
find frontend -name "*.png" -delete 2>/dev/null; echo "done"
```
