# Frontend Architecture

## Role

The frontend is a React single-page application that provides the reading, editing, and administration experience for AgBlogger. The backend remains the source of truth for authentication, authorization, content rendering, and persisted content state.

## Application Shape

The SPA is organized around a shared layout and route-driven page components. Public routes focus on browsing published content, labels, and search. Editor and admin-oriented routes handle authoring, account management, and site administration, with the backend enforcing the final authorization boundary for those actions.

Admin-only management routes are also guarded client-side before rendering workflows that cannot succeed for non-admin users, including the admin panel and label-management entry points such as label creation.

## State Model

Frontend state is deliberately small and split into two categories:

- **server-backed state** such as the current user, site configuration, and resource data — managed by SWR hooks (`frontend/src/hooks/`) for automatic caching, deduplication, and revalidation
- **client UI state** such as theme selection and shared panel behavior — managed by Zustand stores

SWR owns server data fetching and caching; Zustand coordinates session, config, and UI-only concerns. The browser is not treated as the long-term source of truth for content or identity.

## API Integration

The frontend talks to the backend through a shared HTTP client shaped around the backend’s cookie-based browser session model. Browser authentication stays cookie-first, CSRF protection is attached to unsafe requests, and session renewal is handled through the API boundary rather than by storing durable bearer credentials in app state.

## Data Fetching

Read-only data fetching uses SWR hooks in `frontend/src/hooks/`. A global `SWRConfig` in the `Layout` component (`App.tsx`) provides the default fetcher backed by the ky API client. Each resource has a dedicated hook (e.g., `useLabels`, `usePost`, `useSocialAccounts`) that encapsulates the SWR key, fetcher, and return types.

Shared hooks like `useLabels()` (used by 5 components) and `useSocialAccounts()` (used by 3 components) provide automatic request deduplication — multiple components calling the same hook share a single network request and cache entry. SWR also provides caching across navigation and automatic revalidation on window focus.

Write operations (create, update, delete) use direct API calls from `frontend/src/api/`. After a mutation, components call `mutate()` from the relevant SWR hook to trigger revalidation.

Components with debounced search (Header, SearchPage) and paginated/filtered fetches (TimelinePage) continue to use manual `useEffect`+`useState` patterns, as do mutation-only components.

Tests use `<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>` for cache isolation between test cases.

## Editing Architecture

The editor is built around structured post authoring instead of raw filesystem manipulation. Metadata editing, markdown editing, preview, and asset management are presented as one workflow over a canonical post unit. Preview rendering is delegated to the backend so the editor and published site use the same rendering and sanitization pipeline.

Frontend post navigation and editor workflows assume the backend canonical post shape `posts/<slug>/index.md`. The SPA no longer preserves or generates legacy `posts/<slug>.md` flat-file paths.

## Rendering Model

The frontend does not own markdown rendering. It receives rendered HTML from the backend and then adds browser-only enhancements such as navigation affordances, math hydration, and interaction helpers.

## Analytics

The admin panel includes an Analytics tab that displays page view statistics from the backend's GoatCounter proxy. The dashboard component (`frontend/src/components/admin/AnalyticsPanel.tsx`) is lazy-loaded to keep the main bundle small since it pulls in a charting library (currently Recharts).

The dashboard shows summary cards (total views, unique visitors, top page), a top pages table with referrer drill-down, and browser/OS breakdown bar charts. Date range selection (7d/30d/90d) and settings toggles (analytics enabled, show views on posts) are included.

When the admin enables "show views on posts", individual post pages display a view count in the metadata bar, fetched from the public analytics API endpoint.

## Code Entry Points

- `frontend/src/App.tsx` defines the router, shared layout, and application bootstrapping.
- `frontend/src/pages/` contains the main public browsing, authentication, editing and administration entry points.
- `frontend/src/stores/` contains the small set of shared Zustand stores for auth, site config, theme, and UI coordination.
- `frontend/src/api/` contains the HTTP client and API-facing modules that connect the SPA to the backend.
- `frontend/src/hooks/` contains SWR data-fetching hooks (e.g., `useLabels`, `usePost`, `useSocialAccounts`) and client-side enhancements layered on top of backend-rendered content and editor workflows.
- `frontend/src/components/search/` contains the live search dropdown components used by the header for as-you-type search previews.
- `frontend/src/components/share/` contains the social sharing bar and platform-specific sharing components used by the post view.
- `frontend/src/components/labels/` contains shared label form components (names editor, parents selector) used by both the label creation and label settings pages.
- `frontend/src/utils/postUrl.ts` provides centralized slug extraction and URL generation for post navigation, used by 6+ pages/components.
- `frontend/src/api/analytics.ts` contains the analytics API client functions for the admin dashboard and public view counts.
