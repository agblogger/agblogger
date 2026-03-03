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
| `/editor/*` | EditorPage | Structured metadata bar + split-pane markdown editor |
| `/admin` | AdminPage | Admin panel: site settings, pages, password (admin required) |

## Editor Auto-Save

The `useEditorAutoSave` hook (`hooks/useEditorAutoSave.ts`) provides crash recovery and unsaved-changes protection:

- **Dirty tracking**: Compares current form state (body, labels, isDraft, newPath) to the loaded/initial state
- **Debounced auto-save**: Writes draft to `localStorage` (key: `agblogger:draft:<filePath>`) 3 seconds after the last edit
- **Navigation blocking**: `useBlocker` shows a native `window.confirm` dialog for in-app SPA navigation; `beforeunload` covers tab close and page refresh
- **Draft recovery**: On editor mount, detects stale drafts and shows a banner with Restore/Discard options
- **Enabled gating**: The hook accepts an `enabled` parameter; for existing posts it activates only after loading completes, preventing false dirty state during data fetch

## State Management

Two Zustand stores:

- **`authStore`** — User state (`user`, `isLoading`, `isLoggingOut`, `isInitialized`, `error`), login/logout, session check via `checkAuth()`.
- **`siteStore`** — Site configuration fetched on app load.

The `ky` HTTP client uses cookie-based authentication (`credentials: 'include'`). Browser login relies on `HttpOnly` cookies and keeps only the returned `csrf_token` in memory; it does not store bearer tokens from JSON. For unsafe methods (POST/PUT/PATCH/DELETE), it ensures an in-memory CSRF token is available, fetching it from `GET /api/auth/csrf` when necessary, then injects it as the `X-CSRF-Token` header. On 401 responses, the client auto-attempts a token refresh via `POST /api/auth/refresh`, updates the cached CSRF token from the refresh response, and retries the original request.

## Custom Hooks

- **`useEditorAutoSave`** — Crash recovery and unsaved-changes protection (described above).
- **`useActiveHeading`** — Monitors H2/H3 headings via `IntersectionObserver` for table-of-contents tracking, returning the currently active heading ID.
- **`useRenderedHtml`** (exported from `useKatex.ts`) — Processes KaTeX math spans (`math inline`, `math display`) in rendered HTML strings, replacing them with KaTeX-rendered output.

## Frontend Logic Utilities

To keep route/components thin and directly testable, pure logic helpers are extracted into utility modules:

- `components/labels/graphUtils.ts` centralizes label graph algorithms used by label pages (`computeDepths`, `wouldCreateCycle`, `computeDescendants`)
- `components/crosspost/crosspostText.ts` centralizes public post URL and default cross-post text generation (`buildPostUrl`, `buildDefaultText`)

These modules are covered by property-based tests (`fast-check`) in addition to example-based Vitest tests.
