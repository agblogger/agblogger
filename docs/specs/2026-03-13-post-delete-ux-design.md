# Post Delete UX: Simplification & Modal Visibility Fix

**Date**: 2026-03-13
**Scope**: `frontend/src/pages/PostPage.tsx` and its test file

---

## Problem Statement

Two issues with post deletion UX:

1. **Delete choice**: Directory-backed posts (`/index.md`) show two delete options ("Delete post only" vs "Delete with all files"). The desired behavior is to always delete the full directory with no choice, showing only a warning.

2. **Modal visibility**: The confirmation modal uses `position: fixed` but appears off-screen for long posts. Root cause: the `<article>` wrapper has `animate-fade-in`, whose CSS keyframe applies `transform: translateY(...)`. Any CSS `transform` on an ancestor creates a new CSS containing block for `position: fixed` descendants, so the modal is positioned relative to the article rather than the viewport.

---

## Design

### Change 1: Simplify deletion to always delete full directory

- Remove the two-button UI for directory-backed posts.
- Always call `deletePost(filePath, true)` (delete with assets) for all posts. For flat posts (`.md` only), the backend ignores the `delete_assets=true` flag since there is no directory.
- Show a single unified warning for all posts:
  *"This will permanently delete "{title}". This cannot be undone."*
  (Avoids inaccurate "and all associated files" phrasing for flat `.md` posts where no assets exist.)
- Single "Delete" confirm button (`data-testid="confirm-delete"`).
- Simplify component state: `deleteMode: 'post' | 'all' | null` → `showDeleteConfirm: boolean`.

### Change 2: Fix modal visibility via React Portal

- Add `import { createPortal } from 'react-dom'` to `PostPage.tsx` (not currently imported).
- Render the delete confirmation modal via `createPortal(modal, document.body)`.
- This breaks the modal out of the `<article>`'s CSS transform containing block. The `forward` fill mode on the `0.4s` animation keeps `transform: translateY(0)` applied indefinitely, meaning the containing block problem persists permanently after load — not just during animation.
- The `fixed inset-0 z-50` overlay then correctly covers the full viewport regardless of scroll position or animation state.

---

## Affected Files

- `frontend/src/pages/PostPage.tsx` — main implementation
- `frontend/src/pages/__tests__/PostPage.test.tsx` — test updates

---

## Test Changes

- `'confirming delete navigates to home'`: update assertion from `deletePost('posts/hello.md', false)` → `deletePost('posts/hello.md', true)`.
- `'shows confirmation dialog on delete click'`: asserts `/This will permanently delete/` — this regex matches the updated warning text; no assertion change needed. After Change 1 the same unified message appears for both post types.
- `'shows error on delete failure'`: exercises the same delete code path (also calls `deletePost` with `true` after Change 1) but does not assert on call arguments — no test change needed. The error path must reset `showDeleteConfirm` to `false` (replacing the current `setDeleteMode(null)`), preserving the existing assertion that the dialog closes on error.
- `'cancel closes confirmation dialog'`: Cancel must call `setShowDeleteConfirm(false)` (replacing `setDeleteMode(null)`) — the test assertion remains unchanged.
- Add test: directory-backed post (`draftPost` fixture, `/index.md`) shows the unified single-button confirmation dialog (not the two-option UI).
- All other existing tests remain valid.
- `createPortal` renders into `document.body` in jsdom; `screen` queries search the full `document.body`, so portalled content is found without any test setup changes.
- The `animate-fade-in` class on the inner modal dialog box is intentionally kept — it animates the dialog appearance. Since the inner dialog has no `position: fixed` children, it does not introduce a new problematic containing block.

---

## Out of Scope

- Backend changes (API already supports `delete_assets=true`)
- CSS animation changes
- Any other page or component
