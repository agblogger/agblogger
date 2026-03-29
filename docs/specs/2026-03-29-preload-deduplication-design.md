# Preload Data Deduplication

## Problem

The SEO preloading system duplicates rendered HTML content. For each server-rendered page, the full `rendered_html` (post body or excerpt) appears twice: once in the server-rendered HTML inside `<div id="root">` and again in the `<script id="__initial_data__">` JSON blob. For long posts this roughly doubles the initial response size.

## Solution

Split the preloaded data into two sources:

- **Server HTML** carries all rendered HTML content, marked with extraction-friendly attributes (`data-content`, `data-id`, `data-excerpt`). The HTML stays complete for SEO crawlers and no-JS browsers.
- **Slim JSON** carries only structured metadata (ids, titles, dates, labels, pagination) with no HTML fields.

The SPA extracts HTML from the DOM and metadata from JSON, merging them into the same typed objects the hooks expect today.

## Backend Changes

### Server HTML marker elements

**Post detail** — wrap rendered body in `<div data-content>`:

```html
<article>
  <h1>Post Title</h1>
  <p style="...">March 15, 2026 · Author Name</p>
  <div data-content>{post.rendered_html}</div>
</article>
```

**Page detail** — same pattern:

```html
<article>
  <h1>Page Title</h1>
  <div data-content>{page.rendered_html}</div>
</article>
```

**List views (timeline, label posts)** — each item gets `data-id`, excerpt wrapped in `data-excerpt`:

```html
<ul>
  <li data-id="5">
    <a href="/post/foo">Post Title</a>
    <p>March 15, 2026</p>
    <div data-excerpt>{rendered_excerpt}</div>
  </li>
  ...
</ul>
```

### Slim JSON preload

The `__initial_data__` JSON drops all HTML content fields.

**Post detail** — no `rendered_html`:

```json
{
  "id": 5, "file_path": "posts/foo/post.md", "title": "Post Title",
  "subtitle": null, "author": "Author", "created_at": "...", "modified_at": "...",
  "is_draft": false, "labels": ["go", "rust"], "content": null, "warnings": []
}
```

**Page detail** — no `rendered_html`:

```json
{"id": "about", "title": "About"}
```

**Timeline** — posts without `rendered_excerpt`:

```json
{
  "posts": [
    {"id": 5, "file_path": "...", "title": "...", "subtitle": null,
     "author": "...", "created_at": "...", "modified_at": "...",
     "is_draft": false, "labels": ["go"]}
  ],
  "total": 42, "page": 1, "per_page": 10, "total_pages": 5
}
```

**Label posts** — same pattern: label metadata stays, post excerpts removed.

## Frontend Changes

### Implementation layer (low-level utilities in `utils/preload.ts`)

Three focused, independently testable utilities:

- **`readPreloadedMeta<T>()`** — reads and removes the `#__initial_data__` JSON tag. Returns parsed object or null. Essentially the existing `readPreloadedData` renamed.

- **`readPreloadedHtml(selector: string)`** — queries a CSS selector inside `#root`, returns its `innerHTML` or null. Does not remove the element (React mount handles that).

- **`readPreloadedHtmlMap(itemSelector: string, idAttr: string, contentSelector: string)`** — queries all elements matching `itemSelector` inside `#root`. For each, reads the id from the `idAttr` attribute and the HTML from the child matching `contentSelector`. Returns a `Map<string, string>` mapping id values to extracted innerHTML.

### Consumer layer (declarative API)

A single `readPreloaded<T>(spec)` function that calls the low-level utilities and merges results.

**Spec types:**

```ts
interface HtmlField {
  field: string       // target field name, e.g. 'rendered_html'
  selector: string    // CSS selector for content, e.g. '[data-content]'
}

interface ListHtmlField {
  path: string        // dot path to array in JSON, e.g. 'posts' or 'posts.posts'
  key: string         // JSON field to match against data-id, e.g. 'id'
  field: string       // target field per item, e.g. 'rendered_excerpt'
  selector: string    // CSS selector for content marker, e.g. '[data-excerpt]'
}

interface PreloadSpec {
  html?: HtmlField
  listHtml?: ListHtmlField
}
```

**Consumer call sites:**

```ts
// usePost.ts
const preloaded = readPreloaded<PostDetail>({
  html: { field: 'rendered_html', selector: '[data-content]' }
})

// usePage.ts
const preloaded = readPreloaded<PageResponse>({
  html: { field: 'rendered_html', selector: '[data-content]' }
})

// TimelinePage.tsx
const preloaded = readPreloaded<PostListResponse>({
  listHtml: { path: 'posts', key: 'id',
              field: 'rendered_excerpt', selector: '[data-excerpt]' }
})

// useLabelPosts.ts
const preloaded = readPreloaded<LabelPostsData>({
  listHtml: { path: 'posts.posts', key: 'id',
              field: 'rendered_excerpt', selector: '[data-excerpt]' }
})
```

## Testing

- **Backend:** Update SEO route tests to verify marker elements (`data-content`, `data-id`, `data-excerpt`) are present in server HTML, and that the JSON preload no longer contains HTML fields.
- **Frontend:** Update `preload.test.ts` to test all three low-level utilities and the declarative `readPreloaded` function — single HTML extraction, list HTML extraction with id matching, missing elements returning null, and the merge behavior.
- **Integration:** Existing Playwright/browser tests verify the SPA still renders correctly with the new preload flow.

## What doesn't change

- React still replaces server HTML on mount — no hydration changes.
- SWR hooks still receive preloaded data as `fallbackData` — same interface from the hook's perspective.
- Client-side navigations still fetch from the API normally.
- All server HTML content stays complete for crawlers and no-JS browsers (title, date, author, excerpts all remain).
- The `rendered_excerpt` and `rendered_html` fields in existing API response types are unchanged — only the preload source changes.
