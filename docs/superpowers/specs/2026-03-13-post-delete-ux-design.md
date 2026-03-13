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
- Always call `deletePost(filePath, true)` (delete with assets) for all posts. For flat posts (`.md` only), `delete_assets=true` is a no-op since there is no directory.
- Show a single unified warning message for all posts:
  *"This will permanently delete "{title}" and all associated files. This cannot be undone."*
- Single "Delete" confirm button (`data-testid="confirm-delete"`).
- Simplify component state: `deleteMode: 'post' | 'all' | null` → `showDeleteConfirm: boolean`.

### Change 2: Fix modal visibility via React Portal

- Render the delete confirmation modal via `ReactDOM.createPortal(modal, document.body)`.
- This breaks the modal out of the `<article>`'s CSS transform containing block.
- The `fixed inset-0 z-50` overlay then correctly covers the full viewport regardless of scroll position or animation state.

---

## Affected Files

- `frontend/src/pages/PostPage.tsx` — main implementation
- `frontend/src/pages/__tests__/PostPage.test.tsx` — test updates

---

## Test Changes

- `'confirming delete navigates to home'`: update assertion from `deletePost('posts/hello.md', false)` → `deletePost('posts/hello.md', true)`.
- Add test: directory-backed post (`/index.md`) shows the same unified warning and single confirm button (no two-option UI).
- Existing confirmation dialog, cancel, and error tests remain valid with minor wording adjustment if needed.

---

## Out of Scope

- Backend changes (API already supports `delete_assets=true`)
- CSS animation changes
- Any other page or component
