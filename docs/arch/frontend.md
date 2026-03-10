# Frontend Architecture

## Routing

Uses `createBrowserRouter` (data router) with `RouterProvider` for full react-router v7 feature support including `useBlocker`.

| Route | Page | Description |
|-------|------|-------------|
| `/` | TimelinePage | Paginated post list with filter panel, post upload (file/folder) |
| `/post/*` | PostPage | Single post view (rendered HTML) |
| `/page/:pageId` | PageViewPage | Top-level page (About, etc.) |
| `/search` | SearchPage | Full-text search results |
| `/login` | LoginPage | Login form |
| `/labels` | LabelsPage | Label list/graph with segmented control toggle (auth: graph edge create/delete) |
| `/labels/:labelId` | LabelPostsPage | Posts filtered by label |
| `/labels/:labelId/settings` | LabelSettingsPage | Label names, parents, delete (admin-only mutations) |
| `/editor/*` | EditorPage | Structured metadata bar, collapsible file strip, split-pane markdown editor |
| `/admin` | AdminPage | Admin panel: site settings, pages, account (profile + password), social accounts (admin required) |

## Editor Auto-Save

The `useEditorAutoSave` hook (`hooks/useEditorAutoSave.ts`) provides crash recovery and unsaved-changes protection:

- **Dirty tracking**: Compares current form state (title, body, labels, isDraft) to the loaded/initial state
- **Debounced auto-save**: Writes draft to `localStorage` (key: `agblogger:draft:<filePath>`) 3 seconds after the last edit
- **Navigation blocking**: `useBlocker` shows a native `window.confirm` dialog for in-app SPA navigation; `beforeunload` covers tab close and page refresh
- **Draft recovery**: On editor mount, detects stale drafts and shows a banner with Restore/Discard options
- **Enabled gating**: The hook accepts an `enabled` parameter; for existing posts it activates only after loading completes, preventing false dirty state during data fetch

## File Management Strip

The `FileStrip` component (`components/editor/FileStrip.tsx`) provides inline asset management within the editor, positioned between the metadata bar and the editor/preview split:

- **Collapsible strip**: Header shows paperclip icon + file count; expands to show `FileCard` grid with thumbnails (images) or file-type icons
- **Directory-backed posts only**: The strip renders for new drafts and saved posts whose canonical path ends in `/index.md`; legacy flat-file paths do not expose asset management UI
- **Operations**: Upload (via hidden file input), delete (with confirmation if file is referenced in body), rename (with auto-update limited to markdown link/image destinations that reference the renamed asset), insert markdown at cursor, copy filename
- **Save-and-stay flow**: New posts stay on the editor after save (URL replaces to `/editor/{file_path}`); a "View post" button appears once saved
- **Backend endpoints**: `GET /api/posts/{file_path}/assets` (list), `DELETE .../assets/{filename}` (delete), `PATCH .../assets/{filename}` (rename); these endpoints reject flat-file post paths

## Admin Settings

The admin settings tab exposes the editable site-level fields (`title`, `description`, `timezone`). The account tab allows users to change their username and display name (via `PATCH /api/auth/me`), with the display name shown as the author on all posts. Username changes update the `author` field in all matching markdown files on disk and refresh the posts cache. The account tab also contains the password change form.

## State Management

Four Zustand stores:

- **`authStore`** — User state (`user`, `isLoading`, `isLoggingOut`, `isInitialized`, `error`), login/logout, session check via `checkAuth()`.
- **`siteStore`** — Site configuration fetched on app load.
- **`themeStore`** — Theme preference (`mode`: light/dark/system, `resolvedTheme`: light/dark). Persists to `localStorage` (key: `agblogger:theme`), listens to system preference changes, and provides `toggleMode()` to cycle through modes.
- **`filterPanelStore`** — Shared state for the filter panel (`panelState`: closed/open/closing, `activeFilterCount`). The filter toggle button lives in `Header` (rendered only on the timeline page `/`), while the panel body lives in `FilterPanel` within `TimelinePage`. The store coordinates open/close state between these components.

The `ky` HTTP client uses cookie-based authentication (`credentials: 'include'`). Browser login relies on `HttpOnly` cookies and keeps only the returned `csrf_token` in memory; it does not store bearer tokens from JSON. For unsafe methods (POST/PUT/PATCH/DELETE), it ensures an in-memory CSRF token is available, fetching it from `GET /api/auth/csrf` when necessary, then injects it as the `X-CSRF-Token` header. On 401 responses, the client auto-attempts a token refresh via `POST /api/auth/refresh`, updates the cached CSRF token from the refresh response, and retries the original request.

## Custom Hooks

- **`useEditorAutoSave`** — Crash recovery and unsaved-changes protection (described above).
- **`useActiveHeading`** — Monitors H2/H3 headings via `IntersectionObserver` for table-of-contents tracking, returning the currently active heading ID.
- **`useRenderedHtml`** (exported from `useKatex.ts`) — Processes KaTeX math spans (`math inline`, `math display`) in rendered HTML strings, replacing them with KaTeX-rendered output.
- **`useCodeBlockEnhance`** — Adds copy-to-clipboard buttons and language labels to fenced code blocks. Detects language from `class="language-*"` or Pandoc format classes, uses `MutationObserver` for dynamic content.

## Frontend Logic Utilities

To keep route/components thin and directly testable, pure logic helpers are extracted into utility modules:

- `components/labels/graphUtils.ts` centralizes label graph algorithms used by label pages (`computeDepths`, `wouldCreateCycle`, `computeDescendants`)
- `components/crosspost/crosspostText.ts` centralizes public post URL and default cross-post text generation (`buildPostUrl`, `buildDefaultText`)

Additionally, `components/share/useShareHandlers.ts` encapsulates share logic (share text generation, platform-specific handlers, clipboard copy, Mastodon instance prompt) used by `ShareButton` and `ShareBar`.

These modules are covered by property-based tests (`fast-check`) in addition to example-based Vitest tests.
