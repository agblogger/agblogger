"""Tests for admin service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.exceptions import InternalServerError
from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import (
    PageConfig,
    SiteConfig,
    parse_site_config,
    write_site_config,
)
from backend.models.page import PageCache
from backend.services.admin_service import (
    create_page,
    delete_page,
    get_admin_pages,
    get_site_settings,
    remove_favicon,
    remove_image,
    set_favicon,
    set_image,
    update_page,
    update_page_order,
    update_site_settings,
)
from backend.services.cache_service import ensure_tables
from backend.services.page_service import get_page
from backend.services.storage_quota import ContentSizeTracker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await ensure_tables(session)
    yield factory
    await engine.dispose()


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

    def test_preserves_image_on_settings_update(self, cm: ContentManager) -> None:
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                image="assets/image.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        update_site_settings(cm, title="Changed", description="", timezone="UTC")

        reloaded = parse_site_config(cm.content_dir)
        assert reloaded.image == "assets/image.png"

    def test_preserves_favicon_on_settings_update(self, cm: ContentManager) -> None:
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                favicon="assets/favicon.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        update_site_settings(cm, title="Changed", description="", timezone="UTC")

        reloaded = parse_site_config(cm.content_dir)
        assert reloaded.favicon == "assets/favicon.png"


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
    async def test_creates_page(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with patch(
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<p>rendered</p>",
        ):
            result = await create_page(session_factory, cm, page_id="contact", title="Contact")
        assert result.id == "contact"
        assert (cm.content_dir / "contact.md").exists()

        reloaded = parse_site_config(cm.content_dir)
        assert any(p.id == "contact" for p in reloaded.pages)

    async def test_duplicate_id_raises(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with pytest.raises(ValueError, match="already exists"):
            await create_page(session_factory, cm, page_id="about", title="About 2")

    async def test_path_traversal_in_page_id_rejected(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with pytest.raises(OSError):
            await create_page(session_factory, cm, page_id="../../../etc/passwd", title="Evil")

    async def test_reserved_builtin_id_raises(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")
        local_cm = ContentManager(content_dir=content_dir)

        with pytest.raises(ValueError, match="reserved"):
            await create_page(session_factory, local_cm, page_id="labels", title="Labels")

        assert not (content_dir / "labels.md").exists()


class TestDeletePage:
    async def test_deletes_page_and_file(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await delete_page(session_factory, cm, page_id="about", delete_file=True)
        reloaded = parse_site_config(cm.content_dir)
        assert not any(p.id == "about" for p in reloaded.pages)
        assert not (cm.content_dir / "about.md").exists()

    async def test_deletes_page_keeps_file(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await delete_page(session_factory, cm, page_id="about", delete_file=False)
        reloaded = parse_site_config(cm.content_dir)
        assert not any(p.id == "about" for p in reloaded.pages)
        assert (cm.content_dir / "about.md").exists()

    async def test_delete_builtin_raises(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with pytest.raises(ValueError, match="Cannot delete built-in"):
            await delete_page(session_factory, cm, page_id="timeline", delete_file=False)

    async def test_delete_nonexistent_raises(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            await delete_page(session_factory, cm, page_id="nope", delete_file=False)


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
    async def test_unlink_error_logged_not_raised(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """File deletion errors are logged as warnings (config is already updated)."""
        about_path = cm.content_dir / "about.md"
        with (
            patch.object(type(about_path), "unlink", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING),
        ):
            await delete_page(session_factory, cm, page_id="about", delete_file=True)
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

    def test_rejects_empty_id(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="", title="Test")

    def test_rejects_id_too_long(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="a" * 51, title="Test")

    def test_rejects_id_with_uppercase(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="MyPage", title="Test")

    def test_rejects_id_with_spaces(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="my page", title="Test")

    def test_rejects_id_starting_with_hyphen(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="-mypage", title="Test")

    def test_rejects_id_starting_with_underscore(self) -> None:
        from pydantic import ValidationError

        from backend.schemas.admin import PageOrderItem

        with pytest.raises(ValidationError):
            PageOrderItem(id="_mypage", title="Test")

    def test_accepts_valid_id_alphanumeric(self) -> None:
        from backend.schemas.admin import PageOrderItem

        item = PageOrderItem(id="mypage123", title="Test")
        assert item.id == "mypage123"

    def test_accepts_valid_id_with_hyphen(self) -> None:
        from backend.schemas.admin import PageOrderItem

        item = PageOrderItem(id="my-page", title="Test")
        assert item.id == "my-page"

    def test_accepts_valid_id_with_underscore(self) -> None:
        from backend.schemas.admin import PageOrderItem

        item = PageOrderItem(id="my_page", title="Test")
        assert item.id == "my_page"

    def test_accepts_single_char_id(self) -> None:
        from backend.schemas.admin import PageOrderItem

        item = PageOrderItem(id="a", title="Test")
        assert item.id == "a"


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


class TestCreatePageCache:
    async def test_create_page_caches_rendered_html(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with patch(
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<h1>New Page</h1>\n",
        ):
            await create_page(session_factory, cm, page_id="newpage", title="New Page")

        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "newpage"))
            ).scalar_one_or_none()
            assert row is not None
            assert row.rendered_html == "<h1>New Page</h1>\n"
            assert row.title == "New Page"


class TestUpdatePageCache:
    async def test_update_content_re_renders_cache(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>old</p>"))
            await session.commit()

        with patch(
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<p>new</p>",
        ):
            await update_page(session_factory, cm, "about", content="new content")

        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "about"))
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
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            return_value="<p>x</p>",
        ):
            await update_page(session_factory, cm, "about", title="About Us")

        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "about"))
            ).scalar_one_or_none()
            assert row is not None
            assert row.title == "About Us"

    async def test_update_title_does_not_require_re_render(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>x</p>"))
            await session.commit()

        with patch(
            "backend.services.cache_service.render_markdown",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Pandoc crashed"),
        ):
            await update_page(session_factory, cm, "about", title="About Us")

        assert next(page for page in cm.site_config.pages if page.id == "about").title == "About Us"
        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "about"))
            ).scalar_one_or_none()
            assert row is not None
            assert row.title == "About Us"
            assert row.rendered_html == "<p>x</p>"


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
                await session.execute(select(PageCache).where(PageCache.page_id == "about"))
            ).scalar_one_or_none()
            assert row is None

    async def test_delete_page_keeps_cache_when_file_is_retained_and_restore_reuses_it(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>x</p>"))
            await session.commit()

        await delete_page(session_factory, cm, "about", delete_file=False)

        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "about"))
            ).scalar_one_or_none()
            assert row is not None
            assert row.rendered_html == "<p>x</p>"

        update_page_order(
            cm,
            [
                PageConfig(id="timeline", title="Posts"),
                PageConfig(id="about", title="About", file="about.md"),
                PageConfig(id="labels", title="Labels"),
            ],
        )

        result = await get_page(session_factory, cm, "about")
        assert result is not None
        assert result.title == "About"
        assert result.rendered_html == "<p>x</p>"


class TestCreatePageCacheRefreshFailure:
    """create_page must fail if the derived public page cannot be refreshed."""

    async def test_create_page_rolls_back_when_render_fails(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with (
            patch(
                "backend.services.cache_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Pandoc crashed"),
            ),
            pytest.raises(InternalServerError, match="Failed to refresh page cache"),
        ):
            await create_page(session_factory, cm, page_id="contact", title="Contact")

        assert not (cm.content_dir / "contact.md").exists()
        reloaded = parse_site_config(cm.content_dir)
        assert not any(page.id == "contact" for page in reloaded.pages)
        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "contact"))
            ).scalar_one_or_none()
            assert row is None

    async def test_create_page_logs_error_on_cache_refresh_failure(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with (
            patch(
                "backend.services.cache_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Pandoc crashed"),
            ),
            caplog.at_level(logging.ERROR),
            pytest.raises(InternalServerError, match="Failed to refresh page cache"),
        ):
            await create_page(session_factory, cm, page_id="faq", title="FAQ")
        assert any(
            "faq" in r.message.lower() and "cache" in r.message.lower() for r in caplog.records
        )


class TestUpdatePageCacheRefreshFailure:
    """update_page must fail if the derived public page cannot be refreshed."""

    async def test_update_page_rolls_back_when_render_fails(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # Pre-populate cache with old content
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>old</p>"))
            await session.commit()

        original_content = (cm.content_dir / "about.md").read_text(encoding="utf-8")
        with (
            patch(
                "backend.services.cache_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Pandoc crashed"),
            ),
            pytest.raises(InternalServerError, match="Failed to refresh page cache"),
        ):
            await update_page(
                session_factory,
                cm,
                "about",
                title="About Us",
                content="new content",
            )

        assert (cm.content_dir / "about.md").read_text(encoding="utf-8") == original_content
        assert next(page for page in cm.site_config.pages if page.id == "about").title == "About"

        async with session_factory() as session:
            row = (
                await session.execute(select(PageCache).where(PageCache.page_id == "about"))
            ).scalar_one_or_none()
            assert row is not None
            assert row.title == "About"
            assert row.rendered_html == "<p>old</p>"

    async def test_update_page_logs_error_on_cache_refresh_failure(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with (
            patch(
                "backend.services.cache_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Pandoc crashed"),
            ),
            caplog.at_level(logging.ERROR),
            pytest.raises(InternalServerError, match="Failed to refresh page cache"),
        ):
            await update_page(session_factory, cm, "about", content="updated")
        assert any(
            "about" in r.message.lower() and "cache" in r.message.lower() for r in caplog.records
        )


class TestDeletePageNoCacheRow:
    """delete_page should succeed even when no cache row exists."""

    async def test_delete_page_succeeds_without_cache_row(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # No cache row pre-populated — should not raise
        await delete_page(session_factory, cm, page_id="about", delete_file=True)
        reloaded = parse_site_config(cm.content_dir)
        assert not any(p.id == "about" for p in reloaded.pages)


class TestDeletePageQuotaTracking:
    """delete_page_endpoint must adjust the content_size_tracker after deletion."""

    async def test_delete_page_endpoint_adjusts_tracker(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After deleting a page, delete_page_endpoint must call adjust(-size) on the tracker."""
        from unittest.mock import AsyncMock, MagicMock

        from backend.api.admin import delete_page_endpoint
        from backend.models.user import AdminUser
        from backend.services.storage_quota import ContentSizeTracker

        # The about.md file already exists; record its size
        about_path = cm.content_dir / "about.md"
        expected_size = about_path.stat().st_size
        assert expected_size > 0

        tracker = ContentSizeTracker(content_dir=cm.content_dir, max_size=None)
        tracker.adjust(expected_size)  # simulate that tracker knows about the file

        response = MagicMock()
        response.headers = {}

        git_service = MagicMock()
        git_service.try_commit = AsyncMock(return_value="abc123")

        write_lock = MagicMock()
        write_lock.__aenter__ = AsyncMock(return_value=None)
        write_lock.__aexit__ = AsyncMock(return_value=None)

        admin_user = MagicMock(spec=AdminUser)

        await delete_page_endpoint(
            page_id="about",
            response=response,
            content_manager=cm,
            git_service=git_service,
            content_write_lock=write_lock,
            session_factory=session_factory,
            content_size_tracker=tracker,
            _user=admin_user,
            delete_file=True,
        )

        # After deletion, tracker usage should have decreased by the file size
        assert tracker.current_usage == 0

    async def test_delete_page_endpoint_does_not_under_count_when_file_unlink_fails(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If the page file survives deletion, quota should only reflect the config rewrite."""
        from unittest.mock import AsyncMock, MagicMock

        from backend.api.admin import delete_page_endpoint
        from backend.models.user import AdminUser

        tracker = ContentSizeTracker(content_dir=cm.content_dir, max_size=None)
        tracker.recompute()

        def tracked_usage() -> int:
            return sum(
                path.stat().st_size
                for path in cm.content_dir.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and all(not part.startswith(".") for part in path.relative_to(cm.content_dir).parts)
            )

        response = MagicMock()
        response.headers = {}

        git_service = MagicMock()
        git_service.try_commit = AsyncMock(return_value="abc123")

        write_lock = MagicMock()
        write_lock.__aenter__ = AsyncMock(return_value=None)
        write_lock.__aexit__ = AsyncMock(return_value=None)

        admin_user = MagicMock(spec=AdminUser)
        about_path = cm.content_dir / "about.md"

        with patch.object(type(about_path), "unlink", side_effect=OSError("permission denied")):
            await delete_page_endpoint(
                page_id="about",
                response=response,
                content_manager=cm,
                git_service=git_service,
                content_write_lock=write_lock,
                session_factory=session_factory,
                content_size_tracker=tracker,
                _user=admin_user,
                delete_file=True,
            )

        assert about_path.exists()
        assert tracker.current_usage == tracked_usage()


class TestExceptionNarrowingCreatePage:
    """Unexpected exceptions (e.g. AttributeError) from cache refresh must NOT be caught.

    Only SQLAlchemyError, RuntimeError, and InternalServerError are expected
    failure modes.  Catching bare Exception would silently swallow programming
    errors.
    """

    async def test_unexpected_exception_propagates_in_create_page(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AttributeError from cache refresh must propagate, not be swallowed."""
        with (
            patch(
                "backend.services.cache_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=AttributeError("unexpected attr error"),
            ),
            pytest.raises(AttributeError, match="unexpected attr error"),
        ):
            await create_page(session_factory, cm, page_id="contact", title="Contact")


class TestExceptionNarrowingUpdatePage:
    """Unexpected exceptions from cache refresh in update_page must NOT be caught."""

    async def test_unexpected_exception_propagates_in_update_page(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AttributeError from cache refresh must propagate, not be swallowed."""
        async with session_factory() as session:
            session.add(PageCache(page_id="about", title="About", rendered_html="<p>x</p>"))
            await session.commit()

        with (
            patch(
                "backend.services.cache_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=AttributeError("unexpected attr error"),
            ),
            pytest.raises(AttributeError, match="unexpected attr error"),
        ):
            await update_page(session_factory, cm, "about", content="new content")


class TestExceptionNarrowingDeletePage:
    """Unexpected exceptions from DB cleanup in delete_page must NOT be caught."""

    async def test_unexpected_exception_propagates_in_delete_page(
        self, cm: ContentManager, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """TypeError from cache cleanup must propagate, not be swallowed."""
        with (
            patch(
                "backend.services.admin_service.sa_delete",
                side_effect=TypeError("unexpected type error"),
            ),
            pytest.raises(TypeError, match="unexpected type error"),
        ):
            await delete_page(session_factory, cm, page_id="about", delete_file=True)


class TestSetFavicon:
    def test_saves_file_to_assets_and_updates_toml(self, cm: ContentManager) -> None:
        (cm.content_dir / "assets").mkdir(exist_ok=True)
        data = b"\x89PNG fake"

        result = set_favicon(cm, extension=".png", data=data)

        favicon_path = cm.content_dir / "assets" / "favicon.png"
        assert favicon_path.exists()
        assert favicon_path.read_bytes() == data
        assert result.favicon == "assets/favicon.png"
        assert parse_site_config(cm.content_dir).favicon == "assets/favicon.png"

    def test_removes_old_file_on_extension_change(self, cm: ContentManager) -> None:
        assets = cm.content_dir / "assets"
        assets.mkdir(exist_ok=True)
        old_file = assets / "favicon.ico"
        old_file.write_bytes(b"ICO data")

        # Pre-set favicon to .ico
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                favicon="assets/favicon.ico",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        set_favicon(cm, extension=".png", data=b"PNG data")

        assert not old_file.exists()
        assert (assets / "favicon.png").exists()

    def test_creates_assets_dir_if_missing(self, cm: ContentManager) -> None:
        data = b"SVG content"
        result = set_favicon(cm, extension=".svg", data=data)
        assert (cm.content_dir / "assets" / "favicon.svg").exists()
        assert result.favicon == "assets/favicon.svg"


class TestRemoveFavicon:
    def test_removes_file_and_clears_toml(self, cm: ContentManager) -> None:
        assets = cm.content_dir / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "favicon.png").write_bytes(b"PNG")

        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                favicon="assets/favicon.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        result = remove_favicon(cm)

        assert not (assets / "favicon.png").exists()
        assert result.favicon is None
        assert parse_site_config(cm.content_dir).favicon is None

    def test_remove_when_no_favicon_is_noop(self, cm: ContentManager) -> None:
        result = remove_favicon(cm)
        assert result.favicon is None

    def test_remove_tolerates_missing_file(self, cm: ContentManager) -> None:
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                favicon="assets/favicon.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        result = remove_favicon(cm)
        assert result.favicon is None


class TestSetImage:
    def test_saves_file_to_assets_and_updates_toml(self, cm: ContentManager) -> None:
        (cm.content_dir / "assets").mkdir(exist_ok=True)
        data = b"\x89PNG fake site image"

        result = set_image(cm, extension=".png", data=data)

        image_path = cm.content_dir / "assets" / "image.png"
        assert image_path.exists()
        assert image_path.read_bytes() == data
        assert result.image == "assets/image.png"
        assert parse_site_config(cm.content_dir).image == "assets/image.png"

    def test_removes_old_file_on_extension_change(self, cm: ContentManager) -> None:
        assets = cm.content_dir / "assets"
        assets.mkdir(exist_ok=True)
        old_file = assets / "image.jpg"
        old_file.write_bytes(b"JPG data")

        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                image="assets/image.jpg",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        set_image(cm, extension=".png", data=b"PNG data")

        assert not old_file.exists()
        assert (assets / "image.png").exists()

    def test_creates_assets_dir_if_missing(self, cm: ContentManager) -> None:
        data = b"WebP content"
        result = set_image(cm, extension=".webp", data=data)
        assert (cm.content_dir / "assets" / "image.webp").exists()
        assert result.image == "assets/image.webp"

    def test_does_not_clobber_favicon_when_setting_image(self, cm: ContentManager) -> None:
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                favicon="assets/favicon.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        result = set_image(cm, extension=".png", data=b"image data")

        assert result.favicon == "assets/favicon.png"
        assert result.image == "assets/image.png"


class TestSetSiteAssetWriteFailure:
    """A failed asset write must not leave a partial file or update the TOML."""

    def test_set_image_cleans_up_partial_file_on_write_bytes_failure(
        self, cm: ContentManager
    ) -> None:
        assets = cm.content_dir / "assets"
        assets.mkdir(exist_ok=True)
        target = assets / "image.png"
        original_write_bytes = type(target).write_bytes

        def partial_then_raise(self_path: object, _data: bytes, /) -> int:
            from pathlib import Path

            assert isinstance(self_path, Path)
            original_write_bytes(self_path, b"partial")
            raise OSError("disk full")

        with (
            patch.object(type(target), "write_bytes", partial_then_raise),
            pytest.raises(OSError, match="disk full"),
        ):
            set_image(cm, extension=".png", data=b"PNG content")

        assert not target.exists()
        assert parse_site_config(cm.content_dir).image is None

    def test_set_image_propagates_mkdir_oserror(self, cm: ContentManager) -> None:
        assets = cm.content_dir / "assets"
        with (
            patch.object(type(assets), "mkdir", side_effect=OSError("read-only filesystem")),
            pytest.raises(OSError, match="read-only filesystem"),
        ):
            set_image(cm, extension=".png", data=b"PNG content")

        assert parse_site_config(cm.content_dir).image is None

    def test_set_image_rolls_back_when_toml_write_fails(self, cm: ContentManager) -> None:
        assets = cm.content_dir / "assets"
        assets.mkdir(exist_ok=True)

        with (
            patch(
                "backend.services.admin_service.write_site_config",
                side_effect=OSError("toml write failed"),
            ),
            pytest.raises(OSError, match="toml write failed"),
        ):
            set_image(cm, extension=".png", data=b"PNG content")

        assert not (assets / "image.png").exists()
        assert parse_site_config(cm.content_dir).image is None


class TestRemoveImage:
    def test_removes_file_and_clears_toml(self, cm: ContentManager) -> None:
        assets = cm.content_dir / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "image.png").write_bytes(b"PNG")

        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                image="assets/image.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        result = remove_image(cm)

        assert not (assets / "image.png").exists()
        assert result.image is None
        assert parse_site_config(cm.content_dir).image is None

    def test_remove_when_no_image_is_noop(self, cm: ContentManager) -> None:
        result = remove_image(cm)
        assert result.image is None

    def test_remove_tolerates_missing_file(self, cm: ContentManager) -> None:
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                image="assets/image.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        result = remove_image(cm)
        assert result.image is None

    def test_remove_does_not_clear_favicon(self, cm: ContentManager) -> None:
        cfg = cm.site_config
        write_site_config(
            cm.content_dir,
            SiteConfig(
                title=cfg.title,
                description=cfg.description,
                timezone=cfg.timezone,
                favicon="assets/favicon.png",
                image="assets/image.png",
                pages=cfg.pages,
            ),
        )
        cm.reload_config()

        result = remove_image(cm)
        assert result.favicon == "assets/favicon.png"
        assert result.image is None
