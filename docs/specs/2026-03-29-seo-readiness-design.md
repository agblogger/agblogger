# SEO Readiness Design

## Problem

AgBlogger is a React SPA served as static files. When a crawler or social bot requests any page, it receives an empty `<div id="root">` and a JS bundle. The only exception is `/post/{slug}`, which gets Open Graph meta tags injected by the backend — but no actual content in the HTML body.

This means:
- Search engines that don't execute JS see no content at all
- Search engines that do execute JS (Google) must wait for JS execution + API fetch before indexing
- No sitemap, robots.txt, RSS feed, structured data, meta descriptions, or canonical URLs
- Non-post pages (homepage, custom pages, label pages) have no server-side enrichment
- Social sharing previews only work for individual posts

## Design

Eight improvements, built on a shared SEO service.

### 1. SEO Service (`backend/services/seo_service.py`)

Replaces `backend/services/opengraph_service.py`.

**`SeoContext` dataclass:**

| Field | Type | Purpose |
|-------|------|---------|
| `title` | `str` | `<title>` and `og:title` |
| `description` | `str` | `<meta name="description">` and `og:description` |
| `canonical_url` | `str` | `<link rel="canonical">` |
| `og_type` | `str` (default `"website"`) | `og:type` — `"article"` for posts |
| `site_name` | `str \| None` | `og:site_name` |
| `author` | `str \| None` | `article:author` (posts only) |
| `published_time` | `str \| None` | `article:published_time` (posts only) |
| `modified_time` | `str \| None` | `article:modified_time` (posts only) |
| `json_ld` | `dict \| None` | Structured data |
| `rendered_body` | `str \| None` | Server-rendered HTML for pre-rendering |
| `preload_data` | `dict \| None` | API response to embed as JSON for frontend |

**`render_seo_html(base_html: str, ctx: SeoContext) -> str`:**

1. Replace `<title>` with `ctx.title`
2. Inject `<meta name="description">` and `<link rel="canonical">` before `</head>`
3. Inject OG tags (title, description, url, type, site_name, plus article-specific when present)
4. Inject Twitter Card tags (card, title, description)
5. Inject `<script type="application/ld+json">` when `ctx.json_ld` is set
6. When `ctx.rendered_body` is set, inject it inside `<div id="root">` with a minimal inline style block for visual stability
7. When `ctx.preload_data` is set, inject `<script id="__initial_data__" type="application/json">` before `</body>`

All injected values are HTML-escaped. Descriptions are truncated to 200 characters with ellipsis.

The existing `strip_html_tags()` helper moves into this module. `opengraph_service.py` is deleted.

### 2. Server-Rendered Content

When `rendered_body` is present, it is injected inside `<div id="root">` with minimal inline styles for visual stability before the SPA takes over.

**Post pages:**

```html
<div id="root">
  <article style="max-width:42rem;margin:0 auto;padding:2rem 1rem;font-family:system-ui,sans-serif;line-height:1.7;color:#1a1a1a">
    <h1 style="font-size:2.25rem;line-height:1.2;margin-bottom:0.5rem">Post Title</h1>
    <p style="color:#666;font-size:0.875rem;margin-bottom:2rem">March 28, 2026 · Author Name</p>
    <!-- post.rendered_html from Pandoc -->
  </article>
</div>
```

**Post list pages (`/`, `/labels/{labelId}`):**

```html
<div id="root">
  <main style="max-width:42rem;margin:0 auto;padding:2rem 1rem;font-family:system-ui,sans-serif;line-height:1.7;color:#1a1a1a">
    <h1 style="font-size:2.25rem;line-height:1.2;margin-bottom:1.5rem">Blog Title</h1>
    <ul style="list-style:none;padding:0">
      <li style="margin-bottom:1.5rem">
        <a href="/post/my-post" style="font-size:1.25rem;color:#1a1a1a;text-decoration:none">Post Title</a>
        <p style="color:#666;font-size:0.875rem;margin:0.25rem 0">March 28, 2026</p>
        <p style="color:#444;font-size:0.95rem;margin:0">Excerpt text...</p>
      </li>
    </ul>
  </main>
</div>
```

**Custom pages (`/page/{pageId}`):**

Same `<article>` wrapper as posts, containing the Pandoc-rendered page HTML.

**How React replaces it:** `createRoot(root).render(...)` replaces everything inside `<div id="root">`. No cleanup code needed. The transition is imperceptible because the Vite bundle is served from the same origin and cached after the first visit.

**Inline style rationale:** Minimal styles (max-width, margin, padding, font, line-height, color) prevent layout reflow during the brief moment before JS loads. They approximate the SPA's Tailwind layout proportions. No dark mode handling — the flash is imperceptible.

### 3. Data Preloading

To avoid double queries (backend renders server HTML from DB, then frontend fetches the same data via API), the backend embeds the API response as JSON:

```html
<script id="__initial_data__" type="application/json">{"posts":[...],"total":10,...}</script>
```

Injected before `</body>` alongside the server-rendered HTML.

**Frontend utility (`frontend/src/utils/preload.ts`):**

`readPreloadedData<T>(): T | null` — reads the script tag, parses JSON, removes the element (one-time read), returns the data or `null`.

**Integration with data fetching:**
- SWR hooks (`usePost`, `usePage`): pass preloaded data as `fallbackData`
- `useEffect`+`useState` pages (`TimelinePage`, `LabelPostsPage`): check for preloaded data in the effect, use as initial state if present, skip the fetch

On client-side navigations (user clicks a link), no preload tag exists, so these paths fetch from the API normally. The preload only affects the initial server-served page load.

### 4. Route Handlers

All registered before the StaticFiles catch-all mount in `main.py`. Each handler does a data lookup, builds an `SeoContext`, and calls `render_seo_html()`.

| Route | Data source | og:type | rendered_body | JSON-LD | Preload data |
|-------|------------|---------|---------------|---------|-------------|
| `/` | Site config + first page of posts from DB | `website` | Post list (titles, dates, excerpts, links) | `WebSite` | Post list response |
| `/post/{slug}` | PostCache DB lookup (existing, refactored) | `article` | Full `post.rendered_html` | `BlogPosting` | Post detail response |
| `/page/{pageId}` | PageCache DB lookup (pre-rendered) | `website` | Rendered page HTML | `WebPage` | Page response |
| `/labels` | Site config | `website` | None | None | None |
| `/labels/{labelId}` | Label DB + posts for label | `website` | Post list filtered to label | None | Label posts response |
| `/search` | No lookup | `website` | None | None | None |

**Canonical URLs:**
- `/post/{slug}` — resolved to canonical slug form (existing logic)
- `/page/{pageId}` — `/page/{pageId}`
- `/` — site root
- `/labels/{labelId}` — `/labels/{labelId}`
- `/search` — no canonical (query-dependent)

**Descriptions:**
- Posts: stripped rendered excerpt (existing logic)
- Pages: first 200 chars of stripped rendered HTML; falls back to site description for pages without a markdown file
- Homepage: site description from `index.toml`
- Labels index: `"Labels — {site_name}"`
- Label detail: `"Posts labeled {label_name} — {site_name}"`
- Search: `"Search — {site_name}"`

**Fallback behavior:** If any DB lookup fails or returns nothing (missing post, draft post, missing page), return plain `base_html` unchanged. The SPA handles 404s client-side.

**Refactoring the existing `post_route`:** The current ~80-line inline handler in `main.py` shrinks to ~20 lines: DB lookup, build `SeoContext`, call `render_seo_html()`. The asset-redirect logic at the top stays as-is.

### 5. JSON-LD Structured Data

Injected as `<script type="application/ld+json">` before `</head>`.

**Posts — `BlogPosting`:**

```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Post Title",
  "description": "Excerpt text...",
  "url": "https://example.com/post/my-post",
  "datePublished": "2026-03-28T12:00:00Z",
  "dateModified": "2026-03-28T14:00:00Z",
  "author": { "@type": "Person", "name": "Author Name" },
  "publisher": { "@type": "Organization", "name": "Site Name" }
}
```

**Pages — `WebPage`:**

```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "About",
  "description": "First 200 chars...",
  "url": "https://example.com/page/about"
}
```

**Homepage — `WebSite`:**

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "Site Name",
  "description": "Site description",
  "url": "https://example.com/"
}
```

Small helper functions (`blogposting_ld()`, `webpage_ld()`, `website_ld()`) build the dicts. Label and search pages get no JSON-LD.

### 6. Sitemap (`GET /sitemap.xml`)

Dynamic XML sitemap generated from the DB cache on each request.

Includes:
- Homepage (`/`)
- All custom pages with a markdown file (`/page/{id}`)
- All published (non-draft) posts (`/post/{slug}`) with `lastmod` from `modified_at`
- Label pages (`/labels/{labelId}`) for labels with at least one published post

Excludes: `/search`, `/login`, `/admin`, `/editor/*`, `/labels` index, `/labels/new`, `/labels/*/settings`, draft posts.

Response content type: `application/xml`.

### 7. Robots.txt (`GET /robots.txt`)

```
User-agent: *
Allow: /
Disallow: /api/
Disallow: /admin
Disallow: /editor/
Disallow: /login
Disallow: /labels/new
Disallow: /labels/*/settings

Sitemap: https://example.com/sitemap.xml
```

The `Sitemap:` URL is derived from the request's scheme and host so it works across environments.

Response content type: `text/plain`.

### 8. RSS Feed (`GET /feed.xml`)

RSS 2.0 feed of the 20 most recent published posts, ordered by `created_at` descending.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Site Name</title>
    <link>https://example.com/</link>
    <description>Site description</description>
    <atom:link href="https://example.com/feed.xml" rel="self" type="application/rss+xml"/>
    <item>
      <title>Post Title</title>
      <link>https://example.com/post/my-post</link>
      <guid isPermaLink="true">https://example.com/post/my-post</guid>
      <pubDate>Sat, 28 Mar 2026 12:00:00 +0000</pubDate>
      <description>Excerpt text...</description>
    </item>
  </channel>
</rss>
```

`<description>` uses the stripped excerpt. Response content type: `application/rss+xml`.

### 9. Frontend Changes

**Preloaded data utility (`frontend/src/utils/preload.ts`):**

`readPreloadedData<T>(): T | null` — reads and removes the `<script id="__initial_data__">` tag, returns parsed JSON or `null`. One-time read on initial page load.

**Hook integration:**
- `usePost`: accept preloaded data as SWR `fallbackData`
- `usePage`: same
- `TimelinePage`: check for preloaded data in the effect, use as initial state
- `LabelPostsPage`: same

**Dynamic `<title>` updates — each page component sets `document.title`:**
- Post: `"{post title} — {site name}"`
- Page: `"{page title} — {site name}"`
- Homepage: `"{site name}"`
- Label detail: `"{label name} — {site name}"`
- Labels index: `"Labels — {site name}"`
- Search: `"Search — {site name}"`

Small `useEffect` in each page component. No library needed.

**RSS autodiscovery in `frontend/index.html`:**

```html
<link rel="alternate" type="application/rss+xml" title="RSS Feed" href="/feed.xml">
```

Static addition to `<head>`.

## Deletions

- `backend/services/opengraph_service.py` — fully replaced by `seo_service.py`
- Existing `opengraph_service` tests — replaced by `seo_service` tests

## Testing

**SEO service unit tests:**
- `render_seo_html()` output for each injection type: title, meta description, canonical, OG tags, Twitter cards, JSON-LD, rendered body, preloaded data
- HTML escaping of special characters in all injected values
- Description truncation at 200 characters
- Partial context (missing optional fields) produces correct subset of tags
- `strip_html_tags()` edge cases

**Route handler integration tests (for each SEO-enabled route):**
- HTML response contains expected meta tags, structured data, rendered content, and preloaded JSON
- Fallback: missing post / draft post / missing page / missing label returns plain `base_html`
- Canonical URLs resolve correctly
- Asset redirect logic still works for `/post/{slug}` (existing behavior preserved)

**Sitemap tests:**
- Published posts, custom pages, and populated labels appear
- Drafts, admin routes, built-in pages without files do not appear
- Valid XML structure

**Robots.txt tests:**
- Disallow rules present for API, admin, editor, login
- Sitemap URL uses request scheme and host

**RSS feed tests:**
- Valid RSS 2.0 structure
- 20 most recent posts, ordered by created_at descending
- Drafts excluded
- Proper XML escaping of titles and excerpts

**Frontend preload tests:**
- `readPreloadedData` reads and removes the script tag
- Returns `null` on second call
- Returns `null` when no tag exists

## Files Changed

**New files:**
- `backend/services/seo_service.py`
- `frontend/src/utils/preload.ts`
- Tests for the above

**Modified files:**
- `backend/main.py` — refactor `post_route`, add new route handlers, add sitemap/robots/feed endpoints
- `frontend/index.html` — add RSS `<link rel="alternate">`
- `frontend/src/hooks/usePost.ts` — accept preloaded fallback data
- `frontend/src/hooks/usePage.ts` — accept preloaded fallback data
- `frontend/src/pages/TimelinePage.tsx` — preload integration, dynamic title
- `frontend/src/pages/LabelPostsPage.tsx` — preload integration, dynamic title
- `frontend/src/pages/PostPage.tsx` — preload integration, dynamic title
- `frontend/src/pages/PageViewPage.tsx` — preload integration, dynamic title
- `frontend/src/pages/LabelsPage.tsx` — dynamic title
- `frontend/src/pages/SearchPage.tsx` — dynamic title
- Existing opengraph tests → migrated to seo_service tests

**Deleted files:**
- `backend/services/opengraph_service.py`
