# Analytics Dashboard Feature Parity

Close the gap between GoatCounter's built-in dashboard and the AgBlogger admin analytics panel, without exposing GoatCounter's web interface publicly.

## Goals

- Feature parity with GoatCounter's dashboard data categories
- Comparable or better user-friendliness
- No change to the security model (GoatCounter stays internal-only)
- No N+1 query problems in frontend data fetching

## Non-goals

- Exposing GoatCounter's built-in web dashboard
- Event tracking (no event-emitting code exists yet; add when needed)
- Time-of-day heatmap (low value, not available via GoatCounter API)

## Dashboard Layout

Single scrollable view (Approach A — incremental panel additions with component extraction). Section order top to bottom:

1. **Top bar** — date range presets (7d, 30d, 90d) + custom date picker + analytics toggles + Export CSV button
2. **Summary cards** — Page Views, Visitors, Top Page (unchanged)
3. **Views over time** — daily bar chart; auto-switches to weekly buckets for ranges over 30 days
4. **Top pages + Top referrers** — side by side; top pages has inline referrer drill-down (click a row to expand referrers directly below it); top referrers is a new site-wide aggregated view
5. **Browsers + Operating Systems** — horizontal bar charts (top 8); click an entry to expand version breakdown inline below it
6. **Locations + Languages** — ranked tables with country/language, visitor count, percentage
7. **Screen Sizes + Campaigns** — screen sizes as bar chart, campaigns as ranked table

## Panel Formats

- **Bar charts**: browsers, operating systems, screen sizes (short labels, visual comparison)
- **Tables**: locations, languages, campaigns, site-wide referrers (longer labels, read better as text)

## Drill-down Interactions

All drill-downs use a consistent inline expansion pattern:

- **Top pages → referrers**: clicking a page row expands referrers below that row, indented with accent left border
- **Browsers → versions**: clicking a browser entry expands version breakdown inline below that entry
- **Operating Systems → versions**: same pattern as browsers

Clicking again or clicking a different entry collapses the current expansion.

## Custom Date Range

- Date picker appears inline next to the preset buttons, showing the active start/end dates
- Selecting a preset updates the picker; editing the picker deselects the preset
- Validates start < end, disables future dates
- The existing `start`/`end` query params already flow through to GoatCounter

## Views Over Time Chart

- Uses Recharts `BarChart` (consistent with existing bar charts)
- Daily granularity for ranges up to 30 days, weekly buckets for 31+ days
- Tooltip shows date + view count on hover
- Data derived from aggregating per-path daily counts returned by GoatCounter's `/api/v0/stats/hits`

## CSV Export

- Uses GoatCounter's async export API: `POST /api/v0/export` → poll `GET /api/v0/export/{id}` → download `GET /api/v0/export/{id}/download`
- Button shows "Exporting..." with disabled state during the async job
- Triggers browser download on completion; shows error message on failure

## Backend Changes

### New endpoints

- `GET /api/admin/analytics/stats/referrers` — aggregated site-wide referrers. The backend collects referrer data across paths in a single operation and returns a merged, deduplicated, sorted list. This avoids N+1 fetches from the frontend.
- `GET /api/admin/analytics/stats/{category}/{id}` — version drill-down for browsers/OS. Proxies GoatCounter's `/api/v0/stats/{page}/{id}`.
- `POST /api/admin/analytics/export` — create CSV export job.
- `GET /api/admin/analytics/export/{id}` — poll export job status.
- `GET /api/admin/analytics/export/{id}/download` — download completed export.

### New service functions

- `fetch_site_referrers(session, start, end)` — aggregate referrers across all paths into a single ranked list
- `fetch_breakdown_detail(session, category, entry_id)` — proxy version drill-down
- `create_export(session)` / `get_export_status(session, id)` / `download_export(session, id)` — export job lifecycle

### Views over time data

The existing `fetch_path_hits` returns per-path data with daily counts. A new `fetch_views_over_time(session, start, end)` function aggregates this into daily totals. The frontend buckets daily totals into weekly groups client-side when the selected range exceeds 30 days.

### Existing endpoints — no changes needed

The breakdown endpoint `GET /api/admin/analytics/stats/{category}` already supports languages, locations, sizes, and campaigns. No backend changes needed for these.

## Frontend Changes

### Component extraction

`AnalyticsPanel.tsx` becomes an orchestrator. New components:

- `ViewsOverTimeChart` — bar chart with auto-granularity
- `TopPagesPanel` — table with inline referrer expansion
- `TopReferrersPanel` — site-wide referrers table
- `BreakdownBarChart` — reusable for browsers, OS, screen sizes; supports optional inline version drill-down
- `BreakdownTable` — reusable for locations, languages, campaigns
- `DateRangePicker` — custom date range selector
- `ExportButton` — CSV export with async job polling

### Data fetching

- New SWR hooks for: site-wide referrers, version drill-down (keyed by category + entry ID), export status polling
- Breakdown hooks for languages, locations, sizes, campaigns use the existing `useAnalyticsDashboard` pattern or individual SWR hooks per category
- All fetches respect the analytics-enabled short-circuit (return zeroed data when off)
- Avoid N+1: site-wide referrers come from a single backend endpoint, not per-path frontend aggregation

### Empty states and loading

- Each panel shows "No data for selected range" when empty
- Inline drill-downs show a small spinner while loading
- Export button shows "Exporting..." and disables during async job
- All new panels respect analytics-enabled toggle (zeroed out when off)

## Error Handling

- New panels follow existing patterns: network errors show panel-level error messages
- Export failure shows inline error below the button
- Custom date picker shows validation error for invalid ranges
- All new endpoints return 503 when GoatCounter is unavailable (existing pattern)

## Testing

### Backend

- New service functions tested with mocked GoatCounter responses
- Site-wide referrer aggregation: test merging across multiple paths, deduplication, sorting
- Version drill-down proxy: test response transformation
- Export lifecycle: test create, poll, download, and error states
- New endpoints: test auth requirements, parameter validation, 503 on unavailability

### Frontend

- Each extracted component tested in isolation
- Date picker: validation (start < end, no future dates), preset/custom interaction
- Inline drill-down: expand/collapse, loading states, error states
- Export button: state transitions (idle → exporting → download/error)
- Integration: verify new panels render with mock data, respect analytics-enabled toggle
