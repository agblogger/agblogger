"""Tests for admin service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import PageConfig, SiteConfig, parse_site_config
from backend.services.admin_service import (
    create_page,
    delete_page,
    get_admin_pages,
    get_site_settings,
    update_page_order,
    update_site_settings,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    d = tmp_path / "content"
    d.mkdir()
    (d / "posts").mkdir()
    (d / "index.toml").write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n\n'
        '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
    )
    (d / "labels.toml").write_text("[labels]\n")
    (d / "about.md").write_text("# About\n\nAbout page content.\n")
    return d


@pytest.fixture
def cm(content_dir: Path) -> ContentManager:
    return ContentManager(content_dir=content_dir)


class TestGetSiteSettings:
    def test_returns_current_settings(self, cm: ContentManager) -> None:
        result = get_site_settings(cm)
        assert result.title == "Test Blog"
        assert result.timezone == "UTC"


class TestUpdateSiteSettings:
    def test_updates_settings(self, cm: ContentManager) -> None:
        result = update_site_settings(
            cm,
            title="New Title",
            description="desc",
            timezone="US/Eastern",
        )
        assert result.title == "New Title"
        assert result.description == "desc"

        reloaded = parse_site_config(cm.content_dir)
        assert reloaded.title == "New Title"

    def test_preserves_pages(self, cm: ContentManager) -> None:
        update_site_settings(cm, title="Changed", description="", timezone="UTC")
        reloaded = parse_site_config(cm.content_dir)
        assert len(reloaded.pages) == 3


class TestGetAdminPages:
    def test_returns_pages_with_content(self, cm: ContentManager) -> None:
        pages = get_admin_pages(cm)
        assert len(pages) == 3
        assert pages[0]["id"] == "timeline"
        assert pages[0]["is_builtin"] is True
        assert pages[1]["id"] == "about"
        assert pages[1]["content"] == "# About\n\nAbout page content.\n"
        assert pages[2]["id"] == "labels"
        assert pages[2]["is_builtin"] is True


class TestCreatePage:
    def test_creates_page(self, cm: ContentManager) -> None:
        result = create_page(cm, page_id="contact", title="Contact")
        assert result.id == "contact"
        assert (cm.content_dir / "contact.md").exists()

        reloaded = parse_site_config(cm.content_dir)
        assert any(p.id == "contact" for p in reloaded.pages)

    def test_duplicate_id_raises(self, cm: ContentManager) -> None:
        with pytest.raises(ValueError, match="already exists"):
            create_page(cm, page_id="about", title="About 2")

    def test_reserved_builtin_id_raises(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        cm = ContentManager(content_dir=content_dir)

        with pytest.raises(ValueError, match="reserved"):
            create_page(cm, page_id="labels", title="Labels")

        assert not (content_dir / "labels.md").exists()


class TestDeletePage:
    def test_deletes_page_and_file(self, cm: ContentManager) -> None:
        delete_page(cm, page_id="about", delete_file=True)
        reloaded = parse_site_config(cm.content_dir)
        assert not any(p.id == "about" for p in reloaded.pages)
        assert not (cm.content_dir / "about.md").exists()

    def test_deletes_page_keeps_file(self, cm: ContentManager) -> None:
        delete_page(cm, page_id="about", delete_file=False)
        reloaded = parse_site_config(cm.content_dir)
        assert not any(p.id == "about" for p in reloaded.pages)
        assert (cm.content_dir / "about.md").exists()

    def test_delete_builtin_raises(self, cm: ContentManager) -> None:
        with pytest.raises(ValueError, match="Cannot delete built-in"):
            delete_page(cm, page_id="timeline", delete_file=False)

    def test_delete_nonexistent_raises(self, cm: ContentManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            delete_page(cm, page_id="nope", delete_file=False)


class TestUpdateSiteSettingsWriteError:
    def test_write_error_propagates(self, cm: ContentManager) -> None:
        with (
            patch(
                "backend.filesystem.toml_manager.tempfile.mkstemp",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError, match="disk full"),
        ):
            update_site_settings(
                cm,
                title="New Title",
                description="desc",
                timezone="UTC",
            )


class TestDeletePageUnlinkError:
    def test_unlink_error_logged_not_raised(
        self, cm: ContentManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """File deletion errors are logged as warnings (config is already updated)."""
        about_path = cm.content_dir / "about.md"
        with (
            patch.object(type(about_path), "unlink", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING),
        ):
            delete_page(cm, page_id="about", delete_file=True)
        assert any("permission denied" in r.message for r in caplog.records)


class TestUpdatePageOrder:
    def test_reorders_pages(self, cm: ContentManager) -> None:
        new_order = [
            PageConfig(id="labels", title="Tags"),
            PageConfig(id="timeline", title="Home"),
            PageConfig(id="about", title="About", file="about.md"),
        ]
        update_page_order(cm, new_order)
        reloaded = parse_site_config(cm.content_dir)
        assert [p.id for p in reloaded.pages] == ["labels", "timeline", "about"]
        assert reloaded.pages[0].title == "Tags"
        assert reloaded.pages[1].title == "Home"


class TestPageOrderItemValidation:
    """PageOrderItem.file must reject path traversal."""

    def test_rejects_path_traversal_dotdot(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="test", title="Test", file="../../.env")

    def test_rejects_absolute_path(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="test", title="Test", file="/etc/passwd")

    def test_accepts_valid_relative_path(self) -> None:
        from backend.schemas.admin import PageOrderItem

        item = PageOrderItem(id="about", title="About", file="about.md")
        assert item.file == "about.md"

    def test_accepts_none_file(self) -> None:
        from backend.schemas.admin import PageOrderItem

        item = PageOrderItem(id="timeline", title="Timeline", file=None)
        assert item.file is None


class TestSiteConfigWithPages:
    """SiteConfig.with_pages() should return a copy with replaced pages."""

    def test_with_pages_returns_new_config(self) -> None:
        cfg = SiteConfig(
            title="Blog",
            description="Desc",
            timezone="UTC",
            pages=[PageConfig(id="p1", title="Page 1")],
        )
        new_pages = [PageConfig(id="p2", title="Page 2")]
        result = cfg.with_pages(new_pages)

        assert result.title == "Blog"
        assert result.description == "Desc"
        assert result.timezone == "UTC"
        assert len(result.pages) == 1
        assert result.pages[0].id == "p2"
        # Original unchanged
        assert len(cfg.pages) == 1
        assert cfg.pages[0].id == "p1"
