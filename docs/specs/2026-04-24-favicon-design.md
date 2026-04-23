# Favicon Feature Design

**Date:** 2026-04-24

## Summary

Add per-deployment favicon support. `content/index.toml` is the source of truth. The admin panel provides upload/replace/remove UI. No-JS browsers are fully supported via backend HTML injection.

## Data Model

`content/index.toml` gains an optional `favicon` field under `[site]`:

```toml
[site]
title = "My Blog"
favicon = "assets/favicon.png"
```

The value is a path relative to `content/`. The actual image file lives at that path (e.g. `content/assets/favicon.png`). When the field is absent, no favicon is configured.

Supported formats: PNG, ICO, SVG, WebP.

## Backend

### Schema changes

- `SiteConfig` dataclass: add `favicon: str | None = None`
- `SiteSettingsResponse`: add `favicon: str | None`
- `SiteSettingsUpdate`: no change (favicon is not updated via the site settings PUT endpoint — it has its own endpoints)
- `GET /api/admin/site` and `PUT /api/admin/site` both return `SiteSettingsResponse` which now includes `favicon`

### New endpoints

**`GET /favicon.ico`**
- Reads `favicon` path from `index.toml` via site config
- Streams the file from `content/assets/`; sets `Content-Type` based on file extension
- Returns 404 when unset or file missing
- Public — no auth required

**`POST /api/admin/favicon`**
- Admin-only
- Accepts a single multipart file upload (PNG, ICO, SVG, WebP); rejects other types
- Saves file to `content/assets/favicon.{ext}`; if a favicon with a different extension already exists, removes the old file first
- Updates `index.toml` to set `favicon = "assets/favicon.{ext}"`
- Returns updated `SiteSettingsResponse`

**`DELETE /api/admin/favicon`**
- Admin-only
- Removes the file at the configured path from `content/assets/`
- Clears the `favicon` field from `index.toml`
- Returns updated `SiteSettingsResponse`

### `index.html` serving

The backend intercepts its own `index.html` catch-all route. When a favicon is configured:
- Injects `<link rel="icon" href="/favicon.ico">` into `<head>` before serving
- When unset: serves `index.html` unmodified

The hardcoded `<link rel="icon">` (currently an emoji SVG) is removed from `frontend/index.html`.

## Frontend Admin UI

The favicon widget lives inside `SiteSettingsSection.tsx`, below the Timezone field and above the Save Settings button. It is a standalone section with its own API calls — independent of the Save Settings flow.

**Empty state** (no favicon set):
- Helper text: "No favicon set — browsers will show a blank tab icon."
- Dashed upload button: "Upload image (PNG, ICO, SVG, WebP)" — triggers file picker, uploads immediately on selection

**Set state** (favicon configured):
- Thumbnail preview of the current favicon
- Filename and `index.toml` path displayed
- "Replace" button — triggers file picker, uploads immediately on selection, replaces existing
- "Remove" button — calls DELETE endpoint immediately, clears favicon
- Helper text: "Shown in browser tabs, bookmarks, and address bar."

Both upload and remove are immediate (no Save Settings required). While the operation is in progress, controls are disabled. Errors and success are shown inline.

## Sync CLI Path

No special handling required. The user places the image in `content/assets/` and sets `favicon = "assets/favicon.png"` in `index.toml`. The sync CLI transfers both files naturally as part of content sync.

## Testing

- Backend unit tests: `GET /favicon.ico` returns file when set, 404 when unset; `POST /api/admin/favicon` saves file and updates TOML; `DELETE /api/admin/favicon` removes file and clears TOML field; `index.html` injection inserts/omits `<link>` correctly
- Frontend tests: empty-state renders upload button; set-state renders preview + Replace + Remove; upload disables controls during request; remove disables controls during request
- Security: non-admin cannot call `POST`/`DELETE` admin endpoints; only allowed MIME types accepted; file saved to `content/assets/` only (no path traversal)
