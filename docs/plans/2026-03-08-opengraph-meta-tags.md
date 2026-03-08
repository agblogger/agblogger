# Open Graph Meta Tags Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Serve Open Graph meta tags for post pages so social media crawlers (Facebook, LinkedIn, Slack, Discord, iMessage, etc.) display rich link previews with the post's title, description, and author.

**Architecture:** Add a FastAPI route `/post/{path}` before the StaticFiles mount that reads the SPA's `index.html`, queries post metadata from the DB, injects OG/Twitter Card meta tags into `<head>`, and returns the enriched HTML. The SPA still boots normally from this HTML. Drafts and missing posts get the unmodified `index.html`. A pure-function service module handles HTML injection, keeping it testable.

**Tech Stack:** FastAPI, SQLAlchemy (existing PostCache model), `html.escape` for safe attribute encoding, `re` for HTML tag stripping.

---

### Task 1: Create the OG tag injection service

**Files:**
- Create: `backend/services/opengraph_service.py`
- Test: `tests/test_services/test_opengraph_service.py`

**Step 1: Write failing tests**

Create `tests/test_services/test_opengraph_service.py`:

```python
"""Tests for Open Graph meta tag injection."""

from __future__ import annotations

from backend.services.opengraph_service import inject_og_tags, strip_html_tags

BASE_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>AgBlogger</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>"""


class TestStripHtmlTags:
    def test_strips_tags(self) -> None:
        assert strip_html_tags("<p>Hello <b>world</b></p>") == "Hello world"

    def test_decodes_entities(self) -> None:
        assert strip_html_tags("&amp; &lt;tag&gt;") == "& <tag>"

    def test_empty_string(self) -> None:
        assert strip_html_tags("") == ""

    def test_plain_text_unchanged(self) -> None:
        assert strip_html_tags("no tags here") == "no tags here"

    def test_collapses_whitespace(self) -> None:
        assert strip_html_tags("<p>a</p>  <p>b</p>") == "a b"


class TestInjectOgTags:
    def test_injects_og_title(self) -> None:
        result = inject_og_tags(BASE_HTML, title="My Post", description="desc", url="https://example.com/post/x")
        assert '<meta property="og:title" content="My Post" />' in result

    def test_injects_og_description(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="A description", url="https://example.com/post/x")
        assert '<meta property="og:description" content="A description" />' in result

    def test_injects_og_url(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="https://example.com/post/x")
        assert '<meta property="og:url" content="https://example.com/post/x" />' in result

    def test_injects_og_type_article(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="https://example.com/post/x")
        assert '<meta property="og:type" content="article" />' in result

    def test_injects_twitter_card(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="https://example.com/post/x")
        assert '<meta name="twitter:card" content="summary" />' in result

    def test_injects_site_name(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="u", site_name="My Blog")
        assert '<meta property="og:site_name" content="My Blog" />' in result

    def test_injects_author(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="u", author="Alice")
        assert '<meta property="article:author" content="Alice" />' in result

    def test_omits_author_when_none(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="u")
        assert "article:author" not in result

    def test_injects_published_time(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="u", published_time="2026-01-01T00:00:00Z")
        assert '<meta property="article:published_time" content="2026-01-01T00:00:00Z" />' in result

    def test_injects_modified_time(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="u", modified_time="2026-01-02T00:00:00Z")
        assert '<meta property="article:modified_time" content="2026-01-02T00:00:00Z" />' in result

    def test_updates_html_title(self) -> None:
        result = inject_og_tags(BASE_HTML, title="My Post", description="D", url="u")
        assert "<title>My Post</title>" in result
        assert "<title>AgBlogger</title>" not in result

    def test_escapes_html_in_title(self) -> None:
        result = inject_og_tags(BASE_HTML, title='He said "hello" & <goodbye>', description="D", url="u")
        assert 'content="He said &quot;hello&quot; &amp; &lt;goodbye&gt;"' in result

    def test_escapes_html_in_description(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description='a "quote" & <tag>', url="u")
        assert 'og:description" content="a &quot;quote&quot; &amp; &lt;tag&gt;"' in result

    def test_truncates_long_description(self) -> None:
        long_desc = "x" * 500
        result = inject_og_tags(BASE_HTML, title="T", description=long_desc, url="u")
        # OG description should be truncated to ~200 chars + ellipsis
        assert "x" * 197 + "..." in result

    def test_preserves_rest_of_html(self) -> None:
        result = inject_og_tags(BASE_HTML, title="T", description="D", url="u")
        assert '<div id="root"></div>' in result
        assert '<meta charset="UTF-8" />' in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_opengraph_service.py -v`
Expected: FAIL (module not found)

**Step 3: Implement the service**

Create `backend/services/opengraph_service.py`:

```python
"""Open Graph meta tag injection for social media link previews."""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_DESCRIPTION_LENGTH = 200


def strip_html_tags(text: str) -> str:
    """Strip HTML tags and decode entities, collapsing whitespace."""
    clean = _TAG_RE.sub(" ", text)
    clean = _WHITESPACE_RE.sub(" ", clean)
    return html.unescape(clean).strip()


def _truncate(text: str, max_length: int = _MAX_DESCRIPTION_LENGTH) -> str:
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def inject_og_tags(
    base_html: str,
    *,
    title: str,
    description: str,
    url: str,
    site_name: str = "",
    author: str | None = None,
    published_time: str | None = None,
    modified_time: str | None = None,
) -> str:
    """Inject Open Graph and Twitter Card meta tags into HTML <head>."""
    desc = _truncate(description)
    tags = [
        f'<meta property="og:title" content="{html.escape(title)}" />',
        f'<meta property="og:description" content="{html.escape(desc)}" />',
        f'<meta property="og:url" content="{html.escape(url)}" />',
        f'<meta property="og:type" content="article" />',
        f'<meta name="twitter:card" content="summary" />',
        f'<meta name="twitter:title" content="{html.escape(title)}" />',
        f'<meta name="twitter:description" content="{html.escape(desc)}" />',
    ]
    if site_name:
        tags.append(f'<meta property="og:site_name" content="{html.escape(site_name)}" />')
    if author is not None:
        tags.append(f'<meta property="article:author" content="{html.escape(author)}" />')
    if published_time is not None:
        tags.append(
            f'<meta property="article:published_time" content="{html.escape(published_time)}" />'
        )
    if modified_time is not None:
        tags.append(
            f'<meta property="article:modified_time" content="{html.escape(modified_time)}" />'
        )

    og_block = "\n    ".join(tags)
    result = re.sub(r"<title>[^<]*</title>", f"<title>{html.escape(title)}</title>", base_html)
    return result.replace("</head>", f"    {og_block}\n  </head>")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_services/test_opengraph_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/services/opengraph_service.py tests/test_services/test_opengraph_service.py
git commit -m "feat: add OG tag injection service with tests"
```

---

### Task 2: Add the `/post/{path}` route

**Files:**
- Modify: `backend/main.py` (add route before StaticFiles mount)
- Test: `tests/test_api/test_opengraph.py`

**Step 1: Write failing integration tests**

Create `tests/test_api/test_opengraph.py`:

```python
"""Integration tests for Open Graph meta tag serving on /post/ routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import get_test_app_url


@pytest.mark.usefixtures("seed_post")
class TestPostOgTags:
    async def test_post_page_contains_og_title(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/hello.md")
        assert resp.status_code == 200
        assert 'og:title' in resp.text

    async def test_post_page_contains_og_description(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/hello.md")
        assert 'og:description' in resp.text

    async def test_post_page_contains_twitter_card(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/hello.md")
        assert 'twitter:card' in resp.text

    async def test_post_page_updates_html_title(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/hello.md")
        assert "<title>Hello World</title>" in resp.text

    async def test_post_page_contains_og_type_article(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/hello.md")
        assert 'og:type" content="article"' in resp.text

    async def test_missing_post_returns_plain_html(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/nonexistent.md")
        assert resp.status_code == 200
        assert "og:title" not in resp.text

    async def test_draft_post_returns_plain_html(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        # Create a draft post
        resp = await client.post(
            "/api/posts",
            json={"title": "Draft Post", "body": "Secret content", "is_draft": True},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        # OG tags should NOT be injected for drafts
        resp = await client.get(f"/post/{file_path}")
        assert resp.status_code == 200
        assert "og:title" not in resp.text

    async def test_response_content_type_is_html(self, client: AsyncClient) -> None:
        resp = await client.get("/post/posts/hello.md")
        assert "text/html" in resp.headers.get("content-type", "")
```

Note: This test file relies on existing test fixtures (`client`, `seed_post`, `admin_token`) from the test suite's `conftest.py`. Examine `tests/conftest.py` to verify the exact fixture names and adapt if needed.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_opengraph.py -v`
Expected: FAIL (route returns 404 or unmodified HTML)

**Step 3: Add the route in `main.py`**

In `backend/main.py`, add the `/post/{path}` route just before the `StaticFiles` mount (before `if frontend_dir.exists():`). The route needs:
- Read `index.html` from `frontend_dir` (cache it in `app.state`)
- Query `PostCache` for the post metadata
- If post is found and not draft: inject OG tags and return
- Otherwise: return plain `index.html`

Add these imports at the top of `main.py`:
```python
from fastapi.responses import HTMLResponse
```

Add this block in `create_app()` just before `# Serve frontend static files in production`:

```python
    # Serve /post/{path} with Open Graph meta tags for social media link previews
    @app.get("/post/{file_path:path}", response_class=HTMLResponse, include_in_schema=False)
    async def post_with_og_tags(
        file_path: str,
        request: Request,
    ) -> HTMLResponse:
        from backend.services.opengraph_service import inject_og_tags, strip_html_tags

        frontend_dir_path: Path = request.app.state.settings.frontend_dir
        index_path = frontend_dir_path / "index.html"

        # Read and cache the base index.html
        base_html: str | None = getattr(request.app.state, "_og_base_html", None)
        if base_html is None:
            try:
                base_html = index_path.read_text(encoding="utf-8")
                request.app.state._og_base_html = base_html
            except OSError:
                logger.warning("index.html not found at %s", index_path)
                return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        # Look up the post in the cache
        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                from backend.models.post import PostCache

                stmt = select(PostCache).where(PostCache.file_path == file_path)
                result = await session.execute(stmt)
                post = result.scalar_one_or_none()
        except Exception:
            logger.exception("DB error looking up post for OG tags: %s", file_path)
            return HTMLResponse(base_html)

        if post is None or post.is_draft:
            return HTMLResponse(base_html)

        description = ""
        if post.rendered_excerpt:
            description = strip_html_tags(post.rendered_excerpt)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title

        from backend.services.datetime_service import format_iso

        enriched = inject_og_tags(
            base_html,
            title=post.title,
            description=description,
            url=str(request.url),
            site_name=site_name,
            author=post.author,
            published_time=format_iso(post.created_at),
            modified_time=format_iso(post.modified_at),
        )
        return HTMLResponse(enriched)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api/test_opengraph.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_opengraph.py
git commit -m "feat: serve OG meta tags on /post/ pages for social link previews"
```

---

### Task 3: Update architecture docs

**Files:**
- Modify: `docs/arch/backend.md`
- Modify: `docs/arch/data-flow.md`

**Step 1: Add OG meta tags section to `docs/arch/backend.md`**

Add after the "Rendering Pipeline" section:

```markdown
## Open Graph Meta Tags

Post pages (`/post/{file_path}`) are served with Open Graph and Twitter Card meta tags injected into the SPA's `index.html`. This enables rich link previews on social media (Facebook, LinkedIn, Slack, Discord, iMessage, etc.).

The route queries `PostCache` for the post's title, excerpt, author, and timestamps. The excerpt HTML is stripped to plain text for the `og:description` tag. Drafts and missing posts receive the unmodified `index.html` so no metadata is leaked. The base `index.html` is cached in `app.state` after first read.

Tags injected: `og:title`, `og:description`, `og:url`, `og:type` (article), `og:site_name`, `article:author`, `article:published_time`, `article:modified_time`, `twitter:card` (summary), `twitter:title`, `twitter:description`.
```

**Step 2: Add OG flow to `docs/arch/data-flow.md`**

Add a new section:

```markdown
## Viewing a Post (Social Media Crawler)

```
GET /post/{file_path}
    → Query PostCache by file_path
    → If found and not draft:
        → Strip HTML from rendered_excerpt for description
        → Read site_config.title for og:site_name
        → inject_og_tags() into cached index.html
        → Return enriched HTML (SPA boots normally)
    → If not found or draft:
        → Return unmodified index.html
```
```

**Step 3: Commit**

```bash
git add docs/arch/backend.md docs/arch/data-flow.md
git commit -m "docs: document OG meta tag architecture"
```

---

### Task 4: Run full check

**Step 1: Run `just check`**

Run: `just check`
Expected: All static checks and tests pass.
