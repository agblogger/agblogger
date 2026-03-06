"""Tests for PR review fixes.

Covers all 12 issues identified in the comprehensive PR review:
1. Narrow except Exception on session.commit() in update_post_endpoint
2. Narrow except Exception on config write in create_page
3. sync_status returns warnings on git failure
4. parse_json_object always wraps ValueError with context
5. KeyError handler uses logger.critical
6. Lock file cleanup failure is logged (no contextlib.suppress)
7. Misleading "Git commit failed" warning after successful commit
8. _set_git_warning extracted to deps.py
9. Duplicated merge-result file write hoisted
10. Duplicate except blocks merged in sync git commit
11. Test for symlink rollback on commit failure
12. Test for sync_status git failure degradation
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


# ── Fixtures ──


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    posts_dir = tmp_content_dir / "posts"
    (posts_dir / "2026-02-02-hello-world").mkdir()
    (posts_dir / "2026-02-02-hello-world" / "index.md").write_text(
        "---\ntitle: Hello World\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: Admin\nauthor_username: admin\nlabels: []\n---\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text("[labels]\n")
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


# ── Issue 1: Narrow except Exception on session.commit() ──


class TestIssue1CommitFailureLogsError:
    """DB commit failure in update_post should log the error before re-raising."""

    async def test_commit_failure_is_logged_with_context(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)

        # The fixture already creates a post at "2026-02-02-hello-world"
        file_path = "posts/2026-02-02-hello-world/index.md"

        with (
            patch(
                "backend.api.posts.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=OperationalError("disk full", {}, Exception()),
            ),
            caplog.at_level(logging.ERROR, logger="backend.api.posts"),
        ):
            resp = await client.put(
                f"/api/posts/{file_path}",
                json={"title": "Hello World", "body": "Updated", "labels": [], "is_draft": False},
                headers=headers,
            )

        assert resp.status_code >= 400
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("commit failed" in m.lower() or "db commit" in m.lower() for m in error_msgs)


# ── Issue 2: Narrow except Exception on config write ──


class TestIssue2NarrowConfigWriteExcept:
    """create_page config write should catch OSError, not bare Exception."""

    def test_config_write_catches_oserror_not_exception(self) -> None:
        import inspect

        from backend.services import admin_service

        source = inspect.getsource(admin_service.create_page)
        # Should NOT have bare except Exception for the config write block
        # Should have except OSError instead
        assert "except Exception:" not in source


# ── Issue 3: sync_status returns warnings on git failure ──


class TestIssue3SyncStatusWarnings:
    """sync_status should include warnings when git fails."""

    async def test_sync_status_includes_warnings_on_git_failure(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.sync.GitService.head_commit",
            new_callable=AsyncMock,
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # server_commit should be None
        assert data["server_commit"] is None
        # warnings field should exist and contain a warning about git
        assert "warnings" in data
        assert any("git" in w.lower() for w in data["warnings"])


# ── Issue 4: parse_json_object wraps ValueError with context ──


class TestIssue4ParseJsonObjectContext:
    """parse_json_object without error_cls should include context in ValueError."""

    def test_non_json_without_error_cls_includes_context(self) -> None:
        import httpx

        from backend.crosspost.http_utils import parse_json_object

        resp = httpx.Response(200, text="not json")
        with pytest.raises(ValueError, match="Facebook feed endpoint"):
            parse_json_object(resp, context="Facebook feed endpoint")

    def test_non_dict_without_error_cls_includes_context(self) -> None:
        import httpx

        from backend.crosspost.http_utils import parse_json_object

        resp = httpx.Response(200, json=[1, 2, 3])
        with pytest.raises(ValueError, match="X tweets endpoint"):
            parse_json_object(resp, context="X tweets endpoint")


# ── Issue 5: KeyError handler uses logger.critical ──


class TestIssue5KeyErrorLogLevel:
    """KeyError global handler should log at CRITICAL level."""

    async def test_key_error_logged_at_critical(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from httpx import ASGITransport, AsyncClient

        from backend.main import create_app

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-key-error-level")
        async def _raise_key_error() -> None:
            raise KeyError("secret_key_name")

        with caplog.at_level(logging.CRITICAL, logger="backend.main"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/test-key-error-level")

        assert resp.status_code == 500
        critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert any("[BUG]" in r.message for r in critical_records)


# ── Issue 6: Lock file cleanup failure is logged ──


class TestIssue6LockCleanupLogging:
    """Lock file cleanup failure should be logged, not suppressed."""

    def test_lock_cleanup_failure_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import os
        import time

        key_path = tmp_path / "test-key.json"
        lock_path = key_path.with_name(f".{key_path.name}.lock")
        lock_path.write_text("")
        old_time = time.time() - 60
        os.utime(lock_path, (old_time, old_time))

        original_stat = type(lock_path).stat
        original_unlink = type(lock_path).unlink
        stat_failed = False

        def _failing_stat(self, *args, **kwargs):
            nonlocal stat_failed
            if self == lock_path and not stat_failed:
                stat_failed = True
                raise OSError("stat failed")
            return original_stat(self, *args, **kwargs)

        # Make unlink also fail so we can verify it's logged
        def _failing_unlink(self, *args, **kwargs):
            if self == lock_path:
                raise OSError("unlink failed")
            return original_unlink(self, *args, **kwargs)

        from backend.crosspost.atproto_oauth import load_or_create_keypair

        with (
            patch.object(type(lock_path), "stat", _failing_stat),
            patch.object(type(lock_path), "unlink", _failing_unlink),
            caplog.at_level(logging.WARNING, logger="backend.crosspost.atproto_oauth"),
            contextlib.suppress(OSError, FileExistsError, RuntimeError),
        ):
            load_or_create_keypair(key_path)

        # Should have TWO log messages: one for stat failure, one for unlink failure
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("stale keypair lock inspection failed" in m.lower() for m in warning_messages)
        assert any("failed to remove stale lock" in m.lower() for m in warning_messages)


# ── Issue 7: Misleading git commit warning after successful commit ──


class TestIssue7AccurateHeadCommitWarning:
    """After successful git commit, head_commit() failure should have accurate message."""

    async def test_head_commit_failure_message_is_accurate(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        """The warning should say 'Failed to read commit hash', not 'Git commit failed'."""
        import inspect

        from backend.api import sync as sync_mod

        source = inspect.getsource(sync_mod._sync_commit_inner)
        # Find the warning after head_commit failure (after git_failed check)
        # The message should NOT say "Git commit failed" for a head_commit read failure
        # Look for the specific misleading line
        assert (
            'sync_warnings.append("Git commit failed'
            not in source.split("commit_hash = await git_service.head_commit()")[-1]
        )


# ── Issue 8: _set_git_warning extracted to deps.py ──


class TestIssue8SharedSetGitWarning:
    """_set_git_warning should be importable from deps.py, not duplicated."""

    def test_set_git_warning_in_deps(self) -> None:
        from backend.api.deps import set_git_warning

        assert callable(set_git_warning)

    def test_admin_uses_deps_set_git_warning(self) -> None:
        import inspect

        from backend.api import admin

        source = inspect.getsource(admin)
        # Should NOT define its own _set_git_warning
        assert "def _set_git_warning" not in source

    def test_posts_uses_deps_set_git_warning(self) -> None:
        import inspect

        from backend.api import posts

        source = inspect.getsource(posts)
        # Should NOT define its own _set_git_warning
        assert "def _set_git_warning" not in source


# ── Issue 9: Duplicated merge-result file write hoisted ──


class TestIssue9HoistedMergeWrite:
    """Merge result write_text should not be duplicated in both branches."""

    def test_no_duplicate_write_text_in_merge_branches(self) -> None:
        import inspect

        from backend.api import sync as sync_mod

        source = inspect.getsource(sync_mod._sync_commit_inner)
        # Find the section dealing with merge_result
        # After hoisting, write_text(merge_result.merged_content) should appear once
        # in the merge handling block, not twice
        merge_section = source.split("merge_result = await merge_post_file(")[1]
        merge_section = merge_section.split("# Non-conflict or non-post file")[0]
        count = merge_section.count("write_text(merge_result.merged_content")
        assert count == 1, f"Expected 1 write_text for merged_content, found {count}"


# ── Issue 10: Duplicate except blocks merged ──


class TestIssue10MergedExceptBlocks:
    """Git commit except blocks should be merged into one."""

    def test_single_except_block_for_git_commit(self) -> None:
        import inspect

        from backend.api import sync as sync_mod

        source = inspect.getsource(sync_mod._sync_commit_inner)
        # Find the git commit section
        git_section = source.split('await git_service.commit_all(f"Sync commit by {username}")')[1]
        git_section = git_section.split("# ── Update manifest")[0]
        # Should have ONE except block, not two
        except_count = git_section.count("except ")
        assert except_count == 1, f"Expected 1 except block for git commit, found {except_count}"


# ── Issue 11: Test for symlink rollback on commit failure ──


class TestIssue11SymlinkRollbackOnCommitFailure:
    """When commit fails after rename + symlink creation, symlink should be cleaned up."""

    async def test_symlink_removed_during_rollback(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "posts").mkdir()
        (content_dir / "assets").mkdir()
        (content_dir / "index.toml").write_text(
            '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
            '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
        )
        (content_dir / "labels.toml").write_text("[labels]\n")

        post_dir = content_dir / "posts" / "2026-02-02-original-title"
        post_dir.mkdir()
        (post_dir / "index.md").write_text(
            "---\ntitle: Original Title\ncreated_at: 2026-02-02 22:21:29+00\n"
            "author: Admin\nauthor_username: admin\nlabels: []\n---\nContent here.\n"
        )

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

        async with create_test_client(settings) as tc:
            token_resp = await tc.post(
                "/api/auth/token-login",
                json={"username": "admin", "password": "admin123"},
            )
            token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            with patch(
                "sqlalchemy.ext.asyncio.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=OperationalError("disk full", {}, Exception()),
            ):
                resp = await tc.put(
                    "/api/posts/posts/2026-02-02-original-title/index.md",
                    json={
                        "title": "New Different Title",
                        "body": "Content here.",
                        "labels": [],
                        "is_draft": False,
                    },
                    headers=headers,
                )

            assert resp.status_code >= 500

            # Old directory should be restored
            assert post_dir.exists(), "Old directory should be restored"
            # No symlink should remain at old_dir
            assert not post_dir.is_symlink(), (
                "Symlink at old path should be removed during rollback"
            )
            # New directory should not exist
            new_dir = content_dir / "posts" / "2026-02-02-new-different-title"
            assert not new_dir.exists(), "New directory should not persist"


# ── Issue 12: Test for sync_status git failure degradation ──


class TestIssue12SyncStatusGitFailure:
    """sync_status endpoint should degrade gracefully when git fails."""

    async def test_sync_status_returns_200_with_null_commit_on_git_failure(
        self, client: AsyncClient
    ) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.sync.GitService.head_commit",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("git not found"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_commit"] is None

    async def test_sync_status_logs_error_on_git_failure(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)
        with (
            patch(
                "backend.api.sync.GitService.head_commit",
                new_callable=AsyncMock,
                side_effect=subprocess.TimeoutExpired("git", 30),
            ),
            caplog.at_level(logging.ERROR, logger="backend.api.sync"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )

        assert resp.status_code == 200
        assert any("git head" in r.message.lower() for r in caplog.records)
