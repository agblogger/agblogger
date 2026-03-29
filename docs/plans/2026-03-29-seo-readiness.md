# SEO Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgBlogger SEO-ready by adding server-rendered content, meta tags, structured data, sitemap, robots.txt, RSS feed, and data preloading across all public routes.

**Architecture:** A shared `SeoContext` dataclass + `render_seo_html()` function replaces the existing `opengraph_service.py`. Six route handlers (registered before StaticFiles) each build an `SeoContext` from a quick DB/service lookup and call the shared renderer. The frontend reads preloaded JSON from a `<script>` tag to skip the initial API fetch.

**Tech Stack:** FastAPI (backend routes), SQLAlchemy (DB queries), Pandoc (page rendering), React/SWR/Zustand (frontend), Vitest (frontend tests), pytest (backend tests)

**Spec:** `docs/specs/2026-03-29-seo-readiness-design.md`

---

## File Map

**New files:**
- `backend/services/seo_service.py` — `SeoContext` dataclass, `render_seo_html()`, JSON-LD helpers, `strip_html_tags()`
- `tests/test_services/test_seo_service.py` — unit tests for the SEO service
- `tests/test_api/test_seo_routes.py` — integration tests for all SEO-enriched routes
- `tests/test_api/test_sitemap.py` — sitemap endpoint tests
- `tests/test_api/test_robots.py` — robots.txt endpoint tests
- `tests/test_api/test_feed.py` — RSS feed endpoint tests
- `frontend/src/utils/preload.ts` — `readPreloadedData<T>()` utility
- `frontend/src/utils/__tests__/preload.test.ts` — tests for preload utility

**Modified files:**
- `backend/main.py` — refactor `post_route`, add 5 new route handlers, add sitemap/robots/feed endpoints
- `frontend/index.html` — add RSS `<link rel="alternate">`
- `frontend/src/hooks/usePost.ts` — accept preloaded fallback data
- `frontend/src/hooks/usePage.ts` — accept preloaded fallback data
- `frontend/src/hooks/useLabelPosts.ts` — accept preloaded fallback data
- `frontend/src/pages/TimelinePage.tsx` — preload integration, dynamic title
- `frontend/src/pages/PostPage.tsx` — preload integration, dynamic title
- `frontend/src/pages/PageViewPage.tsx` — preload integration, dynamic title
- `frontend/src/pages/LabelPostsPage.tsx` — preload integration, dynamic title
- `frontend/src/pages/LabelsPage.tsx` — dynamic title
- `frontend/src/pages/SearchPage.tsx` — dynamic title

**Deleted files:**
- `backend/services/opengraph_service.py`
- `tests/test_services/test_opengraph_service.py`
- `tests/test_api/test_opengraph.py`

---

### Task 1: SEO Service — `strip_html_tags` and `render_seo_html` Core

**Files:**
- Create: `backend/services/seo_service.py`
- Create: `tests/test_services/test_seo_service.py`

- [ ] **Step 1: Write failing tests for `strip_html_tags`**

Port existing tests from `tests/test_services/test_opengraph_service.py::TestStripHtmlTags` — the function is identical, just re-homed. Create the new test file:

```python
"""Tests for the SEO service."""

from __future__ import annotations

from backend.services.seo_service import strip_html_tags


class TestStripHtmlTags:
    def test_strips_basic_tags(self) -> None:
        assert strip_html_tags("<p>Hello</p>") == "Hello"

    def test_strips_nested_tags(self) -> None:
        assert strip_html_tags("<div><p>Hello <b>World</b></p></div>") == "Hello World"

    def test_strips_self_closing_tags(self) -> None:
        assert strip_html_tags("Hello<br/>World") == "Hello World"

    def test_decodes_html_entities(self) -> None:
        assert strip_html_tags("&amp; &lt; &gt; &quot;") == '& < > "'

    def test_decodes_numeric_entities(self) -> None:
        assert strip_html_tags("&#169; &#x27;") == "\u00a9 '"

    def test_empty_string(self) -> None:
        assert strip_html_tags("") == ""

    def test_plain_text_unchanged(self) -> None:
        assert strip_html_tags("Hello World") == "Hello World"

    def test_collapses_whitespace(self) -> None:
        assert strip_html_tags("Hello   \n\t  World") == "Hello World"

    def test_collapses_whitespace_from_tags(self) -> None:
        assert strip_html_tags("<p>Hello</p>  <p>World</p>") == "Hello World"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert strip_html_tags("  <p>Hello</p>  ") == "Hello"

    def test_tags_with_attributes(self) -> None:
        assert strip_html_tags('<a href="http://example.com">link</a>') == "link"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestStripHtmlTags -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.seo_service'`

- [ ] **Step 3: Write failing tests for `SeoContext` and `render_seo_html`**

Add to `tests/test_services/test_seo_service.py`:

```python
from backend.services.seo_service import SeoContext, render_seo_html

BASE_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Blog</title>
</head>
<body><div id="root"></div></body>
</html>"""


def _make_ctx(**overrides: Any) -> SeoContext:
    defaults: dict[str, Any] = {
        "title": "My Post",
        "description": "A description",
        "canonical_url": "https://example.com/post/my-post",
    }
    defaults.update(overrides)
    return SeoContext(**defaults)


class TestRenderSeoHtml:
    def test_replaces_title_tag(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title="Hello"))
        assert "<title>Hello</title>" in result
        assert "<title>Blog</title>" not in result

    def test_injects_meta_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description="My desc"))
        assert '<meta name="description" content="My desc">' in result

    def test_injects_canonical_link(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(canonical_url="https://example.com/post/x")
        )
        assert '<link rel="canonical" href="https://example.com/post/x">' in result

    def test_injects_og_title(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title="My Post"))
        assert '<meta property="og:title" content="My Post">' in result

    def test_injects_og_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description="Desc"))
        assert '<meta property="og:description" content="Desc">' in result

    def test_injects_og_url(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(canonical_url="https://example.com/post/x")
        )
        assert '<meta property="og:url" content="https://example.com/post/x">' in result

    def test_og_type_defaults_to_website(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert '<meta property="og:type" content="website">' in result

    def test_og_type_article(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(og_type="article"))
        assert '<meta property="og:type" content="article">' in result

    def test_injects_twitter_card(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert '<meta name="twitter:card" content="summary">' in result

    def test_injects_twitter_title(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title="TT"))
        assert '<meta name="twitter:title" content="TT">' in result

    def test_injects_twitter_description(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(description="TD"))
        assert '<meta name="twitter:description" content="TD">' in result

    def test_includes_site_name_when_provided(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(site_name="My Blog"))
        assert '<meta property="og:site_name" content="My Blog">' in result

    def test_omits_site_name_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(site_name=None))
        assert "og:site_name" not in result

    def test_includes_author_when_provided(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(author="Jane"))
        assert '<meta property="article:author" content="Jane">' in result

    def test_omits_author_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(author=None))
        assert "article:author" not in result

    def test_includes_published_time(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(published_time="2026-01-15T10:30:00+00:00")
        )
        assert 'article:published_time" content="2026-01-15T10:30:00+00:00"' in result

    def test_includes_modified_time(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(modified_time="2026-02-20T14:00:00+00:00")
        )
        assert 'article:modified_time" content="2026-02-20T14:00:00+00:00"' in result

    def test_omits_published_time_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert "article:published_time" not in result

    def test_escapes_html_in_title(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(title='<script>alert("xss")</script>'))
        assert "<script>" not in result

    def test_escapes_html_in_description(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(description='<img src=x onerror="alert(1)">')
        )
        assert 'onerror="alert(1)"' not in result

    def test_truncates_long_description(self) -> None:
        long_desc = "a" * 300
        result = render_seo_html(BASE_HTML, _make_ctx(description=long_desc))
        assert "a" * 197 + "..." in result
        assert "a" * 198 + "..." not in result

    def test_does_not_truncate_200_char_description(self) -> None:
        desc = "a" * 200
        result = render_seo_html(BASE_HTML, _make_ctx(description=desc))
        assert desc in result
        assert desc + "..." not in result

    def test_tags_inserted_before_head_close(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        head_close_pos = result.index("</head>")
        og_title_pos = result.index("og:title")
        assert og_title_pos < head_close_pos

    def test_preserves_rest_of_html(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx())
        assert '<meta charset="utf-8">' in result
        assert "<!DOCTYPE html>" in result
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `just test-backend -- tests/test_services/test_seo_service.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 5: Implement `seo_service.py` — `strip_html_tags`, `SeoContext`, `render_seo_html`**

Create `backend/services/seo_service.py`:

```python
"""SEO enrichment service: meta tags, structured data, and pre-rendered content injection."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

_MAX_DESCRIPTION_LENGTH = 200

_PRE_RENDER_STYLE = (
    "max-width:42rem;margin:0 auto;padding:2rem 1rem;"
    "font-family:system-ui,sans-serif;line-height:1.7;color:#1a1a1a"
)


def strip_html_tags(text: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class SeoContext:
    """All SEO metadata for a single page response."""

    title: str
    description: str
    canonical_url: str
    og_type: str = "website"
    site_name: str | None = None
    author: str | None = None
    published_time: str | None = None
    modified_time: str | None = None
    json_ld: dict[str, Any] | None = None
    rendered_body: str | None = None
    preload_data: dict[str, Any] | None = None


def render_seo_html(base_html: str, ctx: SeoContext) -> str:
    """Inject SEO meta tags, structured data, and pre-rendered content into base HTML."""
    description = ctx.description
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        description = description[: _MAX_DESCRIPTION_LENGTH - 3] + "..."

    esc_title = html.escape(ctx.title)
    esc_desc = html.escape(description)
    esc_url = html.escape(ctx.canonical_url)

    # Head tags: meta description, canonical, OG, Twitter Cards
    head_tags = [
        f'<meta name="description" content="{esc_desc}">',
        f'<link rel="canonical" href="{esc_url}">',
        f'<meta property="og:title" content="{esc_title}">',
        f'<meta property="og:description" content="{esc_desc}">',
        f'<meta property="og:url" content="{esc_url}">',
        f'<meta property="og:type" content="{html.escape(ctx.og_type)}">',
        '<meta name="twitter:card" content="summary">',
        f'<meta name="twitter:title" content="{esc_title}">',
        f'<meta name="twitter:description" content="{esc_desc}">',
    ]

    if ctx.site_name:
        head_tags.append(
            f'<meta property="og:site_name" content="{html.escape(ctx.site_name)}">'
        )
    if ctx.author is not None:
        head_tags.append(
            f'<meta property="article:author" content="{html.escape(ctx.author)}">'
        )
    if ctx.published_time is not None:
        head_tags.append(
            f'<meta property="article:published_time" content="{html.escape(ctx.published_time)}">'
        )
    if ctx.modified_time is not None:
        head_tags.append(
            f'<meta property="article:modified_time" content="{html.escape(ctx.modified_time)}">'
        )

    if ctx.json_ld is not None:
        ld_json = json.dumps(ctx.json_ld, ensure_ascii=False, separators=(",", ":"))
        head_tags.append(f'<script type="application/ld+json">{ld_json}</script>')

    head_block = "\n".join(head_tags)

    result = re.sub(r"<title>[^<]*</title>", f"<title>{esc_title}</title>", base_html)
    result = result.replace("</head>", f"{head_block}\n</head>")

    if ctx.rendered_body is not None:
        result = result.replace(
            '<div id="root"></div>',
            f'<div id="root"><div style="{_PRE_RENDER_STYLE}">{ctx.rendered_body}</div></div>',
        )

    if ctx.preload_data is not None:
        preload_json = json.dumps(ctx.preload_data, ensure_ascii=False, separators=(",", ":"))
        esc_preload = preload_json.replace("</", "<\\/")
        result = result.replace(
            "</body>",
            f'<script id="__initial_data__" type="application/json">{esc_preload}</script>\n</body>',
        )

    return result
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_seo_service.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/services/seo_service.py tests/test_services/test_seo_service.py
git commit -m "feat: add SEO service with SeoContext and render_seo_html"
```

---

### Task 2: SEO Service — JSON-LD Helpers, Rendered Body, Preload Data

**Files:**
- Modify: `backend/services/seo_service.py`
- Modify: `tests/test_services/test_seo_service.py`

- [ ] **Step 1: Write failing tests for JSON-LD injection**

Add to `tests/test_services/test_seo_service.py`:

```python
class TestRenderSeoHtmlJsonLd:
    def test_injects_json_ld_script(self) -> None:
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "Test"}
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=ld))
        assert '<script type="application/ld+json">' in result
        assert '"@type":"WebSite"' in result

    def test_json_ld_before_head_close(self) -> None:
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "Test"}
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=ld))
        head_close = result.index("</head>")
        ld_pos = result.index("application/ld+json")
        assert ld_pos < head_close

    def test_omits_json_ld_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(json_ld=None))
        assert "application/ld+json" not in result
```

- [ ] **Step 2: Run tests to verify they pass**

These should already pass from Task 1 implementation. Run:

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestRenderSeoHtmlJsonLd -v`
Expected: All PASS (JSON-LD was implemented in Task 1)

- [ ] **Step 3: Write failing tests for rendered body injection**

Add to `tests/test_services/test_seo_service.py`:

```python
class TestRenderSeoHtmlBody:
    def test_injects_rendered_body_inside_root(self) -> None:
        result = render_seo_html(
            BASE_HTML, _make_ctx(rendered_body="<h1>Hello</h1><p>World</p>")
        )
        assert "<h1>Hello</h1><p>World</p>" in result
        assert '<div id="root"><div style="' in result

    def test_body_has_inline_styles(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body="<p>Hi</p>"))
        assert "max-width:42rem" in result
        assert "font-family:system-ui" in result

    def test_omits_body_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(rendered_body=None))
        assert '<div id="root"></div>' in result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestRenderSeoHtmlBody -v`
Expected: All PASS (rendered body was implemented in Task 1)

- [ ] **Step 5: Write failing tests for preload data injection**

Add to `tests/test_services/test_seo_service.py`:

```python
class TestRenderSeoHtmlPreload:
    def test_injects_preload_script(self) -> None:
        data = {"posts": [{"title": "Hello"}], "total": 1}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        assert '<script id="__initial_data__" type="application/json">' in result
        assert '"posts":[{"title":"Hello"}]' in result

    def test_preload_before_body_close(self) -> None:
        data = {"key": "value"}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        body_close = result.index("</body>")
        preload_pos = result.index("__initial_data__")
        assert preload_pos < body_close

    def test_omits_preload_when_none(self) -> None:
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=None))
        assert "__initial_data__" not in result

    def test_preload_escapes_script_closing_tag(self) -> None:
        data = {"html": "</script><script>alert(1)"}
        result = render_seo_html(BASE_HTML, _make_ctx(preload_data=data))
        assert "</script><script>" not in result
        assert "<\\/script>" in result
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestRenderSeoHtmlPreload -v`
Expected: All PASS (preload was implemented in Task 1)

- [ ] **Step 7: Write failing tests for JSON-LD helper functions**

Add to `tests/test_services/test_seo_service.py`:

```python
from backend.services.seo_service import blogposting_ld, webpage_ld, website_ld


class TestJsonLdHelpers:
    def test_blogposting_ld_basic(self) -> None:
        result = blogposting_ld(
            headline="My Post",
            description="A description",
            url="https://example.com/post/x",
            date_published="2026-03-28T12:00:00+00:00",
            date_modified="2026-03-28T14:00:00+00:00",
            author_name="Jane",
            publisher_name="My Blog",
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "BlogPosting"
        assert result["headline"] == "My Post"
        assert result["author"] == {"@type": "Person", "name": "Jane"}
        assert result["publisher"] == {"@type": "Organization", "name": "My Blog"}

    def test_blogposting_ld_no_author(self) -> None:
        result = blogposting_ld(
            headline="Post",
            description="Desc",
            url="https://example.com/post/x",
            date_published="2026-03-28T12:00:00+00:00",
            date_modified="2026-03-28T14:00:00+00:00",
            author_name=None,
            publisher_name="Blog",
        )
        assert "author" not in result

    def test_webpage_ld(self) -> None:
        result = webpage_ld(
            name="About", description="About page", url="https://example.com/page/about"
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "WebPage"
        assert result["name"] == "About"

    def test_website_ld(self) -> None:
        result = website_ld(
            name="My Blog", description="A blog", url="https://example.com/"
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "WebSite"
        assert result["name"] == "My Blog"
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestJsonLdHelpers -v`
Expected: FAIL — `ImportError: cannot import name 'blogposting_ld'`

- [ ] **Step 9: Implement JSON-LD helper functions**

Add to `backend/services/seo_service.py`:

```python
def blogposting_ld(
    *,
    headline: str,
    description: str,
    url: str,
    date_published: str,
    date_modified: str,
    author_name: str | None,
    publisher_name: str,
) -> dict[str, Any]:
    """Build a schema.org BlogPosting JSON-LD dict."""
    ld: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": headline,
        "description": description,
        "url": url,
        "datePublished": date_published,
        "dateModified": date_modified,
        "publisher": {"@type": "Organization", "name": publisher_name},
    }
    if author_name is not None:
        ld["author"] = {"@type": "Person", "name": author_name}
    return ld


def webpage_ld(*, name: str, description: str, url: str) -> dict[str, Any]:
    """Build a schema.org WebPage JSON-LD dict."""
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": name,
        "description": description,
        "url": url,
    }


def website_ld(*, name: str, description: str, url: str) -> dict[str, Any]:
    """Build a schema.org WebSite JSON-LD dict."""
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": name,
        "description": description,
        "url": url,
    }
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_seo_service.py -v`
Expected: All PASS

- [ ] **Step 11: Commit**

```bash
git add backend/services/seo_service.py tests/test_services/test_seo_service.py
git commit -m "feat: add JSON-LD helpers and verify body/preload injection"
```

---

### Task 3: SEO Service — Server-Rendered Post List Helper

**Files:**
- Modify: `backend/services/seo_service.py`
- Modify: `tests/test_services/test_seo_service.py`

- [ ] **Step 1: Write failing tests for `render_post_list_html`**

This helper renders a simple HTML list of posts for the server-rendered content on homepage and label pages. Add to `tests/test_services/test_seo_service.py`:

```python
from backend.services.seo_service import render_post_list_html


class TestRenderPostListHtml:
    def test_renders_post_links(self) -> None:
        posts = [
            {"title": "First Post", "slug": "first", "date": "March 28, 2026", "excerpt": "Hello"},
            {"title": "Second Post", "slug": "second", "date": "March 27, 2026", "excerpt": "World"},
        ]
        result = render_post_list_html(posts, heading="My Blog")
        assert '<a href="/post/first"' in result
        assert "First Post" in result
        assert '<a href="/post/second"' in result
        assert "March 28, 2026" in result
        assert "Hello" in result

    def test_renders_heading(self) -> None:
        result = render_post_list_html([], heading="My Blog")
        assert "<h1" in result
        assert "My Blog" in result

    def test_empty_list(self) -> None:
        result = render_post_list_html([], heading="Blog")
        assert "<ul" in result
        assert "<li" not in result

    def test_escapes_html_in_title(self) -> None:
        posts = [{"title": "<script>XSS</script>", "slug": "x", "date": "D", "excerpt": "E"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "<script>" not in result

    def test_escapes_html_in_excerpt(self) -> None:
        posts = [{"title": "T", "slug": "x", "date": "D", "excerpt": "<img onerror=alert(1)>"}]
        result = render_post_list_html(posts, heading="Blog")
        assert "onerror" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestRenderPostListHtml -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `render_post_list_html`**

Add to `backend/services/seo_service.py`:

```python
def render_post_list_html(
    posts: list[dict[str, str]],
    *,
    heading: str,
) -> str:
    """Render a simple HTML post list for server-side pre-rendering.

    Each post dict must have keys: title, slug, date, excerpt.
    """
    esc_heading = html.escape(heading)
    items = []
    for post in posts:
        esc_title = html.escape(post["title"])
        esc_slug = html.escape(post["slug"])
        esc_date = html.escape(post["date"])
        esc_excerpt = html.escape(post["excerpt"])
        items.append(
            f'<li style="margin-bottom:1.5rem">'
            f'<a href="/post/{esc_slug}" style="font-size:1.25rem;color:#1a1a1a;'
            f'text-decoration:none">{esc_title}</a>'
            f'<p style="color:#666;font-size:0.875rem;margin:0.25rem 0">{esc_date}</p>'
            f'<p style="color:#444;font-size:0.95rem;margin:0">{esc_excerpt}</p>'
            f"</li>"
        )
    list_html = "\n".join(items)
    return (
        f'<h1 style="font-size:2.25rem;line-height:1.2;margin-bottom:1.5rem">{esc_heading}</h1>'
        f'<ul style="list-style:none;padding:0">{list_html}</ul>'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_services/test_seo_service.py::TestRenderPostListHtml -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/seo_service.py tests/test_services/test_seo_service.py
git commit -m "feat: add render_post_list_html helper for server-side post lists"
```

---

### Task 4: Refactor `post_route` to Use SEO Service

**Files:**
- Modify: `backend/main.py` (lines ~796-878 — the `post_route` handler)
- Delete: `backend/services/opengraph_service.py`
- Delete: `tests/test_services/test_opengraph_service.py`
- Modify: `tests/test_api/test_opengraph.py` — extend with new assertions

- [ ] **Step 1: Extend existing OG integration tests for new SEO features**

Add new test classes to `tests/test_api/test_opengraph.py` (keeping the existing test file, which already has the fixture setup). Add tests for the new meta tags that the refactored route should produce:

```python
class TestPostSeoMetaTags:
    """New SEO meta tags on post pages."""

    async def test_meta_description_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert '<meta name="description"' in resp.text

    async def test_canonical_link_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert '<link rel="canonical"' in resp.text
        assert "/post/hello" in resp.text

    async def test_json_ld_blogposting(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert 'application/ld+json' in resp.text
        assert '"BlogPosting"' in resp.text
        assert '"Hello World"' in resp.text

    async def test_rendered_body_inside_root(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        # The post body should be pre-rendered inside <div id="root">
        assert "post body with some content" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/post/hello")
        assert '__initial_data__' in resp.text
        assert '"rendered_html"' in resp.text

    async def test_draft_has_no_rendered_body(self, client: AsyncClient) -> None:
        resp = await client.get("/post/my-draft")
        assert "Draft content" not in resp.text

    async def test_missing_post_has_no_seo(self, client: AsyncClient) -> None:
        resp = await client.get("/post/nonexistent")
        assert '<meta name="description"' not in resp.text
        assert "application/ld+json" not in resp.text
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_opengraph.py::TestPostSeoMetaTags -v`
Expected: FAIL — the current `post_route` doesn't produce these tags

- [ ] **Step 3: Refactor `post_route` in `backend/main.py`**

Replace the inline OG injection logic (lines ~814-878) with a call to the SEO service. The asset-redirect block at the top (lines 801-812) stays unchanged. The new post view block:

```python
        # Post view: /post/<slug> → serve SPA HTML with SEO enrichment
        from backend.models.post import PostCache
        from backend.services.seo_service import (
            SeoContext,
            blogposting_ld,
            render_seo_html,
            strip_html_tags,
        )
        from backend.utils.datetime import format_iso

        frontend_dir_path: Path = request.app.state.settings.frontend_dir
        index_path = frontend_dir_path / "index.html"

        base_html: str | None = getattr(request.app.state, "_seo_base_html", None)
        if base_html is None:
            try:
                base_html = await asyncio.to_thread(index_path.read_text, encoding="utf-8")
                request.app.state._seo_base_html = base_html
            except OSError:
                logger.warning("index.html not found at %s", index_path)
                return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        from backend.utils.slug import is_directory_post_path, resolve_slug_candidates

        slug = file_path
        post = None
        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                candidates: tuple[str, ...]
                if is_directory_post_path(file_path):
                    candidates = (file_path,)
                elif file_path.startswith("posts/"):
                    candidates = ()
                else:
                    candidates = resolve_slug_candidates(slug)

                for candidate in candidates:
                    stmt = select(PostCache).where(PostCache.file_path == candidate)
                    result = await session.execute(stmt)
                    post = result.scalar_one_or_none()
                    if post is not None:
                        break
        except SQLAlchemyError:
            logger.exception("DB error looking up post for SEO: %s", slug)
            return HTMLResponse(base_html)

        if post is None or post.is_draft:
            return HTMLResponse(base_html)

        description = ""
        if post.rendered_excerpt:
            description = strip_html_tags(post.rendered_excerpt)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title
        canonical = str(request.base_url).rstrip("/") + f"/post/{slug}"
        published = format_iso(post.created_at)
        modified = format_iso(post.modified_at)

        # Build article body for pre-rendering
        rendered_body = None
        if post.rendered_html:
            date_str = post.created_at.strftime("%B %-d, %Y")
            author_line = f" · {post.author}" if post.author else ""
            rendered_body = (
                f"<article>"
                f"<h1>{html.escape(post.title)}</h1>"
                f'<p style="color:#666;font-size:0.875rem;margin-bottom:2rem">'
                f"{html.escape(date_str)}{html.escape(author_line)}</p>"
                f"{post.rendered_html}"
                f"</article>"
            )

        # Build preload data matching PostDetail schema
        preload_data = {
            "id": post.id,
            "file_path": post.file_path,
            "title": post.title,
            "subtitle": post.subtitle,
            "author": post.author,
            "created_at": published,
            "modified_at": modified,
            "is_draft": post.is_draft,
            "rendered_excerpt": post.rendered_excerpt,
            "labels": [pl.label_id for pl in post.labels],
            "rendered_html": post.rendered_html or "",
            "content": None,
            "warnings": [],
        }

        ctx = SeoContext(
            title=post.title,
            description=description,
            canonical_url=canonical,
            og_type="article",
            site_name=site_name,
            author=post.author,
            published_time=published,
            modified_time=modified,
            json_ld=blogposting_ld(
                headline=post.title,
                description=description,
                url=canonical,
                date_published=published,
                date_modified=modified,
                author_name=post.author,
                publisher_name=site_name,
            ),
            rendered_body=rendered_body,
            preload_data=preload_data,
        )

        enriched = render_seo_html(base_html, ctx)
        return HTMLResponse(enriched)
```

Add `import html` at the top of `main.py` if not already present.

- [ ] **Step 4: Delete `backend/services/opengraph_service.py` and its tests**

```bash
rm backend/services/opengraph_service.py
rm tests/test_services/test_opengraph_service.py
```

- [ ] **Step 5: Run all OG integration tests**

Run: `just test-backend -- tests/test_api/test_opengraph.py -v`
Expected: All PASS (existing + new tests)

- [ ] **Step 6: Run full backend test suite to check for no regressions**

Run: `just test-backend`
Expected: All PASS — no other file imports `opengraph_service` (only `main.py` did)

- [ ] **Step 7: Commit**

```bash
git add backend/main.py tests/test_api/test_opengraph.py
git add -u backend/services/opengraph_service.py tests/test_services/test_opengraph_service.py
git commit -m "refactor: replace opengraph_service with seo_service in post_route"
```

---

### Task 5: Homepage Route Handler

**Files:**
- Modify: `backend/main.py`
- Create: `tests/test_api/test_seo_routes.py`

- [ ] **Step 1: Write failing integration tests for homepage SEO**

Create `tests/test_api/test_seo_routes.py` with a shared fixture:

```python
"""Integration tests for SEO-enriched route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def seo_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Settings for SEO route tests with sample content."""
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: [python]\n---\n"
        "Hello body content for excerpt.\n"
    )

    post2 = posts_dir / "second"
    post2.mkdir()
    (post2 / "index.md").write_text(
        "---\ntitle: Second Post\ncreated_at: 2026-03-27 12:00:00+00\n"
        "author: admin\nlabels: []\n---\n"
        "Second post body.\n"
    )

    draft = posts_dir / "my-draft"
    draft.mkdir()
    (draft / "index.md").write_text(
        "---\ntitle: Secret Draft\ncreated_at: 2026-03-26 12:00:00+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\n"
        "Draft content.\n"
    )

    # Add a label
    labels_toml = tmp_content_dir / "labels.toml"
    labels_toml.write_text('[labels.python]\nnames = ["Python"]\n')

    # Add an about page
    (tmp_content_dir / "about.md").write_text("# About\n\nThis is the about page content.\n")
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Test Blog"\ndescription = "A test blog"\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
    )

    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        '<!DOCTYPE html><html><head><title>Blog</title></head>'
        '<body><div id="root"></div></body></html>'
    )

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=frontend_dir,
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(seo_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(seo_settings) as ac:
        yield ac


class TestHomepageSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title_is_site_name(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "<title>Test Blog</title>" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert '<meta name="description" content="A test blog">' in resp.text

    async def test_og_type_website(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert 'og:type" content="website"' in resp.text

    async def test_json_ld_website(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert '"WebSite"' in resp.text
        assert '"Test Blog"' in resp.text

    async def test_canonical_url(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert '<link rel="canonical"' in resp.text

    async def test_rendered_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "/post/hello" in resp.text
        assert "Hello World" in resp.text
        assert "/post/second" in resp.text

    async def test_draft_not_in_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "Secret Draft" not in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert "__initial_data__" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestHomepageSeo -v`
Expected: FAIL — homepage currently returns the plain SPA shell from StaticFiles

- [ ] **Step 3: Add homepage route handler to `backend/main.py`**

Register a new `GET /` handler **before** the StaticFiles mount and **after** the post_route. The handler queries the first page of published posts, builds an `SeoContext`, and returns enriched HTML.

```python
    @app.get("/", include_in_schema=False, response_model=None)
    async def homepage_route(request: Request) -> HTMLResponse:
        from backend.models.post import PostCache
        from backend.services.seo_service import (
            SeoContext,
            render_post_list_html,
            render_seo_html,
            strip_html_tags,
            website_ld,
        )
        from backend.utils.datetime import format_iso

        base_html = await _get_base_html(request)
        if base_html is None:
            return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        content_manager: ContentManager = request.app.state.content_manager
        site_title = content_manager.site_config.title
        site_desc = content_manager.site_config.description
        base_url = str(request.base_url).rstrip("/")

        # Fetch first page of published posts
        posts_data: list[dict[str, str]] = []
        preload_posts: list[dict[str, Any]] = []
        total = 0
        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                count_stmt = (
                    select(func.count())
                    .select_from(PostCache)
                    .where(PostCache.is_draft == False)  # noqa: E712
                )
                total = (await session.execute(count_stmt)).scalar_one()

                stmt = (
                    select(PostCache)
                    .where(PostCache.is_draft == False)  # noqa: E712
                    .order_by(PostCache.created_at.desc())
                    .limit(10)
                )
                result = await session.execute(stmt)
                posts = result.scalars().all()

                for p in posts:
                    excerpt = strip_html_tags(p.rendered_excerpt) if p.rendered_excerpt else ""
                    slug = p.file_path.split("/")[1] if "/" in p.file_path else p.file_path
                    posts_data.append({
                        "title": p.title,
                        "slug": slug,
                        "date": p.created_at.strftime("%B %-d, %Y"),
                        "excerpt": excerpt,
                    })
                    preload_posts.append({
                        "id": p.id,
                        "file_path": p.file_path,
                        "title": p.title,
                        "subtitle": p.subtitle,
                        "author": p.author,
                        "created_at": format_iso(p.created_at),
                        "modified_at": format_iso(p.modified_at),
                        "is_draft": p.is_draft,
                        "rendered_excerpt": p.rendered_excerpt,
                        "labels": [pl.label_id for pl in p.labels],
                    })
        except SQLAlchemyError:
            logger.exception("DB error loading posts for homepage SEO")
            return HTMLResponse(base_html)

        rendered_body = render_post_list_html(posts_data, heading=site_title)

        preload_data = {
            "posts": preload_posts,
            "total": total,
            "page": 1,
            "per_page": 10,
            "total_pages": max(1, (total + 9) // 10),
        }

        ctx = SeoContext(
            title=site_title,
            description=site_desc,
            canonical_url=base_url + "/",
            site_name=site_title,
            json_ld=website_ld(name=site_title, description=site_desc, url=base_url + "/"),
            rendered_body=rendered_body,
            preload_data=preload_data,
        )

        return HTMLResponse(render_seo_html(base_html, ctx))
```

Also extract the base HTML loading into a shared helper to avoid duplication:

```python
async def _get_base_html(request: Request) -> str | None:
    """Read and cache the frontend index.html for SEO injection."""
    base_html: str | None = getattr(request.app.state, "_seo_base_html", None)
    if base_html is None:
        frontend_dir_path: Path = request.app.state.settings.frontend_dir
        index_path = frontend_dir_path / "index.html"
        try:
            base_html = await asyncio.to_thread(index_path.read_text, encoding="utf-8")
            request.app.state._seo_base_html = base_html
        except OSError:
            logger.warning("index.html not found at %s", index_path)
            return None
    return base_html
```

Update the `post_route` to use `_get_base_html()` as well (replace the inline base HTML loading).

Add required imports at the module level in `main.py`: `from sqlalchemy import func, select` (select is likely already imported; add func if missing). Also add `from typing import Any` if not present.

- [ ] **Step 4: Run homepage tests**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestHomepageSeo -v`
Expected: All PASS

- [ ] **Step 5: Run existing OG tests to verify no regressions**

Run: `just test-backend -- tests/test_api/test_opengraph.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_api/test_seo_routes.py
git commit -m "feat: add SEO-enriched homepage route with post list and preload"
```

---

### Task 6: Page Route Handler

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/test_api/test_seo_routes.py`

- [ ] **Step 1: Write failing integration tests for page SEO**

Add to `tests/test_api/test_seo_routes.py`:

```python
class TestPageSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title_includes_page_name(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "<title>About</title>" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert '<meta name="description"' in resp.text

    async def test_og_type_website(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert 'og:type" content="website"' in resp.text

    async def test_json_ld_webpage(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert '"WebPage"' in resp.text
        assert '"About"' in resp.text

    async def test_rendered_body_present(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "about page content" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/page/about")
        assert "__initial_data__" in resp.text

    async def test_unknown_page_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/page/nonexistent")
        assert resp.status_code == 200
        assert "og:title" not in resp.text

    async def test_builtin_page_without_file(self, client: AsyncClient) -> None:
        """Built-in page 'timeline' has no file — returns plain HTML."""
        resp = await client.get("/page/timeline")
        assert resp.status_code == 200
        # timeline is a built-in with no file, so gets site-level defaults
        assert "<title>" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestPageSeo -v`
Expected: FAIL — no `/page/{pageId}` route handler exists yet (falls through to StaticFiles)

- [ ] **Step 3: Add page route handler to `backend/main.py`**

Register before StaticFiles mount:

```python
    @app.get("/page/{page_id}", include_in_schema=False, response_model=None)
    async def page_route(page_id: str, request: Request) -> HTMLResponse:
        from backend.services.page_service import get_page
        from backend.services.seo_service import (
            SeoContext,
            render_seo_html,
            strip_html_tags,
            webpage_ld,
        )

        base_html = await _get_base_html(request)
        if base_html is None:
            return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title
        site_desc = content_manager.site_config.description
        base_url = str(request.base_url).rstrip("/")

        try:
            page = await asyncio.to_thread(get_page, content_manager, page_id)
        except Exception:
            logger.exception("Error loading page for SEO: %s", page_id)
            return HTMLResponse(base_html)

        if page is None:
            return HTMLResponse(base_html)

        description = strip_html_tags(page.rendered_html)[:200] if page.rendered_html else site_desc
        canonical = f"{base_url}/page/{page_id}"

        rendered_body = None
        if page.rendered_html:
            rendered_body = (
                f"<article>"
                f"<h1>{html.escape(page.title)}</h1>"
                f"{page.rendered_html}"
                f"</article>"
            )

        preload_data = {
            "id": page.id,
            "title": page.title,
            "rendered_html": page.rendered_html,
        }

        ctx = SeoContext(
            title=page.title,
            description=description,
            canonical_url=canonical,
            site_name=site_name,
            json_ld=webpage_ld(name=page.title, description=description, url=canonical),
            rendered_body=rendered_body,
            preload_data=preload_data,
        )

        return HTMLResponse(render_seo_html(base_html, ctx))
```

- [ ] **Step 4: Run page tests**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestPageSeo -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_seo_routes.py
git commit -m "feat: add SEO-enriched page route with rendered body and preload"
```

---

### Task 7: Label Routes (Index and Detail)

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/test_api/test_seo_routes.py`

- [ ] **Step 1: Write failing integration tests for label SEO**

Add to `tests/test_api/test_seo_routes.py`:

```python
class TestLabelsIndexSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert "Labels" in resp.text
        assert "<title>" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert '<meta name="description"' in resp.text

    async def test_og_type_website(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert 'og:type" content="website"' in resp.text

    async def test_no_preload_data(self, client: AsyncClient) -> None:
        resp = await client.get("/labels")
        assert "__initial_data__" not in resp.text


class TestLabelDetailSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title_includes_label(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "Python" in resp.text or "python" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert '<meta name="description"' in resp.text

    async def test_rendered_post_list(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "/post/hello" in resp.text
        assert "Hello World" in resp.text

    async def test_preload_data_present(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/python")
        assert "__initial_data__" in resp.text

    async def test_unknown_label_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/labels/nonexistent")
        assert resp.status_code == 200
        assert "og:title" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestLabelsIndexSeo tests/test_api/test_seo_routes.py::TestLabelDetailSeo -v`
Expected: FAIL

- [ ] **Step 3: Add labels index route handler**

Register in `backend/main.py` before StaticFiles mount. Must be registered before the label detail route to avoid path conflicts:

```python
    @app.get("/labels", include_in_schema=False, response_model=None)
    async def labels_index_route(request: Request) -> HTMLResponse:
        from backend.services.seo_service import SeoContext, render_seo_html

        base_html = await _get_base_html(request)
        if base_html is None:
            return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title
        base_url = str(request.base_url).rstrip("/")

        ctx = SeoContext(
            title=f"Labels — {site_name}",
            description=f"Labels — {site_name}",
            canonical_url=f"{base_url}/labels",
            site_name=site_name,
        )

        return HTMLResponse(render_seo_html(base_html, ctx))
```

- [ ] **Step 4: Add label detail route handler**

```python
    @app.get("/labels/{label_id}", include_in_schema=False, response_model=None)
    async def label_detail_route(label_id: str, request: Request) -> HTMLResponse:
        from backend.models.label import LabelCache, PostLabelCache
        from backend.models.post import PostCache
        from backend.services.seo_service import (
            SeoContext,
            render_post_list_html,
            render_seo_html,
            strip_html_tags,
        )
        from backend.utils.datetime import format_iso

        base_html = await _get_base_html(request)
        if base_html is None:
            return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title
        base_url = str(request.base_url).rstrip("/")

        label = None
        posts_data: list[dict[str, str]] = []
        preload_posts: list[dict[str, Any]] = []
        total = 0
        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                label_stmt = select(LabelCache).where(LabelCache.id == label_id)
                label = (await session.execute(label_stmt)).scalar_one_or_none()

                if label is not None:
                    # Count posts for this label
                    count_stmt = (
                        select(func.count())
                        .select_from(PostCache)
                        .join(PostLabelCache, PostCache.id == PostLabelCache.post_id)
                        .where(PostLabelCache.label_id == label_id)
                        .where(PostCache.is_draft == False)  # noqa: E712
                    )
                    total = (await session.execute(count_stmt)).scalar_one()

                    # Fetch first page of posts
                    posts_stmt = (
                        select(PostCache)
                        .join(PostLabelCache, PostCache.id == PostLabelCache.post_id)
                        .where(PostLabelCache.label_id == label_id)
                        .where(PostCache.is_draft == False)  # noqa: E712
                        .order_by(PostCache.created_at.desc())
                        .limit(20)
                    )
                    result = await session.execute(posts_stmt)
                    posts = result.scalars().all()

                    for p in posts:
                        excerpt = strip_html_tags(p.rendered_excerpt) if p.rendered_excerpt else ""
                        slug = p.file_path.split("/")[1] if "/" in p.file_path else p.file_path
                        posts_data.append({
                            "title": p.title,
                            "slug": slug,
                            "date": p.created_at.strftime("%B %-d, %Y"),
                            "excerpt": excerpt,
                        })
                        preload_posts.append({
                            "id": p.id,
                            "file_path": p.file_path,
                            "title": p.title,
                            "subtitle": p.subtitle,
                            "author": p.author,
                            "created_at": format_iso(p.created_at),
                            "modified_at": format_iso(p.modified_at),
                            "is_draft": p.is_draft,
                            "rendered_excerpt": p.rendered_excerpt,
                            "labels": [pl.label_id for pl in p.labels],
                        })
        except SQLAlchemyError:
            logger.exception("DB error loading label for SEO: %s", label_id)
            return HTMLResponse(base_html)

        if label is None:
            return HTMLResponse(base_html)

        import json as json_mod
        label_names = json_mod.loads(label.names) if label.names else [label_id]
        display_name = label_names[0] if label_names else label_id

        rendered_body = render_post_list_html(posts_data, heading=display_name)

        preload_data = {
            "label": {
                "id": label.id,
                "names": label_names,
                "is_implicit": label.is_implicit,
                "parents": [e.parent_id for e in label.parent_edges],
                "children": [e.label_id for e in label.child_edges],
                "post_count": total,
            },
            "posts": {
                "posts": preload_posts,
                "total": total,
                "page": 1,
                "per_page": 20,
                "total_pages": max(1, (total + 19) // 20),
            },
        }

        ctx = SeoContext(
            title=f"{display_name} — {site_name}",
            description=f"Posts labeled {display_name} — {site_name}",
            canonical_url=f"{base_url}/labels/{label_id}",
            site_name=site_name,
            rendered_body=rendered_body,
            preload_data=preload_data,
        )

        return HTMLResponse(render_seo_html(base_html, ctx))
```

**Important:** The `/labels/{label_id}` route must NOT match `/labels/new` or `/labels/{id}/settings` — those are SPA routes. Add these specific routes before the label detail catch-all so they fall through to the SPA:

```python
    @app.get("/labels/new", include_in_schema=False, response_model=None)
    async def labels_new_route(request: Request) -> HTMLResponse:
        base_html = await _get_base_html(request)
        return HTMLResponse(base_html or "<html><body>Not found</body></html>")

    @app.get("/labels/{label_id}/settings", include_in_schema=False, response_model=None)
    async def label_settings_route(label_id: str, request: Request) -> HTMLResponse:
        base_html = await _get_base_html(request)
        return HTMLResponse(base_html or "<html><body>Not found</body></html>")
```

Register these BEFORE `/labels/{label_id}`.

- [ ] **Step 5: Run label tests**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestLabelsIndexSeo tests/test_api/test_seo_routes.py::TestLabelDetailSeo -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_api/test_seo_routes.py
git commit -m "feat: add SEO-enriched label routes with post lists and preload"
```

---

### Task 8: Search Route Handler

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/test_api/test_seo_routes.py`

- [ ] **Step 1: Write failing integration tests**

Add to `tests/test_api/test_seo_routes.py`:

```python
class TestSearchSeo:
    async def test_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_title(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert "Search" in resp.text

    async def test_meta_description(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert '<meta name="description"' in resp.text

    async def test_no_preload_data(self, client: AsyncClient) -> None:
        resp = await client.get("/search")
        assert "__initial_data__" not in resp.text

    async def test_no_canonical(self, client: AsyncClient) -> None:
        """Search pages are query-dependent, no canonical URL."""
        resp = await client.get("/search?q=hello")
        # Canonical should still point to /search (without query)
        # or not be present — either is acceptable
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestSearchSeo -v`
Expected: FAIL

- [ ] **Step 3: Add search route handler**

```python
    @app.get("/search", include_in_schema=False, response_model=None)
    async def search_route(request: Request) -> HTMLResponse:
        from backend.services.seo_service import SeoContext, render_seo_html

        base_html = await _get_base_html(request)
        if base_html is None:
            return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title
        base_url = str(request.base_url).rstrip("/")

        ctx = SeoContext(
            title=f"Search — {site_name}",
            description=f"Search — {site_name}",
            canonical_url=f"{base_url}/search",
            site_name=site_name,
        )

        return HTMLResponse(render_seo_html(base_html, ctx))
```

- [ ] **Step 4: Run search tests**

Run: `just test-backend -- tests/test_api/test_seo_routes.py::TestSearchSeo -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_seo_routes.py
git commit -m "feat: add SEO-enriched search route"
```

---

### Task 9: Sitemap Endpoint

**Files:**
- Modify: `backend/main.py`
- Create: `tests/test_api/test_sitemap.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_api/test_sitemap.py`:

```python
"""Integration tests for the sitemap.xml endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def sitemap_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: [python]\n---\nBody.\n"
    )

    draft = posts_dir / "my-draft"
    draft.mkdir()
    (draft / "index.md").write_text(
        "---\ntitle: Draft\ncreated_at: 2026-03-26 12:00:00+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\nDraft.\n"
    )

    labels_toml = tmp_content_dir / "labels.toml"
    labels_toml.write_text('[labels.python]\nnames = ["Python"]\n')

    (tmp_content_dir / "about.md").write_text("# About\nAbout page.\n")
    index_toml = tmp_content_dir / "index.toml"
    index_toml.write_text(
        '[site]\ntitle = "Blog"\ndescription = "A blog"\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
    )

    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<html><head><title>B</title></head><body></body></html>")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=frontend_dir,
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(sitemap_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(sitemap_settings) as ac:
        yield ac


class TestSitemap:
    async def test_content_type(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "application/xml" in resp.headers["content-type"]

    async def test_valid_xml_structure(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert '<?xml version="1.0"' in resp.text
        assert "<urlset" in resp.text
        assert "</urlset>" in resp.text

    async def test_includes_homepage(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        # Homepage URL should be present
        assert "<loc>" in resp.text

    async def test_includes_published_post(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/post/hello" in resp.text

    async def test_excludes_draft(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/post/my-draft" not in resp.text

    async def test_includes_page(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/page/about" in resp.text

    async def test_excludes_builtin_pages_without_files(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/page/timeline" not in resp.text
        assert "/page/labels" not in resp.text

    async def test_includes_label_with_posts(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "/labels/python" in resp.text

    async def test_has_lastmod_for_posts(self, client: AsyncClient) -> None:
        resp = await client.get("/sitemap.xml")
        assert "<lastmod>" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_sitemap.py -v`
Expected: FAIL

- [ ] **Step 3: Implement sitemap endpoint**

Add to `backend/main.py` before StaticFiles mount:

```python
    @app.get("/sitemap.xml", include_in_schema=False, response_model=None)
    async def sitemap_route(request: Request) -> Response:
        from backend.models.label import LabelCache, PostLabelCache
        from backend.models.post import PostCache
        from backend.utils.datetime import format_iso

        base_url = str(request.base_url).rstrip("/")
        content_manager: ContentManager = request.app.state.content_manager

        urls: list[str] = []
        # Homepage
        urls.append(f"  <url><loc>{base_url}/</loc></url>")

        # Custom pages with files
        for page in content_manager.site_config.pages:
            if page.file is not None:
                urls.append(f"  <url><loc>{base_url}/page/{page.id}</loc></url>")

        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                # Published posts
                stmt = (
                    select(PostCache)
                    .where(PostCache.is_draft == False)  # noqa: E712
                    .order_by(PostCache.created_at.desc())
                )
                result = await session.execute(stmt)
                posts = result.scalars().all()

                for p in posts:
                    slug = p.file_path.split("/")[1] if "/" in p.file_path else p.file_path
                    lastmod = format_iso(p.modified_at)
                    urls.append(
                        f"  <url><loc>{base_url}/post/{slug}</loc>"
                        f"<lastmod>{lastmod}</lastmod></url>"
                    )

                # Labels with at least one published post
                label_stmt = (
                    select(LabelCache.id)
                    .join(PostLabelCache, LabelCache.id == PostLabelCache.label_id)
                    .join(PostCache, PostCache.id == PostLabelCache.post_id)
                    .where(PostCache.is_draft == False)  # noqa: E712
                    .group_by(LabelCache.id)
                )
                label_result = await session.execute(label_stmt)
                label_ids = label_result.scalars().all()

                for lid in label_ids:
                    urls.append(f"  <url><loc>{base_url}/labels/{lid}</loc></url>")
        except SQLAlchemyError:
            logger.exception("DB error generating sitemap")

        url_block = "\n".join(urls)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{url_block}\n"
            "</urlset>"
        )
        return Response(content=xml, media_type="application/xml")
```

- [ ] **Step 4: Run sitemap tests**

Run: `just test-backend -- tests/test_api/test_sitemap.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_sitemap.py
git commit -m "feat: add dynamic sitemap.xml endpoint"
```

---

### Task 10: Robots.txt Endpoint

**Files:**
- Modify: `backend/main.py`
- Create: `tests/test_api/test_robots.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_api/test_robots.py`:

```python
"""Integration tests for the robots.txt endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def robots_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<html><head><title>B</title></head><body></body></html>")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=frontend_dir,
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(robots_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(robots_settings) as ac:
        yield ac


class TestRobotsTxt:
    async def test_content_type(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    async def test_allows_root(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Allow: /" in resp.text

    async def test_disallows_api(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /api/" in resp.text

    async def test_disallows_admin(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /admin" in resp.text

    async def test_disallows_editor(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /editor/" in resp.text

    async def test_disallows_login(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Disallow: /login" in resp.text

    async def test_includes_sitemap_url(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        assert "Sitemap:" in resp.text
        assert "/sitemap.xml" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_robots.py -v`
Expected: FAIL

- [ ] **Step 3: Implement robots.txt endpoint**

Add to `backend/main.py` before StaticFiles mount:

```python
    @app.get("/robots.txt", include_in_schema=False, response_model=None)
    async def robots_route(request: Request) -> Response:
        base_url = str(request.base_url).rstrip("/")
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "Disallow: /admin\n"
            "Disallow: /editor/\n"
            "Disallow: /login\n"
            "Disallow: /labels/new\n"
            "Disallow: /labels/*/settings\n"
            "\n"
            f"Sitemap: {base_url}/sitemap.xml\n"
        )
        return Response(content=body, media_type="text/plain")
```

- [ ] **Step 4: Run robots tests**

Run: `just test-backend -- tests/test_api/test_robots.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_robots.py
git commit -m "feat: add robots.txt endpoint"
```

---

### Task 11: RSS Feed Endpoint

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/index.html`
- Create: `tests/test_api/test_feed.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_api/test_feed.py`:

```python
"""Integration tests for the RSS feed endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def feed_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    posts_dir = tmp_content_dir / "posts"

    post1 = posts_dir / "hello"
    post1.mkdir()
    (post1 / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-03-28 12:00:00+00\n"
        "author: admin\nlabels: []\n---\nHello body.\n"
    )

    draft = posts_dir / "my-draft"
    draft.mkdir()
    (draft / "index.md").write_text(
        "---\ntitle: Draft\ncreated_at: 2026-03-26 12:00:00+00\n"
        "author: admin\nlabels: []\ndraft: true\n---\nDraft.\n"
    )

    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<html><head><title>B</title></head><body></body></html>")

    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=frontend_dir,
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(feed_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(feed_settings) as ac:
        yield ac


class TestRssFeed:
    async def test_content_type(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert resp.status_code == 200
        assert "application/rss+xml" in resp.headers["content-type"]

    async def test_valid_rss_structure(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert '<?xml version="1.0"' in resp.text
        assert '<rss version="2.0"' in resp.text
        assert "<channel>" in resp.text
        assert "</channel>" in resp.text

    async def test_includes_channel_title(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<title>" in resp.text

    async def test_includes_published_post(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<item>" in resp.text
        assert "Hello World" in resp.text

    async def test_excludes_draft(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "Draft" not in resp.text

    async def test_item_has_link(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "/post/hello" in resp.text

    async def test_item_has_guid(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<guid" in resp.text

    async def test_item_has_pubdate(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "<pubDate>" in resp.text

    async def test_atom_self_link(self, client: AsyncClient) -> None:
        resp = await client.get("/feed.xml")
        assert "atom:link" in resp.text
        assert "/feed.xml" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_feed.py -v`
Expected: FAIL

- [ ] **Step 3: Implement RSS feed endpoint**

Add to `backend/main.py` before StaticFiles mount:

```python
    @app.get("/feed.xml", include_in_schema=False, response_model=None)
    async def feed_route(request: Request) -> Response:
        from email.utils import format_datetime as format_rfc2822

        from backend.models.post import PostCache
        from backend.services.seo_service import strip_html_tags

        base_url = str(request.base_url).rstrip("/")
        content_manager: ContentManager = request.app.state.content_manager
        site_title = html.escape(content_manager.site_config.title)
        site_desc = html.escape(content_manager.site_config.description)

        items: list[str] = []
        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                stmt = (
                    select(PostCache)
                    .where(PostCache.is_draft == False)  # noqa: E712
                    .order_by(PostCache.created_at.desc())
                    .limit(20)
                )
                result = await session.execute(stmt)
                posts = result.scalars().all()

                for p in posts:
                    slug = p.file_path.split("/")[1] if "/" in p.file_path else p.file_path
                    link = f"{base_url}/post/{slug}"
                    esc_title = html.escape(p.title)
                    desc = html.escape(
                        strip_html_tags(p.rendered_excerpt) if p.rendered_excerpt else ""
                    )
                    pub_date = format_rfc2822(p.created_at, usegmt=True)
                    items.append(
                        f"    <item>\n"
                        f"      <title>{esc_title}</title>\n"
                        f"      <link>{link}</link>\n"
                        f'      <guid isPermaLink="true">{link}</guid>\n'
                        f"      <pubDate>{pub_date}</pubDate>\n"
                        f"      <description>{desc}</description>\n"
                        f"    </item>"
                    )
        except SQLAlchemyError:
            logger.exception("DB error generating RSS feed")

        items_block = "\n".join(items)
        feed_url = f"{base_url}/feed.xml"
        rss = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            "  <channel>\n"
            f"    <title>{site_title}</title>\n"
            f"    <link>{base_url}/</link>\n"
            f"    <description>{site_desc}</description>\n"
            f'    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>\n'
            f"{items_block}\n"
            "  </channel>\n"
            "</rss>"
        )
        return Response(content=rss, media_type="application/rss+xml")
```

- [ ] **Step 4: Add RSS autodiscovery to `frontend/index.html`**

Add inside `<head>`:
```html
<link rel="alternate" type="application/rss+xml" title="RSS Feed" href="/feed.xml">
```

- [ ] **Step 5: Run feed tests**

Run: `just test-backend -- tests/test_api/test_feed.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py frontend/index.html tests/test_api/test_feed.py
git commit -m "feat: add RSS feed endpoint and autodiscovery link"
```

---

### Task 12: Frontend — Preload Data Utility

**Files:**
- Create: `frontend/src/utils/preload.ts`
- Create: `frontend/src/utils/__tests__/preload.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/utils/__tests__/preload.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { readPreloadedData } from '@/utils/preload'

describe('readPreloadedData', () => {
  beforeEach(() => {
    // Clean up any leftover script tags
    document.getElementById('__initial_data__')?.remove()
  })

  it('returns null when no script tag exists', () => {
    expect(readPreloadedData()).toBeNull()
  })

  it('reads and parses JSON from script tag', () => {
    const data = { posts: [{ title: 'Hello' }], total: 1 }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(data)
    document.body.appendChild(script)

    const result = readPreloadedData()
    expect(result).toEqual(data)
  })

  it('removes the script tag after reading', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedData()
    expect(document.getElementById('__initial_data__')).toBeNull()
  })

  it('returns null on second call', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedData()
    expect(readPreloadedData()).toBeNull()
  })

  it('returns null for invalid JSON', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = 'not valid json'
    document.body.appendChild(script)

    expect(readPreloadedData()).toBeNull()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend -- src/utils/__tests__/preload.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `preload.ts`**

Create `frontend/src/utils/preload.ts`:

```typescript
/** Read and remove the server-injected preload data. One-time read. */
export function readPreloadedData<T = unknown>(): T | null {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null

  el.remove()
  try {
    return JSON.parse(el.textContent ?? '') as T
  } catch {
    return null
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend -- src/utils/__tests__/preload.test.ts`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/preload.ts frontend/src/utils/__tests__/preload.test.ts
git commit -m "feat: add readPreloadedData utility for server-injected JSON"
```

---

### Task 13: Frontend — Hook Integration (usePost, usePage, useLabelPosts)

**Files:**
- Modify: `frontend/src/hooks/usePost.ts`
- Modify: `frontend/src/hooks/usePage.ts`
- Modify: `frontend/src/hooks/useLabelPosts.ts`

- [ ] **Step 1: Update `usePost` to use preloaded data**

The SWR `fallbackData` option provides initial data without triggering a fetch. Read the preloaded data once at module level (before any hook runs) so it's available for the first render.

Edit `frontend/src/hooks/usePost.ts`:

```typescript
import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloadedData } from '@/utils/preload'

const preloaded = readPreloadedData<PostDetail>()

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

**Important caveat:** `readPreloadedData` is one-shot — it reads and removes the script tag. Since only one hook's module will find the tag (depending on which page the server rendered), the other hooks will get `null` and fetch normally. This is correct behavior: on a post page, `usePost` gets the preload; on a page view, `usePage` gets it.

- [ ] **Step 2: Update `usePage` to use preloaded data**

Edit `frontend/src/hooks/usePage.ts`:

```typescript
import useSWR from 'swr'
import type { PageResponse } from '@/api/client'
import { readPreloadedData } from '@/utils/preload'

const preloaded = readPreloadedData<PageResponse>()

export function usePage(pageId: string | null) {
  return useSWR<PageResponse, Error>(
    pageId !== null ? `pages/${pageId}` : null,
    undefined,
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}
```

- [ ] **Step 3: Update `useLabelPosts` to use preloaded data**

Edit `frontend/src/hooks/useLabelPosts.ts`:

```typescript
import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloadedData } from '@/utils/preload'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

const preloaded = readPreloadedData<LabelPostsData>()

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

- [ ] **Step 4: Run frontend tests to check for regressions**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/usePost.ts frontend/src/hooks/usePage.ts frontend/src/hooks/useLabelPosts.ts
git commit -m "feat: integrate preloaded data into SWR hooks"
```

---

### Task 14: Frontend — Timeline Preload Integration

**Files:**
- Modify: `frontend/src/pages/TimelinePage.tsx`

- [ ] **Step 1: Add preload integration to TimelinePage**

The timeline uses `useEffect`+`useState`, not SWR. Read the preloaded data once and use it as initial state to skip the first fetch when the page loads from the server with data already embedded.

Edit `frontend/src/pages/TimelinePage.tsx` — add near the top of the file:

```typescript
import { readPreloadedData } from '@/utils/preload'
import type { PostListResponse } from '@/api/client'

const preloadedTimeline = readPreloadedData<PostListResponse>()
```

Then in the component, change the initial state:

```typescript
const [data, setData] = useState<PostListResponse | null>(preloadedTimeline)
const [loading, setLoading] = useState(preloadedTimeline === null)
```

And in the `useEffect` fetch, skip the API call when preloaded data was used on the initial render (page 1 with no filters):

```typescript
  useEffect(() => {
    const p = Number(searchParams.get('page') ?? '1')
    // ... existing filter parsing ...

    // Skip fetch if we have preloaded data for the default view
    if (preloadedTimeline !== null && p === 1 && labels.length === 0 && !author && !fromDate && !toDate) {
      preloadedTimeline = null  // one-shot: don't skip on subsequent renders
      return
    }

    void (async () => {
      // ... existing fetch logic ...
    })()
  }, [searchParams, retryCount, user])
```

**Note:** Since `preloadedTimeline` is a module-level `let` (change from `const` to `let`), clearing it to `null` ensures subsequent navigations back to the timeline trigger a fresh fetch.

- [ ] **Step 2: Run frontend tests**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/TimelinePage.tsx
git commit -m "feat: integrate preloaded data into TimelinePage"
```

---

### Task 15: Frontend — Dynamic Page Titles

**Files:**
- Modify: `frontend/src/pages/PostPage.tsx`
- Modify: `frontend/src/pages/PageViewPage.tsx`
- Modify: `frontend/src/pages/TimelinePage.tsx`
- Modify: `frontend/src/pages/LabelPostsPage.tsx`
- Modify: `frontend/src/pages/LabelsPage.tsx`
- Modify: `frontend/src/pages/SearchPage.tsx`

- [ ] **Step 1: Add dynamic title to PostPage**

Add to `frontend/src/pages/PostPage.tsx`:

```typescript
import { useSiteStore } from '@/stores/siteStore'

// Inside PostPage component, after post data is available:
const siteTitle = useSiteStore((s) => s.config?.title)

useEffect(() => {
  if (post !== undefined && siteTitle !== undefined) {
    document.title = `${post.title} — ${siteTitle}`
  }
}, [post, siteTitle])
```

- [ ] **Step 2: Add dynamic title to PageViewPage**

Add to `frontend/src/pages/PageViewPage.tsx`:

```typescript
import { useSiteStore } from '@/stores/siteStore'

// Inside component:
const siteTitle = useSiteStore((s) => s.config?.title)

useEffect(() => {
  if (page !== undefined && siteTitle !== undefined) {
    document.title = `${page.title} — ${siteTitle}`
  }
}, [page, siteTitle])
```

- [ ] **Step 3: Add dynamic title to TimelinePage**

The homepage should just show the site name. Add to `frontend/src/pages/TimelinePage.tsx`:

```typescript
import { useSiteStore } from '@/stores/siteStore'

// Inside component:
const siteTitle = useSiteStore((s) => s.config?.title)

useEffect(() => {
  if (siteTitle !== undefined) {
    document.title = siteTitle
  }
}, [siteTitle])
```

- [ ] **Step 4: Add dynamic title to LabelPostsPage**

Add to `frontend/src/pages/LabelPostsPage.tsx`:

```typescript
import { useSiteStore } from '@/stores/siteStore'

// Inside component, after label data:
const siteTitle = useSiteStore((s) => s.config?.title)

useEffect(() => {
  if (label !== null && siteTitle !== undefined) {
    const name = label.names.length > 0 ? label.names[0] : label.id
    document.title = `${name} — ${siteTitle}`
  }
}, [label, siteTitle])
```

- [ ] **Step 5: Add dynamic title to LabelsPage**

Add to `frontend/src/pages/LabelsPage.tsx`:

```typescript
import { useSiteStore } from '@/stores/siteStore'

// Inside component:
const siteTitle = useSiteStore((s) => s.config?.title)

useEffect(() => {
  if (siteTitle !== undefined) {
    document.title = `Labels — ${siteTitle}`
  }
}, [siteTitle])
```

- [ ] **Step 6: Add dynamic title to SearchPage**

Add to `frontend/src/pages/SearchPage.tsx`:

```typescript
import { useSiteStore } from '@/stores/siteStore'

// Inside component:
const siteTitle = useSiteStore((s) => s.config?.title)

useEffect(() => {
  if (siteTitle !== undefined) {
    document.title = `Search — ${siteTitle}`
  }
}, [siteTitle])
```

- [ ] **Step 7: Run frontend tests**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/PostPage.tsx frontend/src/pages/PageViewPage.tsx frontend/src/pages/TimelinePage.tsx frontend/src/pages/LabelPostsPage.tsx frontend/src/pages/LabelsPage.tsx frontend/src/pages/SearchPage.tsx
git commit -m "feat: add dynamic document.title to all page components"
```

---

### Task 16: Delete Old OG Test File and Run Full Suite

**Files:**
- Delete: `tests/test_api/test_opengraph.py` (merged into `test_seo_routes.py` conceptually; original OG tests were extended in Task 4)

**Wait** — actually, the existing `test_opengraph.py` tests are still valid and were *extended* in Task 4, not replaced. Keep the file. This task is just the final verification.

- [ ] **Step 1: Run full backend test suite**

Run: `just test-backend`
Expected: All PASS

- [ ] **Step 2: Run full frontend test suite**

Run: `just test-frontend`
Expected: All PASS

- [ ] **Step 3: Run full gate**

Run: `just check`
Expected: All PASS (static checks + tests)

- [ ] **Step 4: Update architecture docs**

Update `docs/arch/backend.md` to mention:
- SEO route handlers serve enriched HTML for all public routes before the StaticFiles catch-all
- `seo_service.py` provides the shared SEO enrichment pipeline (replaces `opengraph_service.py`)
- Sitemap, robots.txt, and RSS feed endpoints

Update `docs/arch/frontend.md` to mention:
- Server-rendered content inside `<div id="root">` is replaced by React on mount
- Preloaded data via `<script id="__initial_data__">` skips the initial API fetch
- Each page component sets `document.title` dynamically

- [ ] **Step 5: Commit architecture doc updates**

```bash
git add docs/arch/backend.md docs/arch/frontend.md
git commit -m "docs: update architecture docs for SEO enrichment"
```
