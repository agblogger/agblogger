# Analytics

## Purpose

Analytics gives AgBlogger page-view tracking and statistics without depending on third-party hosted services. A self-hosted GoatCounter sidecar collects hits, and the backend proxies stats to the admin dashboard and optionally exposes per-post view counts to readers.

GoatCounter is treated as a soft dependency — the backend starts and serves content normally when GoatCounter is unavailable. Deployments can also omit the sidecar entirely; in that mode analytics requests continue to follow the existing missing-token/offline-sidecar path without affecting core traffic.

## Architecture

The feature is built around a sidecar model:

- a GoatCounter container on the internal Docker network owns the hits database and stats API
- the backend service records hits, proxies stats, and manages persisted settings
- the frontend surfaces stats in an admin dashboard tab and optional public view counts on posts

Two admin-controlled toggles -- analytics-enabled and show-views-on-posts -- are stored as a singleton row in a durable Alembic-managed table. The stored values remain durable across redeploys, but the backend clamps the effective analytics-enabled state off whenever the deployment omits the GoatCounter sidecar.

## Sidecar deployment and provisioning

The backend communicates with GoatCounter through its internal HTTP API using an API token scoped to hit recording and stats reads. Requests connect over the internal Docker service name, but they present the GoatCounter site host expected by the sidecar so the analytics site resolves consistently. The deployment helper and backend normalize that configured host to the same bare hostname before provisioning sites or sending `Host` headers. The sidecar provisions idempotently through GoatCounter's own CLI lookups, resolving the site-specific admin user before creating or syncing the shared API token, so it can recover when the token volume is replaced or the configured site host changes while the database volume persists. Because current GoatCounter CLI builds do not expose the stats permission correctly during token creation, the entrypoint also repairs the token permission bitmask in the database on startup. On every start it also repairs the token-file mode so the non-root AgBlogger process can still read the shared token after upgrades or volume reuse. The GoatCounter database stays private to the sidecar. The token and database live on separate named volumes so the sidecar can recover when either is independently replaced.

## Data Flow

When a reader fetches a post or page through the API, the backend fires an asynchronous hit to GoatCounter. The server-rendered frontend routes for direct post and page loads also fire the same canonical hit before returning the preloaded HTML, so initial visits, refreshes, and no-JS browsing are counted instead of relying on a client-side API fetch. Hits are fire-and-forget — network failures are logged but never affect the reader's response. The backend sends the canonical path together with the client IP and user agent so GoatCounter can apply its normal session-based deduplication without any browser-side JavaScript. Admin users are excluded (non-admin authenticated users are still tracked), and detected bots are filtered out. Background analytics work is bounded so public traffic spikes cannot create an unbounded number of in-flight tasks.

Admin dashboard statistics — unique views, per-path views, referrers, browser and OS breakdowns — are proxied from GoatCounter's stats API through admin-only backend endpoints. GoatCounter only tracks unique views (first-visit per session), not raw pageview counts: the ``total`` and per-path ``count`` fields already represent deduplicated visitors. The dashboard shows "Page Views" (sum of per-path unique views) and "Visitors" (site-wide unique visitors from GoatCounter's ``total``), giving two distinct and meaningful metrics. The frontend computes the selected local-day window in the browser and sends explicit UTC start/end instants. Stats are only served while analytics is enabled. The frontend reads settings first and short-circuits stats fetches when analytics is disabled, returning zeroed-out data so the normal off state shows empty dashboards rather than loading spinners or GoatCounter outage errors.

## Content Relationship

Public view counts are only exposed when analytics is enabled, the per-post toggle is on, and the requested slug resolves to a published post. The public endpoint normalizes canonical file paths back to the short GoatCounter path before looking up hits, so different URL forms for the same post resolve to the same count.

The endpoint returns the same `views: null` response for draft, disabled, or non-existent posts (deleted posts are removed from the cache and thus behave as non-existent) to avoid leaking hidden content state.

## UI Placement

The UI surfaces analytics in two places:

- an admin dashboard tab with a full set of panels delegated to focused sub-components under `frontend/src/components/admin/analytics/`:
  - summary cards showing page views, visitors, and the top page
  - a views-over-time chart with automatic daily/weekly granularity selection
  - top pages with inline per-path referrer drill-down alongside a site-wide referrers panel
  - browser and OS breakdowns with version drill-down, and location and language tables
  - a screen-sizes chart and campaigns table
  - a custom date range picker with common presets
  - CSV export via GoatCounter's async export API
- an optional view count in post metadata, controlled by the admin show-views toggle

## Security Boundaries

The GoatCounter sidecar is internal to the deployment. Its API token never leaves the private Docker network and is mounted into the application container through a dedicated read-only token volume rather than the full GoatCounter data volume. The GoatCounter database is not shared with the application container. Background analytics work is bounded to prevent public traffic from creating unbounded in-process work.

## Code Entry Points

- `backend/api/analytics.py` exposes the admin stats proxy and public view-count endpoints, including site-wide referrer aggregation, breakdown version detail, and the three-step CSV export lifecycle (create, poll, download).
- `backend/services/analytics_service.py` orchestrates hit recording, stats retrieval, and settings management.
- `backend/models/analytics.py` contains the durable analytics settings table model.
- `frontend/src/components/admin/AnalyticsPanel.tsx` is the lazy-loaded admin dashboard orchestrator that composes the sub-components below.
- `frontend/src/components/admin/analytics/` contains the extracted analytics sub-components: charts, tables, drill-downs, the date range picker, and the export button.
- `frontend/src/hooks/useAnalyticsDashboard.ts` provides composite SWR hooks for the dashboard, including site-wide referrers and breakdown version detail.
- `frontend/src/api/analytics.ts` contains the analytics API client functions for admin and public use.
- `goatcounter/entrypoint.sh` is the sidecar's provisioning and startup script, including site-host normalization from deployment-provided environment.
