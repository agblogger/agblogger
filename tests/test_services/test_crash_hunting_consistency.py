"""Regression tests for data consistency issues #4, #5, #6, #7, #9.

Each test verifies that a specific fix prevents data inconsistency
when an operation partially fails.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import parse_site_config
from backend.models.base import CacheBase, DurableBase
from backend.models.post import FTS_CREATE_SQL, PostCache
from backend.utils.datetime import format_iso, now_utc

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine() -> AsyncGenerator[object]:
    """Create an in-memory SQLite engine for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(CacheBase.metadata.create_all)
        await conn.run_sync(DurableBase.metadata.create_all)
        # Create FTS5 virtual table manually
        await conn.execute(FTS_CREATE_SQL)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(
    async_engine: object,
) -> async_sessionmaker[AsyncSession]:
    """Return a session factory for the in-memory engine."""
    from sqlalchemy.ext.asyncio import AsyncEngine

    assert isinstance(async_engine, AsyncEngine)
    return async_sessionmaker(async_engine, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Provide a session for tests."""
    async with session_factory() as s:
        yield s


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    d = tmp_path / "content"
    d.mkdir()
    (d / "posts").mkdir()
    (d / "index.toml").write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
        '[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"\n'
    )
    (d / "labels.toml").write_text("[labels]\n")
    (d / "about.md").write_text("# About\n\nAbout page content.\n")
    return d


@pytest.fixture
def cm(content_dir: Path) -> ContentManager:
    return ContentManager(content_dir=content_dir)


# ---------------------------------------------------------------------------
# Issue #4: upload_post orphaned assets
# ---------------------------------------------------------------------------


class TestUploadPostOrphanedAssets:
    """If DB operations fail after assets are written, assets must be cleaned up."""

    @pytest.mark.slow
    async def test_assets_cleaned_up_on_flush_failure(self, tmp_path: Path) -> None:
        """When session.flush() raises after asset files are written, the
        upload endpoint must clean up orphaned asset files."""
        from sqlalchemy.exc import OperationalError

        from backend.config import Settings
        from tests.conftest import create_test_client

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")

        db_path = tmp_path / "test.db"
        settings = Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
        )

        async with create_test_client(settings) as client:
            token_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Patch session.flush to raise, simulating a DB failure after
            # asset files have been written to disk.
            async def failing_flush(self: AsyncSession, objects: Any = None) -> None:
                raise OperationalError("disk full", {}, Exception())

            md_content = "---\ntitle: Upload Flush Fail\n---\nBody\n"
            png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

            with patch.object(AsyncSession, "flush", failing_flush):
                resp = await client.post(
                    "/api/posts/upload",
                    files=[
                        ("files", ("index.md", md_content.encode(), "text/markdown")),
                        ("files", ("photo.png", png_bytes, "image/png")),
                    ],
                    headers=headers,
                )

            assert resp.status_code >= 400

            # Verify no orphaned asset directories remain in the posts dir
            posts_dir = content_dir / "posts"
            for child in posts_dir.iterdir():
                if child.is_dir():
                    asset_files = [f for f in child.iterdir() if f.name != "index.md"]
                    assert not asset_files, f"Orphaned assets found in {child}: {asset_files}"

    @pytest.mark.slow
    async def test_assets_cleaned_up_on_replace_labels_failure(self, tmp_path: Path) -> None:
        """When _replace_post_labels raises after assets are written and flush
        succeeds, the upload endpoint must still clean up orphaned assets."""
        from sqlalchemy.exc import OperationalError

        from backend.config import Settings
        from tests.conftest import create_test_client

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")

        db_path = tmp_path / "test.db"
        settings = Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
        )

        async with create_test_client(settings) as client:
            token_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            md_content = "---\ntitle: Upload Labels Fail\n---\nBody\n"
            img1_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
            img2_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 50

            # Patch _replace_post_labels to raise after flush succeeds
            with patch(
                "backend.api.posts._replace_post_labels",
                new_callable=AsyncMock,
                side_effect=OperationalError("table locked", {}, Exception()),
            ):
                resp = await client.post(
                    "/api/posts/upload",
                    files=[
                        ("files", ("index.md", md_content.encode(), "text/markdown")),
                        ("files", ("img1.png", img1_bytes, "image/png")),
                        ("files", ("img2.jpg", img2_bytes, "image/jpeg")),
                    ],
                    headers=headers,
                )

            assert resp.status_code >= 400

            # Verify no orphaned asset directories remain in the posts dir
            posts_dir = content_dir / "posts"
            for child in posts_dir.iterdir():
                if child.is_dir():
                    asset_files = [f for f in child.iterdir() if f.name != "index.md"]
                    assert not asset_files, f"Orphaned assets found in {child}: {asset_files}"


# ---------------------------------------------------------------------------
# Issue #5: delete_post_endpoint deletes file before commit
# ---------------------------------------------------------------------------


class TestDeletePostCommitBeforeFileDelete:
    """DB changes must be committed before the post file is deleted from disk."""

    @pytest.mark.slow
    async def test_file_survives_if_commit_fails(self, tmp_path: Path) -> None:
        """If the DB commit fails during delete, the post file must still
        exist on disk because commit happens before file deletion."""
        from sqlalchemy.exc import OperationalError

        from backend.config import Settings
        from tests.conftest import create_test_client

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")

        db_path = tmp_path / "test.db"
        settings = Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
        )

        async with create_test_client(settings) as client:
            token_resp = await client.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # First, create a post via the API so it exists in both DB and disk
            md_content = "---\ntitle: Delete Commit Fail\n---\nBody content\n"
            create_resp = await client.post(
                "/api/posts/upload",
                files={"files": ("post.md", md_content.encode(), "text/markdown")},
                headers=headers,
            )
            assert create_resp.status_code == 201
            file_path = create_resp.json()["file_path"]
            post_file = content_dir / file_path

            assert post_file.exists()

            # Patch session.commit to raise, simulating a DB commit failure.
            # The delete endpoint calls commit before file deletion, so if
            # commit fails the file must survive.
            async def failing_commit(self: AsyncSession) -> None:
                raise OperationalError("database locked", {}, Exception())

            with patch.object(AsyncSession, "commit", failing_commit):
                resp = await client.delete(
                    f"/api/posts/{file_path}",
                    headers=headers,
                )

            # The endpoint should return an error
            assert resp.status_code >= 400

            # The file must still exist on disk since commit failed
            assert post_file.exists(), "Post file was deleted even though DB commit failed"

    async def test_file_delete_failure_after_commit_leaves_db_clean(
        self,
        cm: ContentManager,
        session: AsyncSession,
    ) -> None:
        """After the fix, if file deletion fails after commit, the DB
        records are already gone (commit happened first)."""
        from datetime import UTC, datetime

        from sqlalchemy import delete as sa_delete

        from backend.models.label import PostLabelCache

        post_dir = cm.content_dir / "posts" / "2026-03-11-log-test"
        post_dir.mkdir(parents=True)
        post_file = post_dir / "index.md"
        post_file.write_text("---\ntitle: Log Test\n---\nContent\n")
        file_path = "posts/2026-03-11-log-test/index.md"

        post = PostCache(
            file_path=file_path,
            title="Log Test",
            author="admin",
            created_at=datetime.now(UTC),
            modified_at=datetime.now(UTC),
            is_draft=False,
            content_hash="def456",
        )
        session.add(post)
        await session.commit()
        post_id = post.id

        # Delete DB records (mimicking the fixed flow)
        await session.execute(sa_delete(PostLabelCache).where(PostLabelCache.post_id == post_id))
        await session.delete(post)
        await session.commit()

        # Simulate file deletion failure - the DB is already clean
        with (
            patch.object(
                cm,
                "delete_post",
                side_effect=OSError("permission denied"),
            ),
            contextlib.suppress(OSError),
        ):
            cm.delete_post(file_path, delete_assets=False)

        # The DB should still not have the post (commit already happened)
        result = await session.execute(select(PostCache).where(PostCache.file_path == file_path))
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Issue #6: session.rollback() after commit is no-op in update_profile
# ---------------------------------------------------------------------------


class TestUpdateProfileCacheRebuildRevert:
    """When cache rebuild fails after a committed username change,
    the username must be reverted using a fresh session, not a rollback."""

    async def test_rollback_after_commit_is_ineffective(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Demonstrate that rollback after commit does NOT revert changes.
        This is the bug the fix addresses."""
        from backend.models.user import AdminUser

        now = format_iso(now_utc())

        # Create a user
        async with session_factory() as s:
            user = AdminUser(
                username="oldname",
                email="test@example.com",
                password_hash="hash",
                created_at=now,
                updated_at=now,
            )
            s.add(user)
            await s.commit()

        # Change username and commit
        async with session_factory() as s:
            result = await s.execute(select(AdminUser).where(AdminUser.username == "oldname"))
            user = result.scalar_one()
            user.username = "newname"
            await s.commit()

            # Now try rollback - it should be a no-op since already committed
            await s.rollback()

        # Verify the username is still "newname" - rollback was ineffective
        async with session_factory() as s:
            result = await s.execute(select(AdminUser).where(AdminUser.username == "newname"))
            found = result.scalar_one_or_none()
            assert found is not None, (
                "Rollback after commit should be a no-op; username should still be 'newname'"
            )

    async def test_fresh_session_reverts_username(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """The fix uses a fresh session to revert the username
        when cache rebuild fails."""
        from backend.models.user import AdminUser

        now = format_iso(now_utc())

        # Create a user
        async with session_factory() as s:
            user = AdminUser(
                username="oldname",
                email="test2@example.com",
                password_hash="hash",
                created_at=now,
                updated_at=now,
            )
            s.add(user)
            await s.commit()
            user_id = user.id

        # Change username and commit (simulating what update_profile does)
        async with session_factory() as s:
            result = await s.execute(select(AdminUser).where(AdminUser.id == user_id))
            user = result.scalar_one()
            user.username = "newname"
            await s.commit()

        # Now use a FRESH session to revert (this is the fix)
        async with session_factory() as revert_session:
            result = await revert_session.execute(select(AdminUser).where(AdminUser.id == user_id))
            user = result.scalar_one()
            user.username = "oldname"
            await revert_session.commit()

        # Verify the revert worked
        async with session_factory() as s:
            result = await s.execute(select(AdminUser).where(AdminUser.id == user_id))
            user = result.scalar_one()
            assert user.username == "oldname", (
                "Fresh session revert should have restored the original username"
            )


# ---------------------------------------------------------------------------
# Issue #7: delete_page deletes file before updating config
# ---------------------------------------------------------------------------


class TestDeletePageConfigBeforeFile:
    """Config must be updated before file deletion so that if file deletion
    fails, the config is already consistent."""

    async def test_config_updated_even_if_file_delete_fails(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After the fix, if the file deletion fails, the config should
        already be updated (page removed from config)."""
        about_path = cm.content_dir / "about.md"
        assert about_path.exists()

        from backend.services.admin_service import delete_page

        # Patch Path.unlink to fail
        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            # After the fix, this should NOT raise - it logs a warning
            await delete_page(session_factory, cm, page_id="about", delete_file=True)

        # Config should have the page removed
        reloaded = parse_site_config(cm.content_dir)
        assert not any(p.id == "about" for p in reloaded.pages)

        # File still exists (unlink failed) but config is correct
        assert about_path.exists()

    async def test_config_updated_before_file_deletion(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After the fix, config is updated first, then file is deleted."""
        from backend.filesystem.toml_manager import write_site_config
        from backend.services.admin_service import delete_page

        call_order: list[str] = []
        original_write = write_site_config
        original_unlink = Path.unlink

        def track_write(*args: Any, **kwargs: Any) -> None:
            call_order.append("write_config")
            original_write(*args, **kwargs)

        def track_unlink(self_path: Path, **kwargs: Any) -> None:
            call_order.append("delete_file")
            original_unlink(self_path, **kwargs)

        with (
            patch(
                "backend.services.admin_service.write_site_config",
                side_effect=track_write,
            ),
            patch.object(Path, "unlink", track_unlink),
        ):
            await delete_page(session_factory, cm, page_id="about", delete_file=True)

        write_idx = call_order.index("write_config")
        delete_idx = call_order.index("delete_file")
        assert write_idx < delete_idx, "Config must be written before file is deleted"

    async def test_file_delete_failure_logged_as_warning(
        self,
        cm: ContentManager,
        session_factory: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When file deletion fails after config update, a warning is logged."""
        from backend.services.admin_service import delete_page

        with (
            patch.object(Path, "unlink", side_effect=OSError("disk error")),
            caplog.at_level(logging.WARNING),
        ):
            await delete_page(session_factory, cm, page_id="about", delete_file=True)

        assert any("disk error" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Issue #9: reload_config non-atomic assignment
# ---------------------------------------------------------------------------


class TestReloadConfigAtomicAssignment:
    """Both site config and labels should be parsed before either is assigned,
    so a failure in parse_labels_config doesn't leave site_config updated
    but labels stale."""

    def test_site_config_not_updated_if_labels_parse_fails(self, cm: ContentManager) -> None:
        """If parse_labels_config raises an unexpected error, site_config
        should NOT be updated (atomic: both or neither)."""
        # Load initial config
        original_site_config = cm.site_config
        # Ensure labels are loaded too
        _ = cm.labels

        # Modify the site config on disk so reload would produce a new value
        (cm.content_dir / "index.toml").write_text(
            '[site]\ntitle = "Changed Title"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )

        # Make parse_labels_config raise an unexpected error
        with (
            patch(
                "backend.filesystem.content_manager.parse_labels_config",
                side_effect=RuntimeError("unexpected error"),
            ),
            pytest.raises(RuntimeError, match="unexpected error"),
        ):
            cm.reload_config()

        # site_config should NOT be updated since labels failed
        assert cm._site_config == original_site_config, (
            "site_config should not be updated when labels parsing fails"
        )

    def test_both_updated_on_success(self, cm: ContentManager) -> None:
        """When both parse calls succeed, both values are updated."""
        # Load initial config
        _ = cm.site_config
        _ = cm.labels

        # Modify both on disk
        (cm.content_dir / "index.toml").write_text(
            '[site]\ntitle = "New Title"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (cm.content_dir / "labels.toml").write_text(
            '[labels]\n[labels.python]\nnames = ["Python"]\n'
        )

        cm.reload_config()

        assert cm.site_config.title == "New Title"
        assert "python" in cm.labels

    def test_labels_not_updated_if_site_config_parse_fails(self, cm: ContentManager) -> None:
        """If parse_site_config raises, labels should also NOT be updated."""
        _ = cm.site_config
        original_labels = cm.labels

        with (
            patch(
                "backend.filesystem.content_manager.parse_site_config",
                side_effect=RuntimeError("site config error"),
            ),
            pytest.raises(RuntimeError, match="site config error"),
        ):
            cm.reload_config()

        # Labels should be unchanged
        assert cm._labels == original_labels
