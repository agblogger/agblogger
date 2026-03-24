# GoatCounter Analytics Integration

## Overview

Server-internal GoatCounter analytics integration for AgBlogger. GoatCounter runs as a sidecar Docker container on the internal network with no public exposure. The AgBlogger backend is the sole client — it records page hits server-side and proxies the stats API for the admin dashboard.

## Architecture

### Container Topology

GoatCounter runs alongside the existing `agblogger` and `caddy` services in docker-compose:

- **Image**: Official GoatCounter Docker image
- **Network**: Internal Docker network only — no `ports` mapping, only `expose`
- **Storage**: Persistent volume (`goatcounter-db`) for its SQLite database
- **Startup**: Does not block AgBlogger startup — soft dependency
- **Access**: Reachable only at `http://goatcounter:8080` from within the Docker network

### API Token Provisioning

GoatCounter requires an API token for stat queries. On first boot, the GoatCounter container entrypoint:

1. Creates a site and generates an API token
2. Writes the token to a shared volume that AgBlogger reads on startup
3. Skips on subsequent boots if already initialized

### Data Flow

**Hit recording** (on every post/page view):

1. Browser navigates to a post → frontend calls `GET /api/posts/{slug}`
2. Backend serves the response to the reader
3. Backend fires an async `POST http://goatcounter:8080/api/v0/count` with the path, client IP, and User-Agent
4. GoatCounter records the hit and handles deduplication internally

**Dashboard** (admin panel):

1. Admin opens the Analytics tab → frontend calls AgBlogger API endpoints
2. Backend proxies to GoatCounter's `GET /api/v0/stats/*` endpoints
3. Backend transforms and returns data to the frontend

## Backend

### New Service: `backend/services/analytics_service.py`

Responsibilities:

- **Recording hits**: Async method called from post/page API handlers. Sends `POST /api/v0/count` with `path`, client IP, and `User-Agent`. Fire-and-forget — failures logged but never block the response.
- **Fetching stats**: Proxies GoatCounter's stats endpoints — total views, per-path hits, referrers, browser/OS breakdowns. Accepts date range parameters.
- **Settings management**: Read/update analytics settings (enabled toggle, show views on posts).

Uses `httpx.AsyncClient` with short timeouts (2-3s for hits, 5s for dashboard queries). Hits are batched where possible using GoatCounter's array-based `/api/v0/count` endpoint.

### New API Router: `backend/api/analytics.py`

Admin endpoints (require `require_admin`):

- `GET /api/admin/analytics/stats/total` — total pageview counts (date range filter)
- `GET /api/admin/analytics/stats/hits` — per-path view/visitor stats (date range filter)
- `GET /api/admin/analytics/stats/hits/{path_id}` — referrer breakdown for a specific path
- `GET /api/admin/analytics/stats/{category}` — browser, OS, etc. breakdowns
- `GET /api/admin/analytics/settings` — current analytics settings
- `PUT /api/admin/analytics/settings` — update analytics settings

Public endpoint:

- `GET /api/analytics/views/{slug}` — view count for a single post. Returns data only when `analytics_show_views_on_posts` is enabled; returns `null` when disabled.

### Hit Recording Integration

In the existing post and page API handlers, after serving a successful response, fire the hit asynchronously. Gated on the `analytics_enabled` setting.

**What gets tracked**:

- `GET /api/posts/{slug}` — post views
- `GET /api/pages/{id}` — static page views

**What gets forwarded to GoatCounter**:

- `path` — the public URL path (e.g. `/post/building-with-rust`, `/page/about`)
- Client IP (respecting `X-Forwarded-For` behind proxy) — for unique visitor deduplication
- `User-Agent` header — for browser/OS stats

**What does NOT get tracked**:

- API calls from authenticated users (admin/editor activity)
- Search, label browsing, timeline
- Bot requests (common crawlers filtered by User-Agent)

### Admin Settings (Durable Database Table)

Two settings, stored in a durable table:

| Setting | Type | Default | Description |
|---|---|---|---|
| `analytics_enabled` | bool | `true` | Kill switch — stops sending hits when off |
| `analytics_show_views_on_posts` | bool | `false` | Show view count on post pages |

## Frontend

### Admin Panel — Analytics Tab

New "Analytics" tab added to the existing admin panel (`AdminPage.tsx`), alongside Settings, Pages, Account, Social.

**Dashboard layout**:

1. **Top bar**: Date range selector (7d / 30d / 90d / custom) and the two toggle settings
2. **Summary cards**: Total views, unique visitors, top page today
3. **Views over time**: Area chart (Recharts) showing views and unique visitors per day
4. **Top pages table**: Sortable — page path, views, unique visitors. Clickable rows drill into page detail.
5. **Page detail view** (drill-down): Views-over-time chart for the selected page, plus referrer sources table
6. **Breakdown panels**: Browser and OS distribution as horizontal bar charts

### Post View Count Display

On `PostPage`, when `analytics_show_views_on_posts` is enabled, fetch `GET /api/analytics/views/{slug}` and display the count near the post title (e.g. "142 views").

### Dependencies

- **Recharts** (~45KB gzipped) for charts — area charts, bar charts

## Error Handling & Reliability

**GoatCounter unavailability**:

- Hit recording fails silently — logged at WARNING level, reader experience unaffected
- Dashboard endpoints return 503 with "Analytics service unavailable"
- `httpx.AsyncClient` uses short timeouts (2-3s hits, 5s dashboard)

**Startup behavior**: AgBlogger does NOT depend on GoatCounter to start. If GoatCounter is unavailable:

- Hit recording is skipped
- Dashboard shows "Analytics unavailable" message
- All other functionality works normally

**API token missing**: Analytics service logs a warning and disables itself until the token becomes available. No crash.

**Settings fallback**: Fresh installs use defaults (`analytics_enabled=true`, `analytics_show_views_on_posts=false`).

## Deployment

### Docker Compose Changes

New `goatcounter` service:

- Internal network only (no port mappings)
- Persistent `goatcounter-db` volume
- Healthcheck on API endpoint
- Starts before `agblogger` in compose ordering

### Deployment Helper Updates

`cli/deploy_production.py` updated to:

- Include the GoatCounter container in generated compose files
- Add `goatcounter-db` volume to persistent storage
- Handle GoatCounter in `setup.sh` orchestration

### Caddy

No Caddy changes — GoatCounter has no public routes.
