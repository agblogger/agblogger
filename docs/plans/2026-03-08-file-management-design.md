# File Management in Editor — Design

## Problem

After uploading assets to a post, users have no way to view, rename, or delete them. The only file-related UI is an upload button that inserts markdown references. Users need visibility into attached files and basic management operations.

## Design

### Layout: Collapsible Strip

A horizontal strip below the metadata bar, above the editor/preview split.

**Collapsed state:** Single line showing file count:
```
📎 Files (3)                                         [▼]
```

**Expanded state:** Horizontal flex row of ~80×80px cards that wraps to multiple lines if needed. Each card shows a thumbnail (images) or file-type icon (other files) with the filename below. The last card is always a dashed-border "+ Upload" button. Starts collapsed by default.

### File Card Actions

Each card has a kebab menu (⋮) with:

1. **Insert** — Inserts `![filename](filename)` (images) or `[filename](filename)` (other) at cursor position
2. **Copy name** — Copies filename to clipboard
3. **Rename** — Inline edit: filename becomes a text input, Enter confirms, Escape cancels. On confirm, all markdown references in the body are auto-updated (`![...](old)` → `![...](new)`)
4. **Delete** — If file is referenced in markdown body, confirmation dialog: "This file is referenced in your post. Delete anyway?" (Cancel / Delete). If not referenced, delete immediately

### Save-and-Stay Flow

Currently, saving a new post navigates to the post view page. This changes to:

- **New post save:** Post is created, URL replaces to `/editor/{new-file-path}` — user stays on the editor. FileStrip becomes functional immediately.
- **Existing post save:** No change (already stays on editor).

Before first save, FileStrip shows "Save to start adding files" with upload disabled.

### View Post Button

A "View post" button in the editor toolbar, visible only after the post has been saved at least once. If the editor has unsaved changes, a `window.confirm` prompt asks "You have unsaved changes. Leave without saving?" — OK navigates to the post view, Cancel stays on the editor.

### Backend API

Three new endpoints:

- `GET /api/posts/{file_path}/assets` — Returns `{ assets: [{ name, size, is_image }] }`. Reads post directory, excludes `index.md` and hidden files.
- `DELETE /api/posts/{file_path}/assets/{filename}` — Deletes file from disk, commits to git. Returns 204.
- `PATCH /api/posts/{file_path}/assets/{filename}` — Body: `{ "new_name": "..." }`. Validates filename, renames on disk, commits to git. Returns `{ name, size, is_image }`. Does not update markdown body (handled client-side).

All endpoints require admin authentication.

### Frontend Components

- `FileStrip.tsx` — Collapsible container below metadata. Manages local state (asset list, expanded/collapsed, loading). Fetches assets on mount, re-fetches after upload/delete/rename.
- `FileCard.tsx` — Individual card with thumbnail/icon, filename, kebab menu, inline rename state.

No new Zustand store. FileStrip uses local state and receives callbacks from EditorPage for cursor insertion and body reference updates.

### Integration

- Upload button moves from editor toolbar into FileStrip
- Drag-and-drop on textarea remains (triggers FileStrip re-fetch)
- Thumbnails loaded via existing `GET /api/content/{file_path}` endpoint
- Existing `POST /api/posts/{file_path}/assets` endpoint used for uploads
