# Preload Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplication of rendered HTML in server-side preloading by splitting preloaded data into slim JSON metadata and DOM-extracted HTML content.

**Architecture:** The backend changes server-rendered HTML to include `data-content`/`data-excerpt`/`data-id` marker elements and drops HTML fields from the JSON preload blob. The frontend gains a layered preload utility: low-level functions extract from JSON and DOM independently, and a declarative `readPreloaded<T>(spec)` merges both sources into the typed objects the SPA hooks already expect.

**Tech Stack:** Python/FastAPI (backend), TypeScript/React (frontend), Vitest (frontend tests), pytest (backend tests)

**Spec:** `docs/specs/2026-03-29-preload-deduplication-design.md`

---

### Task 1: Backend — Add `data-content` marker to post detail server HTML and drop `rendered_html` from post preload JSON

**Files:**
- Modify: `backend/main.py:890-917` (post_route rendered_body and preload_data)
- Modify: `tests/test_api/test_opengraph.py:176-179` (post preload assertion)
- Modify: `tests/test_api/test_seo_routes.py` (no direct changes needed, but verify tests still pass)
- Modify: `tests/test_services/test_seo_service.py` (no changes — tests use generic preload_data)

- [ ] **Step 1: Write failing test — post preload JSON must not contain `rendered_html`, server HTML must have `data-content` marker**

In `tests/test_api/test_opengraph.py`, update the existing `test_preload_data_present` test and add a new test:

```python
async def test_preload_data_present(self, client: AsyncClient) -> None:
    resp = await client.get("/post/hello")
    assert "__initial_data__" in resp.text
    assert '"rendered_html"' not in resp.text

async def test_rendered_body_has_data_content_marker(self, client: AsyncClient) -> None:
    resp = await client.get("/post/hello")
    assert "data-content" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_opengraph.py -v -k "test_preload_data_present or test_rendered_body_has_data_content"` (unsandboxed)

Expected: `test_preload_data_present` FAILS because current JSON contains `"rendered_html"`. `test_rendered_body_has_data_content_marker` FAILS because current HTML has no `data-content` attribute.

- [ ] **Step 3: Update post route — add `data-content` wrapper and slim down preload JSON**

In `backend/main.py`, in the `post_route` function (around line 890), change the rendered_body to wrap the post HTML content in a `<div data-content>` marker:

```python
        rendered_body = None
        if post.rendered_html:
            date_str = post.created_at.strftime("%B %-d, %Y")
            author_line = f" \u00b7 {post.author}" if post.author else ""
            rendered_body = (
                f"<article>"
                f"<h1>{html_mod.escape(post.title)}</h1>"
                f'<p style="color:#666;font-size:0.875rem;margin-bottom:2rem">'
                f"{html_mod.escape(date_str)}{html_mod.escape(author_line)}</p>"
                f"<div data-content>{post.rendered_html}</div>"
                f"</article>"
            )
```

And remove `rendered_html` and `rendered_excerpt` from `preload_data`:

```python
        preload_data = {
            "id": post.id,
            "file_path": post.file_path,
            "title": post.title,
            "subtitle": post.subtitle,
            "author": post.author,
            "created_at": published,
            "modified_at": modified,
            "is_draft": post.is_draft,
            "labels": label_ids,
            "content": None,
            "warnings": [],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_opengraph.py -v` (unsandboxed)

Expected: All tests pass.

- [ ] **Step 5: Run full backend test suite to check for regressions**

Run: `just test-backend` (unsandboxed)

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_api/test_opengraph.py
git commit -m "feat: add data-content marker to post HTML and slim post preload JSON"
```

---

### Task 2: Backend — Add `data-content` marker to page detail server HTML and drop `rendered_html` from page preload JSON

**Files:**
- Modify: `backend/main.py:1070-1080` (page_route rendered_body and preload_data)
- Modify: `tests/test_api/test_seo_routes.py:149-155` (page preload assertions)

- [ ] **Step 1: Write failing test — page preload JSON must not contain `rendered_html`, server HTML must have `data-content` marker**

In `tests/test_api/test_seo_routes.py`, update the `TestPageSeo` class:

```python
async def test_preload_data_present(self, client: AsyncClient) -> None:
    resp = await client.get("/page/about")
    assert "__initial_data__" in resp.text
    assert '"rendered_html"' not in resp.text

async def test_rendered_body_has_data_content_marker(self, client: AsyncClient) -> None:
    resp = await client.get("/page/about")
    assert "data-content" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestPageSeo -v -k "test_preload_data_present or test_rendered_body_has_data_content"` (unsandboxed)

Expected: Both FAIL.

- [ ] **Step 3: Update page route — add `data-content` wrapper and slim down preload JSON**

In `backend/main.py`, in the `page_route` function (around line 1070), wrap page content:

```python
        rendered_body = None
        if page.rendered_html:
            rendered_body = (
                f"<article><h1>{html_mod.escape(page.title)}</h1>"
                f"<div data-content>{page.rendered_html}</div></article>"
            )
```

And remove `rendered_html` from `preload_data`:

```python
        preload_data = {
            "id": page.id,
            "title": page.title,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestPageSeo -v` (unsandboxed)

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_seo_routes.py
git commit -m "feat: add data-content marker to page HTML and slim page preload JSON"
```

---

### Task 3: Backend — Add `data-id` and `data-excerpt` markers to `render_post_list_html` and drop `rendered_excerpt` from list preload JSON

**Files:**
- Modify: `backend/services/seo_service.py:153-182` (render_post_list_html)
- Modify: `backend/main.py:965-1010` (homepage_route preload_posts)
- Modify: `backend/main.py:1151-1210` (label_detail_route preload_posts_ld)
- Modify: `tests/test_services/test_seo_service.py:284-321` (TestRenderPostListHtml)
- Modify: `tests/test_api/test_seo_routes.py:121-123,210-212` (homepage and label preload assertions)

- [ ] **Step 1: Write failing test — `render_post_list_html` must include `data-id` and `data-excerpt` markers**

In `tests/test_services/test_seo_service.py`, update the `TestRenderPostListHtml` class. The function signature changes to accept `id` per post dict. Update existing tests and add new ones:

```python
class TestRenderPostListHtml:
    def test_renders_post_links(self) -> None:
        posts = [
            {"id": "1", "title": "First Post", "slug": "first", "date": "March 28, 2026", "excerpt": "Hello"},
            {"id": "2", "title": "Second Post", "slug": "second", "date": "March 27, 2026", "excerpt": "World"},
        ]
        result = render_post_list_html(posts, heading="My Blog")
        assert '<a href="/post/first"' in result
        assert "First Post" in result
        assert '<a href="/post/second"' in result
        assert "March 28, 2026" in result

    def test_renders_heading(self) -> None:
        result = render_post_list_html([], heading="My Blog")
        assert "<h1" in result
        assert "My Blog" in result

    def test_empty_list(self) -> None:
        result = render_post_list_html([], heading="Blog")
        assert "<ul" in result
        assert "<li" not in result

    def test_escapes_html_in_title(self) -> None:
        posts = [{"id": "1", "title": "<script>XSS</script>", "slug": "x", "date": "D", "excerpt": "E"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "<script>" not in result

    def test_escapes_html_in_excerpt(self) -> None:
        posts = [{"id": "1", "title": "T", "slug": "x", "date": "D", "excerpt": "<img onerror=alert(1)>"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "onerror" not in result

    def test_includes_data_id_attribute(self) -> None:
        posts = [{"id": "42", "title": "T", "slug": "s", "date": "D", "excerpt": "E"}]
        result = render_post_list_html(posts, heading="Blog")
        assert 'data-id="42"' in result

    def test_includes_data_excerpt_marker(self) -> None:
        posts = [{"id": "1", "title": "T", "slug": "s", "date": "D", "excerpt": "My excerpt text"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "data-excerpt" in result
        assert "My excerpt text" in result
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestRenderPostListHtml -v` (unsandboxed)

Expected: `test_includes_data_id_attribute` and `test_includes_data_excerpt_marker` FAIL. Existing tests may also fail because the post dicts now include `"id"` which the current function doesn't use (but dict access won't break — they'll pass unless the function rejects unknown keys). Actually the existing tests will also fail because they don't have the `"id"` key — update them first in step 1.

- [ ] **Step 3: Update `render_post_list_html` to include `data-id` and `data-excerpt` markers**

In `backend/services/seo_service.py`, update the function. The post dict now requires an `id` key:

```python
def render_post_list_html(
    posts: list[dict[str, str]],
    *,
    heading: str,
) -> str:
    """Render a simple HTML post list for server-side pre-rendering.

    Each post dict must have keys: id, title, slug, date, excerpt.
    """
    esc_heading = html.escape(heading)
    items = []
    for post in posts:
        esc_id = html.escape(str(post["id"]))
        esc_title = html.escape(strip_html_tags(post["title"]))
        esc_slug = html.escape(post["slug"])
        esc_date = html.escape(post["date"])
        esc_excerpt = html.escape(strip_html_tags(post["excerpt"]))
        items.append(
            f'<li data-id="{esc_id}" style="margin-bottom:1.5rem">'
            f'<a href="/post/{esc_slug}" style="font-size:1.25rem;color:#1a1a1a;'
            f'text-decoration:none">{esc_title}</a>'
            f'<p style="color:#666;font-size:0.875rem;margin:0.25rem 0">{esc_date}</p>'
            f'<div data-excerpt><p style="color:#444;font-size:0.95rem;margin:0">'
            f"{esc_excerpt}</p></div>"
            f"</li>"
        )
    list_html = "\n".join(items)
    return (
        f'<h1 style="font-size:2.25rem;line-height:1.2;margin-bottom:1.5rem">{esc_heading}</h1>'
        f'<ul style="list-style:none;padding:0">{list_html}</ul>'
    )
```

- [ ] **Step 4: Update homepage route to pass `id` in posts_data and drop `rendered_excerpt` from preload_posts**

In `backend/main.py`, in the `homepage_route` function (around line 985-1010):

Update posts_data to include `"id"`:

```python
                    posts_data.append(
                        {
                            "id": str(p.id),
                            "title": p.title,
                            "slug": slug,
                            "date": p.created_at.strftime("%B %-d, %Y"),
                            "excerpt": excerpt,
                        }
                    )
```

Remove `rendered_excerpt` from preload_posts:

```python
                    preload_posts.append(
                        {
                            "id": p.id,
                            "file_path": p.file_path,
                            "title": p.title,
                            "subtitle": p.subtitle,
                            "author": p.author,
                            "created_at": format_iso(p.created_at),
                            "modified_at": format_iso(p.modified_at),
                            "is_draft": p.is_draft,
                            "labels": [pl.label_id for pl in p.labels],
                        }
                    )
```

- [ ] **Step 5: Update label detail route to pass `id` in posts_data_ld and drop `rendered_excerpt` from preload_posts_ld**

In `backend/main.py`, in the `label_detail_route` function (around line 1189-1210):

Update posts_data_ld to include `"id"`:

```python
                        posts_data_ld.append(
                            {
                                "id": str(p.id),
                                "title": p.title,
                                "slug": slug,
                                "date": p.created_at.strftime("%B %-d, %Y"),
                                "excerpt": excerpt,
                            }
                        )
```

Remove `rendered_excerpt` from preload_posts_ld:

```python
                        preload_posts_ld.append(
                            {
                                "id": p.id,
                                "file_path": p.file_path,
                                "title": p.title,
                                "subtitle": p.subtitle,
                                "author": p.author,
                                "created_at": format_iso(p.created_at),
                                "modified_at": format_iso(p.modified_at),
                                "is_draft": p.is_draft,
                                "labels": [pl.label_id for pl in p.labels],
                            }
                        )
```

- [ ] **Step 6: Update SEO route integration tests for homepage and label detail**

In `tests/test_api/test_seo_routes.py`:

Update `TestHomepageSeo.test_preload_data_present`:

```python
async def test_preload_data_present(self, client: AsyncClient) -> None:
    resp = await client.get("/")
    assert "__initial_data__" in resp.text
    assert '"rendered_excerpt"' not in resp.text
```

Add `test_rendered_list_has_data_id_markers` to `TestHomepageSeo`:

```python
async def test_rendered_list_has_data_id_markers(self, client: AsyncClient) -> None:
    resp = await client.get("/")
    assert "data-id" in resp.text
    assert "data-excerpt" in resp.text
```

Update `TestLabelDetailSeo.test_preload_data_present`:

```python
async def test_preload_data_present(self, client: AsyncClient) -> None:
    resp = await client.get("/labels/python")
    assert "__initial_data__" in resp.text
    assert '"rendered_excerpt"' not in resp.text
```

Add `test_rendered_list_has_data_id_markers` to `TestLabelDetailSeo`:

```python
async def test_rendered_list_has_data_id_markers(self, client: AsyncClient) -> None:
    resp = await client.get("/labels/python")
    assert "data-id" in resp.text
    assert "data-excerpt" in resp.text
```

- [ ] **Step 7: Run all backend tests**

Run: `just test-backend` (unsandboxed)

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add backend/services/seo_service.py backend/main.py tests/test_services/test_seo_service.py tests/test_api/test_seo_routes.py
git commit -m "feat: add data-id/data-excerpt markers to list HTML and slim list preload JSON"
```

---

### Task 4: Frontend — Implement low-level preload utilities and tests

**Files:**
- Modify: `frontend/src/utils/preload.ts` (rewrite with three low-level utilities)
- Modify: `frontend/src/utils/__tests__/preload.test.ts` (rewrite tests for new utilities)

- [ ] **Step 1: Write failing tests for the three low-level utilities**

Replace the contents of `frontend/src/utils/__tests__/preload.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { readPreloadedMeta, readPreloadedHtml, readPreloadedHtmlMap } from '@/utils/preload'

describe('readPreloadedMeta', () => {
  beforeEach(() => {
    document.getElementById('__initial_data__')?.remove()
  })

  it('returns null when no script tag exists', () => {
    expect(readPreloadedMeta()).toBeNull()
  })

  it('reads and parses JSON from script tag', () => {
    const data = { id: 1, title: 'Hello' }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(data)
    document.body.appendChild(script)

    const result = readPreloadedMeta()
    expect(result).toEqual(data)
  })

  it('removes the script tag after reading', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedMeta()
    expect(document.getElementById('__initial_data__')).toBeNull()
  })

  it('returns null on second call', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedMeta()
    expect(readPreloadedMeta()).toBeNull()
  })

  it('returns null for invalid JSON', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = 'not valid json'
    document.body.appendChild(script)

    expect(readPreloadedMeta()).toBeNull()
  })
})

describe('readPreloadedHtml', () => {
  beforeEach(() => {
    const root = document.getElementById('root')
    if (root) root.innerHTML = ''
    else {
      const div = document.createElement('div')
      div.id = 'root'
      document.body.appendChild(div)
    }
  })

  it('returns null when selector matches nothing', () => {
    expect(readPreloadedHtml('[data-content]')).toBeNull()
  })

  it('extracts innerHTML from matched element inside root', () => {
    const root = document.getElementById('root')!
    root.innerHTML = '<article><h1>Title</h1><div data-content><p>Body</p></div></article>'

    const result = readPreloadedHtml('[data-content]')
    expect(result).toBe('<p>Body</p>')
  })

  it('does not match elements outside root', () => {
    document.body.insertAdjacentHTML('beforeend', '<div data-content><p>Outside</p></div>')

    const result = readPreloadedHtml('[data-content]')
    expect(result).toBeNull()

    document.body.querySelector('[data-content]')?.remove()
  })
})

describe('readPreloadedHtmlMap', () => {
  beforeEach(() => {
    const root = document.getElementById('root')
    if (root) root.innerHTML = ''
    else {
      const div = document.createElement('div')
      div.id = 'root'
      document.body.appendChild(div)
    }
  })

  it('returns empty map when no items match', () => {
    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(0)
  })

  it('extracts id-keyed map of content HTML', () => {
    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><a>Post One</a><div data-excerpt><p>Excerpt one</p></div></li>' +
      '<li data-id="2"><a>Post Two</a><div data-excerpt><p>Excerpt two</p></div></li>' +
      '</ul>'

    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(2)
    expect(result.get('1')).toBe('<p>Excerpt one</p>')
    expect(result.get('2')).toBe('<p>Excerpt two</p>')
  })

  it('skips items missing content selector', () => {
    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><a>Post One</a><div data-excerpt><p>Excerpt</p></div></li>' +
      '<li data-id="2"><a>Post Two</a></li>' +
      '</ul>'

    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(1)
    expect(result.get('1')).toBe('<p>Excerpt</p>')
  })

  it('skips items missing id attribute', () => {
    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><div data-excerpt><p>One</p></div></li>' +
      '<li><div data-excerpt><p>No id</p></div></li>' +
      '</ul>'

    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(1)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend -- --run frontend/src/utils/__tests__/preload.test.ts` (unsandboxed)

Expected: FAIL — `readPreloadedMeta`, `readPreloadedHtml`, `readPreloadedHtmlMap` are not exported.

- [ ] **Step 3: Implement the three low-level utilities**

Replace the contents of `frontend/src/utils/preload.ts`:

```typescript
/** Read and remove the server-injected preload metadata JSON. One-time read. */
export function readPreloadedMeta<T>(): T | null {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null

  const raw = el.textContent
  el.remove()
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

/** Extract innerHTML from a single element matching `selector` inside #root. */
export function readPreloadedHtml(selector: string): string | null {
  const root = document.getElementById('root')
  if (root === null) return null

  const el = root.querySelector(selector)
  if (el === null) return null

  return el.innerHTML
}

/**
 * Extract an id-keyed map of innerHTML from list items inside #root.
 *
 * Queries all elements matching `itemSelector`, reads the id from `idAttr`,
 * and extracts innerHTML from the child matching `contentSelector`.
 */
export function readPreloadedHtmlMap(
  itemSelector: string,
  idAttr: string,
  contentSelector: string,
): Map<string, string> {
  const result = new Map<string, string>()
  const root = document.getElementById('root')
  if (root === null) return result

  const items = root.querySelectorAll(itemSelector)
  for (const item of items) {
    const id = item.getAttribute(idAttr)
    if (id === null) continue

    const contentEl = item.querySelector(contentSelector)
    if (contentEl === null) continue

    result.set(id, contentEl.innerHTML)
  }

  return result
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend -- --run frontend/src/utils/__tests__/preload.test.ts` (unsandboxed)

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/preload.ts frontend/src/utils/__tests__/preload.test.ts
git commit -m "feat: implement low-level preload extraction utilities"
```

---

### Task 5: Frontend — Implement declarative `readPreloaded<T>(spec)` consumer API and tests

**Files:**
- Modify: `frontend/src/utils/preload.ts` (add readPreloaded function and spec types)
- Modify: `frontend/src/utils/__tests__/preload.test.ts` (add readPreloaded tests)

- [ ] **Step 1: Write failing tests for `readPreloaded`**

Append to `frontend/src/utils/__tests__/preload.test.ts`:

```typescript
import { readPreloaded } from '@/utils/preload'

describe('readPreloaded', () => {
  beforeEach(() => {
    document.getElementById('__initial_data__')?.remove()
    const root = document.getElementById('root')
    if (root) root.innerHTML = ''
    else {
      const div = document.createElement('div')
      div.id = 'root'
      document.body.appendChild(div)
    }
  })

  it('returns null when no JSON tag exists', () => {
    expect(readPreloaded({})).toBeNull()
  })

  it('merges single HTML field from DOM into metadata', () => {
    const meta = { id: 1, title: 'Post' }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(meta)
    document.body.appendChild(script)

    const root = document.getElementById('root')!
    root.innerHTML = '<article><h1>Post</h1><div data-content><p>Body HTML</p></div></article>'

    const result = readPreloaded<{ id: number; title: string; rendered_html: string }>({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })

    expect(result).toEqual({ id: 1, title: 'Post', rendered_html: '<p>Body HTML</p>' })
  })

  it('sets HTML field to empty string when DOM element not found', () => {
    const meta = { id: 1, title: 'Post' }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(meta)
    document.body.appendChild(script)

    const result = readPreloaded<{ id: number; title: string; rendered_html: string }>({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })

    expect(result).toEqual({ id: 1, title: 'Post', rendered_html: '' })
  })

  it('merges list HTML fields into nested array items', () => {
    const meta = {
      posts: [
        { id: 1, title: 'First' },
        { id: 2, title: 'Second' },
      ],
      total: 2,
    }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(meta)
    document.body.appendChild(script)

    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><div data-excerpt><p>Excerpt one</p></div></li>' +
      '<li data-id="2"><div data-excerpt><p>Excerpt two</p></div></li>' +
      '</ul>'

    const result = readPreloaded<{
      posts: { id: number; title: string; rendered_excerpt: string }[]
      total: number
    }>({
      listHtml: {
        path: 'posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })

    expect(result).toEqual({
      posts: [
        { id: 1, title: 'First', rendered_excerpt: '<p>Excerpt one</p>' },
        { id: 2, title: 'Second', rendered_excerpt: '<p>Excerpt two</p>' },
      ],
      total: 2,
    })
  })

  it('handles dot-path traversal for nested arrays', () => {
    const meta = {
      label: { id: 'python', names: ['Python'] },
      posts: {
        posts: [
          { id: 1, title: 'First' },
          { id: 2, title: 'Second' },
        ],
        total: 2,
      },
    }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(meta)
    document.body.appendChild(script)

    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><div data-excerpt><p>One</p></div></li>' +
      '<li data-id="2"><div data-excerpt><p>Two</p></div></li>' +
      '</ul>'

    const result = readPreloaded<{
      label: { id: string; names: string[] }
      posts: {
        posts: { id: number; title: string; rendered_excerpt: string }[]
        total: number
      }
    }>({
      listHtml: {
        path: 'posts.posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })

    expect(result!.posts.posts[0].rendered_excerpt).toBe('<p>One</p>')
    expect(result!.posts.posts[1].rendered_excerpt).toBe('<p>Two</p>')
    expect(result!.label.id).toBe('python')
  })

  it('sets empty string for list items with no matching DOM element', () => {
    const meta = {
      posts: [
        { id: 1, title: 'First' },
        { id: 3, title: 'No DOM match' },
      ],
      total: 2,
    }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(meta)
    document.body.appendChild(script)

    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul><li data-id="1"><div data-excerpt><p>One</p></div></li></ul>'

    const result = readPreloaded<{
      posts: { id: number; title: string; rendered_excerpt: string }[]
      total: number
    }>({
      listHtml: {
        path: 'posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })

    expect(result!.posts[0].rendered_excerpt).toBe('<p>One</p>')
    expect(result!.posts[1].rendered_excerpt).toBe('')
  })

  it('returns plain metadata when no spec fields are set', () => {
    const meta = { id: 1, title: 'Post' }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(meta)
    document.body.appendChild(script)

    const result = readPreloaded<{ id: number; title: string }>({})
    expect(result).toEqual({ id: 1, title: 'Post' })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend -- --run frontend/src/utils/__tests__/preload.test.ts` (unsandboxed)

Expected: FAIL — `readPreloaded` is not exported.

- [ ] **Step 3: Implement `readPreloaded` and the spec types**

Append to `frontend/src/utils/preload.ts`:

```typescript
export interface HtmlField {
  field: string
  selector: string
}

export interface ListHtmlField {
  path: string
  key: string
  field: string
  itemSelector: string
  contentSelector: string
}

export interface PreloadSpec {
  html?: HtmlField
  listHtml?: ListHtmlField
}

/** Declarative preload reader: reads slim JSON metadata and merges HTML extracted from the DOM. */
export function readPreloaded<T>(spec: PreloadSpec): T | null {
  const meta = readPreloadedMeta<Record<string, unknown>>()
  if (meta === null) return null

  if (spec.html !== undefined) {
    const html = readPreloadedHtml(spec.html.selector)
    ;(meta as Record<string, unknown>)[spec.html.field] = html ?? ''
  }

  if (spec.listHtml !== undefined) {
    const { path, key, field, itemSelector, contentSelector } = spec.listHtml
    const idAttr = itemSelector.replace(/^\[|\]$/g, '')
    const htmlMap = readPreloadedHtmlMap(itemSelector, idAttr, contentSelector)

    const segments = path.split('.')
    let target: unknown = meta
    for (const segment of segments) {
      target = (target as Record<string, unknown>)[segment]
    }

    if (Array.isArray(target)) {
      for (const item of target) {
        const record = item as Record<string, unknown>
        const itemId = String(record[key])
        record[field] = htmlMap.get(itemId) ?? ''
      }
    }
  }

  return meta as T
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend -- --run frontend/src/utils/__tests__/preload.test.ts` (unsandboxed)

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/preload.ts frontend/src/utils/__tests__/preload.test.ts
git commit -m "feat: implement declarative readPreloaded consumer API"
```

---

### Task 6: Frontend — Migrate consumers to use `readPreloaded`

**Files:**
- Modify: `frontend/src/hooks/usePost.ts` (switch to readPreloaded)
- Modify: `frontend/src/hooks/usePage.ts` (switch to readPreloaded)
- Modify: `frontend/src/pages/TimelinePage.tsx` (switch to readPreloaded)
- Modify: `frontend/src/hooks/useLabelPosts.ts` (switch to readPreloaded)

- [ ] **Step 1: Migrate `usePost.ts`**

Replace the contents of `frontend/src/hooks/usePost.ts`:

```typescript
import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

const preloaded = readPreloaded<PostDetail>({
  html: { field: 'rendered_html', selector: '[data-content]' },
})

export function usePost(slug: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<PostDetail, Error>(
    slug !== null ? ['post', slug, userId] : null,
    ([, s]: [string, string, number | null]) => fetchPost(s),
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}

export function useViewCount(slug: string | null) {
  return useSWR<ViewCountResponse, Error>(
    slug !== null ? ['viewCount', slug] : null,
    ([, s]: [string, string]) => fetchViewCount(s),
  )
}
```

- [ ] **Step 2: Migrate `usePage.ts`**

Replace the contents of `frontend/src/hooks/usePage.ts`:

```typescript
import useSWR from 'swr'
import type { PageResponse } from '@/api/client'
import { readPreloaded } from '@/utils/preload'

const preloaded = readPreloaded<PageResponse>({
  html: { field: 'rendered_html', selector: '[data-content]' },
})

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  return useSWR<PageResponse, Error>(
    pageId !== null ? `pages/${pageId}` : null,
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}
```

- [ ] **Step 3: Migrate `TimelinePage.tsx`**

In `frontend/src/pages/TimelinePage.tsx`, change the import and preload call at the top of the file.

Replace:

```typescript
import { readPreloadedData } from '@/utils/preload'

let preloadedTimeline = readPreloadedData<PostListResponse>()
```

With:

```typescript
import { readPreloaded } from '@/utils/preload'

let preloadedTimeline = readPreloaded<PostListResponse>({
  listHtml: { path: 'posts', key: 'id', field: 'rendered_excerpt',
              itemSelector: '[data-id]', contentSelector: '[data-excerpt]' },
})
```

- [ ] **Step 4: Migrate `useLabelPosts.ts`**

Replace the contents of `frontend/src/hooks/useLabelPosts.ts`:

```typescript
import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

const preloaded = readPreloaded<LabelPostsData>({
  listHtml: {
    path: 'posts.posts',
    key: 'id',
    field: 'rendered_excerpt',
    itemSelector: '[data-id]',
    contentSelector: '[data-excerpt]',
  },
})

export function useLabelPosts(labelId: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<LabelPostsData, Error>(
    labelId !== null ? ['labelPosts', labelId, userId] : null,
    async ([, id]: [string, string, number | null]) => {
      const [label, posts] = await Promise.all([fetchLabel(id), fetchLabelPosts(id)])
      return { label, posts }
    },
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}
```

- [ ] **Step 5: Run frontend tests**

Run: `just test-frontend` (unsandboxed)

Expected: All pass. The hook tests mock the API layer, not the preload utility, so they should work unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/usePost.ts frontend/src/hooks/usePage.ts frontend/src/pages/TimelinePage.tsx frontend/src/hooks/useLabelPosts.ts
git commit -m "feat: migrate preload consumers to declarative readPreloaded API"
```

---

### Task 7: Remove legacy `readPreloadedData` and run full check

**Files:**
- Modify: `frontend/src/utils/preload.ts` (remove readPreloadedData if still present — it was replaced in Task 4)
- Verify: no remaining imports of `readPreloadedData`

- [ ] **Step 1: Verify no remaining references to `readPreloadedData`**

Search the codebase for any remaining imports or usages of `readPreloadedData`. If Task 4 replaced the file contents, there should be none. But verify.

Run: `grep -r "readPreloadedData" frontend/src/ --include="*.ts" --include="*.tsx"` (or use the Grep tool)

Expected: No matches.

- [ ] **Step 2: Run full check**

Run: `just check` (unsandboxed)

Expected: All static checks and tests pass.

- [ ] **Step 3: Commit (if any cleanup was needed)**

If any cleanup was needed, commit:

```bash
git add -A
git commit -m "refactor: remove legacy readPreloadedData references"
```

---

### Task 8: Update architecture docs

**Files:**
- Modify: `docs/arch/frontend.md` (update Server-Side Preloading section)
- Modify: `docs/arch/backend.md` (update SEO and Server-Side Enrichment section if needed)

- [ ] **Step 1: Update `docs/arch/frontend.md`**

Update the "Server-Side Preloading" section to reflect the new two-source architecture:

```markdown
## Server-Side Preloading

On the initial page load, the backend embeds pre-rendered HTML inside `<div id="root">` and slim structured metadata as a JSON script tag. HTML content is marked with `data-content` (single-resource pages) and `data-id`/`data-excerpt` (list views) attributes for extraction. The SPA reads metadata from the JSON tag and HTML from the DOM via a declarative preload utility, then merges them into typed objects. This avoids duplicating rendered HTML across both sources. React replaces the server HTML on mount; client-side navigations fetch from the API normally.
```

Update the code entry points line for preload.ts:

```markdown
- `frontend/src/utils/preload.ts` provides the layered preload system: low-level `readPreloadedMeta`, `readPreloadedHtml`, and `readPreloadedHtmlMap` utilities, plus the declarative `readPreloaded<T>(spec)` consumer API for merging server-injected JSON metadata with DOM-extracted HTML content.
```

- [ ] **Step 2: Verify `docs/arch/backend.md` is still accurate**

The "SEO and Server-Side Enrichment" section in `docs/arch/backend.md` says: "Each handler enriches the SPA shell with meta tags, structured data, server-rendered content, and preloaded API data". This is still accurate — the preloaded data is just slimmer now. No change needed.

- [ ] **Step 3: Commit**

```bash
git add docs/arch/frontend.md
git commit -m "docs: update frontend arch for preload deduplication"
```
