# Page HTML Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache pandoc-rendered HTML for top-level pages in the database so read requests never invoke pandoc.

**Architecture:** Add a `PageCache` CacheBase model populated during `rebuild_cache` and on admin create/update mutations. The read path (`get_page`) queries the DB instead of rendering. Pages without backing files (`file=None`) have no cache row and return `None` (404) — the frontend never requests these since builtins route to their own components.

**Tech Stack:** SQLAlchemy (CacheBase), FastAPI, pandoc renderer (existing)

---

### Task 1: Add PageCache model

**Files:**
- Create: `backend/models/page.py`
- Modify: `backend/models/base.py:20-25` (update CacheBase docstring)

- [ ] **Step 1: Create the PageCache model**

```python
# backend/models/page.py
"""Page cache model."""

from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import CacheBase


class PageCache(CacheBase):
    """Cached rendered HTML for top-level pages (regenerated from filesystem)."""

    __tablename__ = "pages_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_html: Mapped[str] = mapped_column(Text, nullable=False)
```

- [ ] **Step 2: Update CacheBase docstring**

In `backend/models/base.py`, update the `CacheBase` docstring to include `pages_cache`:

```python
class CacheBase(DeclarativeBase):
    """Base class for cache tables dropped and regenerated on startup.

    Tables: posts_cache, pages_cache, labels_cache, label_parents_cache,
    post_labels_cache, sync_manifest.
    """
```

- [ ] **Step 3: Commit**

```bash
git add backend/models/page.py backend/models/base.py
git commit -m "feat: add PageCache model for cached page HTML"
```

---

### Task 2: Populate PageCache during rebuild_cache

**Files:**
- Modify: `backend/services/cache_service.py`
- Modify: `tests/test_services/test_cache_rebuild_resilience.py`

- [ ] **Step 1: Write failing test — pages are cached during rebuild**

Add to `tests/test_services/test_cache_rebuild_resilience.py`:

```python
from backend.models.page import PageCache

class TestPageCacheRebuild:
    """Test that rebuild_cache populates PageCache for file-backed pages."""

    async def test_rebuild_caches_file_backed_pages(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        (content_dir / "about.md").write_text("# About\n\nHello.\n")
        cm = ContentManager(content_dir=content_dir)

        with patch(
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<h1>About</h1>\n<p>Hello.</p>",
        ):
            await rebuild_cache(session_factory, cm)

        async with session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 1
            assert pages[0].page_id == "about"
            assert pages[0].title == "About"
            assert "<h1>About</h1>" in pages[0].rendered_html

    async def test_rebuild_skips_pages_without_file(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        cm = ContentManager(content_dir=content_dir)

        await rebuild_cache(session_factory, cm)

        async with session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 0

    async def test_rebuild_skips_page_with_missing_file(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "T"\ndescription = "D"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        # about.md intentionally not created
        cm = ContentManager(content_dir=content_dir)

        await rebuild_cache(session_factory, cm)

        async with session_factory() as session:
            pages = (await session.execute(select(PageCache))).scalars().all()
            assert len(pages) == 0
```

These tests need the `session_factory` fixture. Check the existing test file — it already uses one from `conftest.py`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_cache_rebuild_resilience.py::TestPageCacheRebuild -v
```

Expected: FAIL — `PageCache` not imported / not populated.

- [ ] **Step 3: Implement — populate PageCache in rebuild_cache**

In `backend/services/cache_service.py`, add the import:

```python
from backend.models.page import PageCache
```

Add a `delete(PageCache)` call alongside the other cache clears at the top of `rebuild_cache`. Then, after the label setup block and before the post scan, add:

```python
        # Render and cache file-backed pages
        await session.execute(delete(PageCache))
        for page_cfg in content_manager.site_config.pages:
            if page_cfg.file is None:
                continue
            raw = content_manager.read_page(page_cfg.id)
            if raw is None:
                logger.warning("Skipping page %s: file not found", page_cfg.id)
                continue
            try:
                page_html = await render_markdown(raw)
            except RuntimeError as exc:
                logger.warning("Skipping page %s: %s", page_cfg.id, exc)
                continue
            session.add(
                PageCache(page_id=page_cfg.id, title=page_cfg.title, rendered_html=page_html)
            )
        await session.flush()
```

Note: place the `delete(PageCache)` alongside the other deletes at the top, and place the page-rendering loop after labels are flushed but before the post scan.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_cache_rebuild_resilience.py::TestPageCacheRebuild -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/cache_service.py tests/test_services/test_cache_rebuild_resilience.py
git commit -m "feat: populate PageCache during rebuild_cache"
```

---

### Task 3: Read page HTML from cache instead of rendering

**Files:**
- Modify: `backend/services/page_service.py`
- Modify: `backend/api/pages.py`
- Modify: `tests/test_services/test_page_service.py`

- [ ] **Step 1: Write failing tests — get_page reads from DB**

Replace the existing `TestGetPage` tests in `tests/test_services/test_page_service.py`. The new `get_page` will accept a `session_factory` instead of calling pandoc. Tests need a DB session with pre-populated `PageCache` rows.

```python
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.filesystem.content_manager import ContentManager
from backend.models.page import PageCache
from backend.schemas.page import PageConfig, PageResponse
from backend.services.cache_service import ensure_tables
from backend.services.page_service import get_page, get_site_config


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await ensure_tables(session)
    yield factory
    await engine.dispose()


class TestGetPage:
    async def test_returns_none_for_nonexistent_page_id(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        result = await get_page(session_factory, cm, "nonexistent")
        assert result is None

    async def test_returns_none_for_page_without_file(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # "timeline" and "nofile" pages have file=None — no cache row, returns None
        result = await get_page(session_factory, cm, "timeline")
        assert result is None

    async def test_returns_cached_html(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # Pre-populate cache
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<h1>About</h1>"))
            await session.commit()

        result = await get_page(session_factory, cm, "about")
        assert result is not None
        assert result.rendered_html == "<h1>About</h1>"
        assert result.title == "About"

    async def test_returns_none_when_page_not_in_cache(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # "about" is in config with a file, but no cache row exists
        result = await get_page(session_factory, cm, "about")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_page_service.py::TestGetPage -v
```

Expected: FAIL — `get_page` signature doesn't accept `session_factory`.

- [ ] **Step 3: Implement — rewrite get_page to read from DB**

Update `backend/services/page_service.py`:

```python
"""Page service: top-level page retrieval and rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.models.page import PageCache
from backend.schemas.page import PageConfig, PageResponse, SiteConfigResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.filesystem.content_manager import ContentManager


def get_site_config(content_manager: ContentManager) -> SiteConfigResponse:
    """Get the site configuration for the frontend."""
    cfg = content_manager.site_config
    return SiteConfigResponse(
        title=cfg.title,
        description=cfg.description,
        pages=[PageConfig(id=p.id, title=p.title, file=p.file) for p in cfg.pages],
    )


async def get_page(
    session_factory: async_sessionmaker[AsyncSession],
    content_manager: ContentManager,
    page_id: str,
) -> PageResponse | None:
    """Get a top-level page from the cache."""
    cfg = content_manager.site_config
    page_cfg = next((p for p in cfg.pages if p.id == page_id), None)
    if page_cfg is None:
        return None

    if page_cfg.file is None:
        return None

    async with session_factory() as session:
        row = (
            await session.execute(select(PageCache).where(PageCache.page_id == page_id))
        ).scalar_one_or_none()

    if row is None:
        return None

    return PageResponse(id=page_id, title=row.title, rendered_html=row.rendered_html)
```

- [ ] **Step 4: Update the API endpoint to pass session_factory**

In `backend/api/pages.py`, update `get_page_endpoint`:

- Remove the `RenderError` import and its `try/except` block.
- Pass `session_factory` as the first argument to `get_page`.

```python
@router.get("/{page_id}", response_model=PageResponse)
async def get_page_endpoint(
    page_id: str,
    request: Request,
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    user: Annotated[AdminUser | None, Depends(get_current_admin)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
) -> PageResponse:
    """Get a top-level page with rendered HTML."""
    if not _PAGE_ID_PATTERN.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page ID")
    page = await get_page(session_factory, content_manager, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fire_background_hit(
        request=request,
        session_factory=session_factory,
        path=f"/page/{page_id}",
        user=user,
    )
    return page
```

Remove unused imports: `RenderError` from `backend.pandoc.renderer`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_page_service.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/page_service.py backend/api/pages.py tests/test_services/test_page_service.py
git commit -m "feat: read page HTML from cache instead of rendering on read"
```

---

### Task 4: Cache page HTML on create and update

**Files:**
- Modify: `backend/services/admin_service.py`
- Modify: `backend/api/admin.py`
- Modify: `tests/test_services/test_admin_service.py`

- [ ] **Step 1: Write failing tests — create_page renders and caches**

Add to `tests/test_services/test_admin_service.py`:

```python
from backend.models.page import PageCache
from sqlalchemy import select

class TestCreatePageCache:
    async def test_create_page_caches_rendered_html(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with patch(
            "backend.services.admin_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<h1>New Page</h1>\n",
        ):
            await create_page(session_factory, cm, page_id="newpage", title="New Page")

        async with session_factory() as session:
            row = (
                await session.execute(
                    select(PageCache).where(PageCache.page_id == "newpage")
                )
            ).scalar_one_or_none()
            assert row is not None
            assert row.rendered_html == "<h1>New Page</h1>\n"
            assert row.title == "New Page"
```

- [ ] **Step 2: Write failing test — update_page re-renders and updates cache**

```python
class TestUpdatePageCache:
    async def test_update_content_re_renders_cache(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # Seed cache row
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>old</p>"))
            await session.commit()

        with patch(
            "backend.services.admin_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<p>new</p>",
        ):
            await update_page(session_factory, cm, "about", content="new content")

        async with session_factory() as session:
            row = (
                await session.execute(
                    select(PageCache).where(PageCache.page_id == "about")
                )
            ).scalar_one_or_none()
            assert row is not None
            assert row.rendered_html == "<p>new</p>"

    async def test_update_title_updates_cache_title(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>x</p>"))
            await session.commit()

        with patch(
            "backend.services.admin_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<p>x</p>",
        ):
            await update_page(session_factory, cm, "about", title="About Us")

        async with session_factory() as session:
            row = (
                await session.execute(
                    select(PageCache).where(PageCache.page_id == "about")
                )
            ).scalar_one_or_none()
            assert row is not None
            assert row.title == "About Us"
```

- [ ] **Step 3: Write failing test — delete_page removes cache row**

```python
class TestDeletePageCache:
    async def test_delete_page_removes_cache_row(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>x</p>"))
            await session.commit()

        await delete_page(session_factory, cm, "about", delete_file=True)

        async with session_factory() as session:
            row = (
                await session.execute(
                    select(PageCache).where(PageCache.page_id == "about")
                )
            ).scalar_one_or_none()
            assert row is None
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_admin_service.py::TestCreatePageCache tests/test_services/test_admin_service.py::TestUpdatePageCache tests/test_services/test_admin_service.py::TestDeletePageCache -v
```

Expected: FAIL — `create_page`/`update_page`/`delete_page` don't accept `session_factory`.

- [ ] **Step 5: Implement — make admin service functions async with caching**

Update `backend/services/admin_service.py`:

Add imports:
```python
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.page import PageCache
from backend.pandoc.renderer import render_markdown
```

Change `create_page` to `async def create_page(session_factory, cm, *, page_id, title)`:
- After writing the file and reloading config, read the file content, render via pandoc, and insert a `PageCache` row.

Change `update_page` to `async def update_page(session_factory, cm, page_id, *, title=None, content=None)`:
- After the filesystem writes, read the current file content, re-render, and upsert the cache row (delete old + insert new).
- If only title changed (no content change), still re-read and re-render since the cache row title must match.

Change `delete_page` to `async def delete_page(session_factory, cm, page_id, *, delete_file)`:
- After config/file changes, delete the `PageCache` row for this page_id.

- [ ] **Step 6: Update admin API endpoints to pass session_factory**

In `backend/api/admin.py`:

- Add `get_session_factory` to the deps import.
- Add `session_factory` parameter (via `Depends(get_session_factory)`) to `create_page_endpoint`, `update_page_endpoint`, and `delete_page_endpoint`.
- Pass `session_factory` as the first argument to the service calls.
- Update existing tests for `create_page`, `delete_page` that call them directly (in `test_admin_service.py`) — they need a `session_factory` fixture and must `await` the calls.

- [ ] **Step 7: Update existing admin_service tests to async**

Existing tests that call `create_page`, `update_page`, `delete_page` must become async and pass `session_factory`. Add a `session_factory` fixture to the test file (same pattern as other test files). Mock `render_markdown` in each test that calls create/update.

- [ ] **Step 8: Run all admin service tests**

```bash
uv run pytest tests/test_services/test_admin_service.py -v
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/services/admin_service.py backend/api/admin.py tests/test_services/test_admin_service.py
git commit -m "feat: cache page HTML on create, update, and delete"
```

---

### Task 5: Update conftest renderer patch sites

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add admin_service to renderer patch sites**

In `tests/conftest.py`, add `"backend.services.admin_service"` to `_RENDER_MARKDOWN_IMPORT_SITES`:

```python
_RENDER_MARKDOWN_IMPORT_SITES = (
    "backend.services.cache_service",
    "backend.services.admin_service",
    "backend.services.page_service",
    "backend.api.posts",
    "backend.api.render",
)
```

Note: `page_service` no longer imports `render_markdown`, so it can be removed from this tuple. But since it's harmless and the restore function checks `hasattr`, leave it for now — or remove it if you prefer.

- [ ] **Step 2: Run the full test suite for affected files**

```bash
uv run pytest tests/test_services/test_page_service.py tests/test_services/test_admin_service.py tests/test_services/test_cache_rebuild_resilience.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "fix: add admin_service to renderer patch sites in conftest"
```

---

### Task 6: Run full quality gate

- [ ] **Step 1: Run just check**

```bash
just check
```

Expected: all static checks and tests pass.

- [ ] **Step 2: Fix any issues found**

Address type errors, lint issues, or test failures.

- [ ] **Step 3: Update architecture docs**

Update `docs/arch/backend.md` and `docs/arch/data-flow.md` to mention `pages_cache` alongside `posts_cache` where relevant. Update `backend/models/base.py` CacheBase docstring if not already done.

- [ ] **Step 4: Commit**

```bash
git add docs/arch/ backend/models/base.py
git commit -m "docs: update architecture docs for page cache"
```
