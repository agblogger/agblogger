# Analytics

## Purpose

Analytics gives AgBlogger page-view tracking and statistics without depending on third-party hosted services. A self-hosted GoatCounter sidecar collects hits, and the backend proxies stats to the admin dashboard and optionally exposes per-post view counts to readers.

GoatCounter is treated as a soft dependency — the backend starts and serves content normally when GoatCounter is unavailable.

## Architecture

The feature is built around a sidecar model:

- a GoatCounter container on the internal Docker network owns the hits database and stats API
- the backend service records hits, proxies stats, and manages persisted settings
- the frontend surfaces stats in an admin dashboard tab and optional public view counts on posts

The backend communicates with GoatCounter through its internal HTTP API using an API token scoped to hit recording and stats reads. The GoatCounter database stays private to the sidecar. The token and database live on separate named volumes so the sidecar can re-provision when either is independently replaced. To tolerate that recovery path, the backend re-reads the mounted token file for each hit or stats request instead of assuming the first successful read remains valid forever.

Two admin-controlled toggles — analytics-enabled and show-views-on-posts — are stored in a durable Alembic-managed table and persist independently of GoatCounter's availability.

## Data Flow

When a reader fetches a post or page through the API, the backend fires an asynchronous hit to GoatCounter. Hits are fire-and-forget — network failures are logged but never affect the reader's response. Admin users are excluded (non-admin authenticated users are still tracked), and detected bots are filtered out. Background analytics work is bounded so public traffic spikes cannot create an unbounded number of in-flight tasks.

Admin dashboard statistics — total views, per-path hits, referrers, browser and OS breakdowns — are proxied from GoatCounter's stats API through admin-only backend endpoints. Stats are only served while analytics is enabled. The frontend reads settings first and short-circuits stats fetches when analytics is disabled so the normal off state is not presented as a GoatCounter outage.

## Content Relationship

Public view counts are only exposed when analytics is enabled, the per-post toggle is on, and the requested slug resolves to a published post. The public endpoint normalizes canonical file paths back to the short GoatCounter path before looking up hits, so different URL forms for the same post resolve to the same count.

The endpoint returns the same `views: null` response for draft, disabled, or non-existent posts (deleted posts are removed from the cache and thus behave as non-existent) to avoid leaking hidden content state.

## UI Placement

The UI surfaces analytics in two places:

- an admin dashboard tab displaying page-view statistics, referrers, and browser breakdowns with date-range controls
- an optional view count in post metadata, controlled by the admin show-views toggle

## Security Boundaries

The GoatCounter sidecar is internal to the deployment. Its API token never leaves the private Docker network and is mounted into the application container through a dedicated read-only token volume rather than the full GoatCounter data volume. The GoatCounter database is not shared with the application container. Background analytics work is bounded to prevent public traffic from creating unbounded in-process work.

## Code Entry Points

- `backend/api/analytics.py` exposes the admin stats proxy and public view-count endpoints.
- `backend/services/analytics_service.py` orchestrates hit recording, stats retrieval, and settings management.
- `backend/models/analytics.py` contains the durable analytics settings table model.
- `frontend/src/components/admin/AnalyticsPanel.tsx` is the lazy-loaded admin dashboard tab.
- `frontend/src/api/analytics.ts` contains the analytics API client functions for admin and public use.
- `goatcounter/entrypoint.sh` is the sidecar's provisioning and startup script.
