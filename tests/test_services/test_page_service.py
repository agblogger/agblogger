"""Tests for the page service."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.filesystem.content_manager import ContentManager
from backend.models.page import PageCache
from backend.services.cache_service import ensure_tables
from backend.services.page_service import get_page, get_site_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    d = tmp_path / "content"
    d.mkdir()
    (d / "posts").mkdir()
    (d / "index.toml").write_text(
        '[site]\ntitle = "Test Blog"\ndescription = "A test blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n\n'
        '[[pages]]\nid = "nofile"\ntitle = "No File Page"\n'
    )
    (d / "labels.toml").write_text("[labels]\n")
    (d / "about.md").write_text("# About\n\nAbout page content.\n")
    return d


@pytest.fixture
def cm(content_dir: Path) -> ContentManager:
    return ContentManager(content_dir=content_dir)


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await ensure_tables(session)
    yield factory  # type: ignore[misc]
    await engine.dispose()


class TestGetSiteConfig:
    def test_returns_correct_title_and_description(self, cm: ContentManager) -> None:
        result = get_site_config(cm)
        assert result.title == "Test Blog"
        assert result.description == "A test blog"

    def test_returns_pages(self, cm: ContentManager) -> None:
        result = get_site_config(cm)
        page_ids = [p.id for p in result.pages]
        assert "timeline" in page_ids
        assert "about" in page_ids
        assert "nofile" in page_ids


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
