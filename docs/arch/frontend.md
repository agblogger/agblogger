# Frontend Architecture

## Role

The frontend is a React single-page application that provides the reading, editing, and administration experience for AgBlogger. The backend remains the source of truth for authentication, authorization, content rendering, and persisted content state.

## Application Shape

The SPA is organized around a shared layout and route-driven page components. Public routes focus on browsing published content, labels, and search. Editor and admin-oriented routes handle authoring, account management, and site administration, with the backend enforcing the final authorization boundary for those actions.

Admin-only management routes are also guarded client-side before rendering workflows that cannot succeed for non-admin users, including the admin panel and label-management entry points such as label creation.

## State Model

Frontend state is deliberately small and split into two categories:

- **server-backed state** such as the current user, site configuration, and resource data — primarily managed by SWR hooks for automatic caching, deduplication, and revalidation
- **client UI state** such as theme selection and shared panel behavior — managed by Zustand stores

SWR handles most server data fetching and caching; Zustand coordinates session, config, and UI-only concerns. The browser is not treated as the long-term source of truth for content or identity.

## Data Fetching

Two patterns are used for reading server data:

**SWR hooks** — used for single-resource reads where the data is stable (not paginated or filtered). Each hook wraps `useSWR` with a conditional key and a dedicated fetcher. Auth-sensitive hooks scope the cache key by user ID so the cache invalidates on login/logout.

| Hook | Key shape | Used by |
|------|-----------|---------|
| `usePost(slug)` | `['post', slug, userId]` | `PostPage` |
| `usePage(pageId)` | `pages/${pageId}` | `PageViewPage` |
| `useLabelPosts(labelId)` | `['labelPosts', labelId, userId]` | `LabelPostsPage` |
| `useLabels()` | `labels` | `LabelsPage` |
| `useViewCount(slug)` | `['viewCount', slug]` | `PostPage` |

**Manual `useEffect`+`useState`** — used for paginated, filtered, or debounced fetches where the query parameters change frequently and SWR's key model is less ergonomic. These components manage their own loading/error state and may use `AbortController` for request cancellation.

| Page | Why not SWR |
|------|-------------|
| `TimelinePage` | Paginated + multi-filter (labels, author, date range) with URL param sync |
| `SearchPage` | Debounced query with abort controller |

Write operations always use direct API calls regardless of the read pattern.

## Server-Side Preloading

On the initial page load, the backend may embed API data in a `<script id="__initial_data__" type="application/json">` tag. The `readPreloadedData<T>()` utility (`frontend/src/utils/preload.ts`) reads and removes this tag once. SWR hooks (`usePost`, `usePage`, `useLabelPosts`) pass the preloaded data as `fallbackData` to skip the initial fetch. The timeline page checks for preloaded data in its `useEffect` and uses it as initial state.

The backend also injects server-rendered HTML inside `<div id="root">` for SEO and no-JS browsers. React's `createRoot().render()` replaces this content on mount — no special cleanup needed.

## Page Titles

Each page component sets `document.title` dynamically via a `useEffect` using the site name from `useSiteStore`. The format is `"{page title} — {site name}"` for content pages and just `"{site name}"` for the homepage.

## API Integration

The frontend talks to the backend through a shared HTTP client shaped around the backend’s cookie-based browser session model. Browser authentication stays cookie-first, CSRF protection is attached to unsafe requests, and session renewal is handled through the API boundary rather than by storing durable bearer credentials in app state.

## Editing Architecture

The editor is built around structured post authoring instead of raw filesystem manipulation. Metadata editing, markdown editing, preview, and asset management are presented as one workflow over a canonical post unit. Preview rendering is delegated to the backend so the editor and published site use the same rendering and sanitization pipeline.

## Rendering Model

The frontend does not own markdown rendering. It receives rendered HTML from the backend and then adds browser-only enhancements such as navigation affordances, math hydration, and interaction helpers.

## Code Entry Points

- `frontend/src/App.tsx` defines the router, shared layout, and application bootstrapping.
- `frontend/src/pages/` contains the main public browsing, authentication, editing and administration entry points.
- `frontend/src/stores/` contains the small set of shared Zustand stores for auth, site config, theme, and UI coordination.
- `frontend/src/api/` contains the HTTP client and API-facing modules that connect the SPA to the backend.
- `frontend/src/hooks/` contains SWR data-fetching hooks (with server-preloaded fallback data support) and client-side enhancements layered on top of backend-rendered content and editor workflows.
- `frontend/src/utils/preload.ts` provides the one-shot `readPreloadedData<T>()` utility for reading server-injected JSON data.
- `frontend/src/components/search/` contains the live search dropdown components used by the header for as-you-type search previews.
- `frontend/src/components/share/` contains the social sharing bar and platform-specific sharing components used by the post view.
- `frontend/src/components/labels/` contains shared label form components (names editor, parents selector) used by both the label creation and label settings pages.
- `frontend/src/utils/postUrl.ts` provides centralized slug extraction and URL generation for post navigation, used by 6+ pages/components.
- `frontend/src/api/analytics.ts` contains the analytics API client functions for the admin dashboard and public view counts.
