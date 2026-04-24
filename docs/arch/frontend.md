# Frontend Architecture

## Role

The frontend is a React single-page application that provides the reading, editing, and administration experience for AgBlogger. The backend remains the source of truth for authentication, authorization, content rendering, and persisted content state.

## Application Shape

The SPA is organized around a shared layout and route-driven page components. Public routes focus on browsing published content, labels, and search. Editor and admin-oriented routes handle authoring, account management, and site administration, with the backend enforcing the final authorization boundary for those actions. Admin-only management routes are also guarded client-side.

## State Model

Frontend state is deliberately small and split into two categories:

- **server-backed state** such as the current user, site configuration, and resource data — primarily managed by SWR hooks for automatic caching, deduplication, and revalidation
- **client UI state** such as theme selection and shared panel behavior — managed by Zustand stores

SWR handles most server data fetching and caching; Zustand coordinates session, config, and UI-only concerns. The browser is not treated as the long-term source of truth for content or identity.

## Data Fetching

Single-resource reads (individual posts, pages, label detail) use SWR hooks for caching and revalidation. Paginated and filtered views (timeline, search) use manual `useEffect`+`useState` because their query parameters change frequently with URL param sync.

The timeline route treats the URL as the canonical filter state. Pagination, label filters, and date filters all round-trip through query params, with date ranges encoded as API-ready UTC/ISO timestamps in the URL while the UI still renders local `YYYY-MM-DD` input values.

Auth-sensitive reads scope their cache key by user ID so the cache invalidates on login/logout. Write operations always use direct API calls.

## Server-Side Preloading

On the initial page load, the backend embeds pre-rendered HTML inside `<div id="root">` and structured metadata as a server-owned JSON script tag outside the rendered content tree. The SPA reads both sources on boot via a declarative preload utility, merging them into typed objects. Rendered HTML content lives only in the server HTML — the preload utility extracts it from the DOM. The preload script is identified with a dedicated marker that sanitized user content cannot forge, so rendered markdown cannot spoof bootstrap metadata. This gives crawlers and no-JS browsers real content, while the SPA gets structured data without a round-trip. React replaces the server HTML on mount; client-side navigations fetch from the API normally. Client-only routes such as login, admin, and editor paths are served as the plain SPA shell without SEO preload data so refreshes and direct links still boot the router correctly.

## API Integration

The frontend talks to the backend through a shared HTTP client shaped around the backend’s cookie-based browser session model. Browser authentication stays cookie-first, CSRF protection is attached to unsafe requests, and session renewal is handled through the API boundary rather than by storing durable bearer credentials in app state.

Application boot also installs small compatibility shims needed by runtime dependencies before the router and data layer initialize. Keep these shims in the frontend bootstrap path so public pages do not crash on older-but-still-supported browsers.

## Editing Architecture

The editor is built around structured post authoring instead of raw filesystem manipulation. Metadata editing, markdown editing, preview, and asset management are presented as one workflow over a canonical post unit. Preview rendering is delegated to the backend so the editor and published site use the same rendering and sanitization pipeline.

## Rendering Model

The frontend does not own markdown rendering. It receives rendered HTML from the backend and then adds browser-only enhancements such as navigation affordances, math hydration, and interaction helpers.

## Code Entry Points

- `frontend/src/main.tsx` is the application entry point; it installs compatibility shims and mounts the React tree.
- `frontend/src/App.tsx` defines the router and shared layout.
- `frontend/src/bootstrap/` contains startup compatibility shims that must run before app dependencies initialize.
- `frontend/src/pages/` contains the main public browsing, authentication, editing and administration entry points.
- `frontend/src/stores/` contains the small set of shared Zustand stores for auth, site config, theme, and UI coordination.
- `frontend/src/api/` contains the HTTP client and API-facing modules that connect the SPA to the backend.
- `frontend/src/hooks/` contains SWR data-fetching hooks (with server-preloaded fallback data support) and client-side enhancements layered on top of backend-rendered content and editor workflows.
- `frontend/src/utils/preload.ts` provides the preload system: low-level utilities for reading JSON metadata and extracting HTML from the server-rendered DOM, plus a declarative consumer API that merges both sources into typed objects.
- `frontend/src/utils/postUrl.ts` provides centralized slug extraction and URL generation for post navigation.
- `frontend/src/components/search/` contains the live search dropdown components used by the header for as-you-type search previews.
- `frontend/src/components/share/` contains the social sharing bar and platform-specific sharing components used by the post view.
- `frontend/src/components/labels/` contains shared label form components (names editor, parents selector) used by both the label creation and label settings pages.
- `frontend/src/components/admin/analytics/` contains analytics sub-components: charts, tables, drill-downs, the date range picker, and the export button.
