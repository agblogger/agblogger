---
name: rss-footer-button
description: Add an unobtrusive RSS icon to the existing site footer so readers can discover and subscribe to the feed
metadata:
  type: project
---

# RSS Footer Button

## Goal

Make the RSS feed at `/feed.xml` discoverable for readers without cluttering the header.

## Context

- The feed endpoint (`/feed.xml`) already exists and is fully implemented.
- `frontend/index.html` already contains `<link rel="alternate" type="application/rss+xml" href="/feed.xml">` for machine discovery.
- The only gap is a visible UI affordance for human readers.

## Design

### Footer change (`frontend/src/App.tsx`)

The existing footer renders a single `<p>` with "Powered by AgBlogger". Add the RSS icon inline on the same line, separated by a `·` character, to avoid adding vertical height.

Resulting layout (single row):

```
Powered by AgBlogger · [rss icon]
```

The RSS element is an `<a href="/feed.xml">` containing:
- `Rss` icon from lucide-react at `size={14}`
- `aria-label="RSS feed"` and `title="RSS feed"`
- Same `text-xs text-muted hover:text-accent transition-colors` style as the Privacy Policy link

The separator `·` uses `text-muted/40` so it recedes visually.

The Privacy Policy link (conditional on `subscriptionsEnabled`) stays on its own row below, unchanged.

### `index.html` — already done

`<link rel="alternate" type="application/rss+xml" title="RSS Feed" href="/feed.xml">` is already present in `frontend/index.html:7`. No change needed.

## Files Changed

- `frontend/src/App.tsx` — inline RSS icon in the existing footer `<p>`

## Out of Scope

- No new component
- No new setting or feature flag
- No header change
