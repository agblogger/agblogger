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

GoatCounter requires an API token for stat queries. A custom entrypoint script handles first-boot provisioning:

1. Check if the site already exists (presence of `/data/goatcounter/token` file)
2. If not, run `goatcounter db create site -createdb -vhost=stats.internal -user.email=admin@example.com` to create the site with its SQLite database
3. Run `goatcounter db create apitoken -user=admin@example.com -perm=count,site_read` to generate the API token needed for hit recording and stats reads
4. Write the token to `/data/goatcounter/token` (a shared volume mounted by both containers)
5. On subsequent boots, skip steps 2-4 if the token file already exists

**AgBlogger reads the token lazily** — on the first analytics operation (hit recording or dashboard request), the analytics service checks for the token file. If not yet available, the operation is skipped with a warning log. Each subsequent request re-checks if the token file has appeared. No polling loop, no restart required.

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

- `GET /api/analytics/views/{file_path:path}` — view count for a single post. Accepts the same path formats as the post endpoint (bare slug or full file path) for consistency. Returns data only when `analytics_show_views_on_posts` is enabled; returns `null` when disabled. Must not reveal the existence of draft or unpublished posts — returns the same response for non-existent and draft slugs.

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

- Requests from authenticated users — if the request carries a valid session cookie, the hit is not recorded. This distinguishes admin/editor browsing from public readers on the same endpoints.
- Search, label browsing, timeline
- Bot requests (detected via `crawlerdetect` library)

### Admin Settings (Durable Database Table)

Two settings, stored in a new durable table (managed by Alembic migration):

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

- **Recharts** (~45KB gzipped) for charts — area charts, bar charts. Lazy-loaded (dynamic import) since it's only used in the admin Analytics tab.

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
