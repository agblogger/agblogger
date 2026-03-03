"""Tests for the page service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.filesystem.content_manager import ContentManager
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
    async def test_returns_none_for_nonexistent_page_id(self, cm: ContentManager) -> None:
        result = await get_page(cm, "nonexistent")
        assert result is None

    async def test_returns_empty_html_for_timeline(self, cm: ContentManager) -> None:
        result = await get_page(cm, "timeline")
        assert result is not None
        assert result.id == "timeline"
        assert result.title == "Posts"
        assert result.rendered_html == ""

    async def test_returns_none_when_page_has_no_file(self, cm: ContentManager) -> None:
        result = await get_page(cm, "nofile")
        assert result is None

    async def test_returns_none_when_file_does_not_exist(
        self, content_dir: Path, cm: ContentManager
    ) -> None:
        # Remove the about.md file so it exists in config but not on disk
        (content_dir / "about.md").unlink()
        result = await get_page(cm, "about")
        assert result is None

    async def test_returns_rendered_html_for_valid_page(self, cm: ContentManager) -> None:
        with patch(
            "backend.services.page_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<h1>About</h1>\n<p>About page content.</p>",
        ):
            result = await get_page(cm, "about")
        assert result is not None
        assert result.id == "about"
        assert result.title == "About"
        assert "<h1>About</h1>" in result.rendered_html
