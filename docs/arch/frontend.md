# Frontend Architecture

## Role

The frontend is a React single-page application that provides the reading, editing, and administration experience for AgBlogger. The backend remains the source of truth for authentication, authorization, content rendering, and persisted content state.

## Application Shape

The SPA is organized around a shared layout and route-driven page components. Public routes focus on browsing published content, labels, and search. Editor and admin-oriented routes handle authoring, account management, and site administration, with the backend enforcing the final authorization boundary for those actions.

## State Model

Frontend state is deliberately small and split into two categories:

- **server-backed state** such as the current user and site configuration
- **client UI state** such as theme selection and shared panel behavior

Zustand stores coordinate those concerns, but the browser is not treated as the long-term source of truth for content or identity.

## API Integration

The frontend talks to the backend through a shared HTTP client shaped around the backend’s cookie-based browser session model. Browser authentication stays cookie-first, CSRF protection is attached to unsafe requests, and session renewal is handled through the API boundary rather than by storing durable bearer credentials in app state.

## Editing Architecture

The editor is built around structured post authoring instead of raw filesystem manipulation. Metadata editing, markdown editing, preview, and asset management are presented as one workflow over a canonical post unit. Preview rendering is delegated to the backend so the editor and published site use the same rendering and sanitization pipeline.

## Rendering Model

The frontend does not own markdown rendering. It receives rendered HTML from the backend and then adds browser-only enhancements such as navigation affordances, math hydration, and interaction helpers.

## Code Entry Points

- `frontend/src/App.tsx` defines the router, shared layout, and application bootstrapping.
- `frontend/src/pages/TimelinePage.tsx`, `frontend/src/pages/PostPage.tsx`, `frontend/src/pages/PageViewPage.tsx`, `frontend/src/pages/SearchPage.tsx`, and `frontend/src/pages/LabelsPage.tsx` are the main public browsing entry points.
- `frontend/src/pages/EditorPage.tsx`, `frontend/src/pages/AdminPage.tsx`, and `frontend/src/pages/LabelSettingsPage.tsx` are the main editing and administration entry points.
- `frontend/src/stores/` contains the small set of shared Zustand stores for auth, site config, theme, and UI coordination.
- `frontend/src/api/` contains the HTTP client and API-facing modules that connect the SPA to the backend.
- `frontend/src/hooks/` contains client-side enhancements layered on top of backend-rendered content and editor workflows.
