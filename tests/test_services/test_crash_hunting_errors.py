"""Regression tests for crash-hunting error handling (Issues #10-#14).

Issue #10: Cross-post loop aborts on unexpected exception types
Issue #11: fm.dumps in merge_post_file can raise yaml.YAMLError
Issue #12: merge_file_content can raise subprocess.TimeoutExpired
Issue #13: update_label checks cycles against stale edges
Issue #14: session.flush() in create_post_endpoint lacks rollback
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import frontmatter as fm
import pytest

from backend.models.base import CacheBase, DurableBase
from backend.models.crosspost import SocialAccount
from backend.models.label import LabelCache, LabelParentCache
from backend.services.crosspost_service import crosspost
from backend.services.crypto_service import encrypt_value
from backend.services.datetime_service import format_datetime, now_utc
from backend.services.git_service import GitService
from backend.services.label_service import update_label
from backend.services.sync_service import merge_post_file
from tests.conftest import TEST_SECRET_KEY

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from backend.crosspost.base import CrossPostContent, CrossPostResult


# ── Fixtures ──


@pytest.fixture
async def _create_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)
        await conn.run_sync(CacheBase.metadata.create_all)


@pytest.fixture
async def session(db_session: AsyncSession, _create_tables: None) -> AsyncSession:
    return db_session


def _make_post(meta: dict[str, Any], body: str) -> str:
    post = fm.Post(body, **meta)
    return fm.dumps(post) + "\n"


# ── Issue #10: Cross-post loop aborts on unexpected exception types ──


class TestCrosspostCatchAllExceptions:
    """A poster plugin raising KeyError/TypeError/AttributeError must not abort the loop."""

    async def test_keyerror_in_poster_does_not_abort_loop(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A KeyError in poster.post() should be caught, not abort the entire crosspost."""
        call_count = {"calls": 0}

        class KeyErrorPoster:
            platform = "bluesky"

            async def post(self, content: CrossPostContent) -> CrossPostResult:
                call_count["calls"] += 1
                raise KeyError("missing_key")

        async def mock_get_poster(platform: str, creds: dict[str, str]) -> KeyErrorPoster:
            return KeyErrorPoster()

        monkeypatch.setattr("backend.services.crosspost_service.get_poster", mock_get_poster)

        now = format_datetime(now_utc())
        creds = encrypt_value(json.dumps({"access_token": "tok"}), TEST_SECRET_KEY)
        account = SocialAccount(
            user_id=1,
            platform="bluesky",
            account_name="test",
            credentials=creds,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        await session.commit()

        mock_cm = MagicMock()
        mock_cm.read_post.return_value = MagicMock(
            title="Test", content="body", labels=[], is_draft=False
        )
        mock_cm.get_plain_excerpt.return_value = "excerpt"

        results = await crosspost(
            session=session,
            content_manager=mock_cm,
            post_path="posts/test/index.md",
            platforms=["bluesky"],
            actor=MagicMock(id=1, username="u", display_name="U"),
            site_url="https://example.com",
            secret_key=TEST_SECRET_KEY,
        )

        assert len(results) == 1
        assert not results[0].success
        assert results[0].error is not None

    async def test_typeerror_in_poster_does_not_abort_loop(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A TypeError in poster.post() should be caught."""

        class TypeErrorPoster:
            platform = "bluesky"

            async def post(self, content: CrossPostContent) -> CrossPostResult:
                raise TypeError("unexpected type")

        async def mock_get_poster(platform: str, creds: dict[str, str]) -> TypeErrorPoster:
            return TypeErrorPoster()

        monkeypatch.setattr("backend.services.crosspost_service.get_poster", mock_get_poster)

        now = format_datetime(now_utc())
        creds = encrypt_value(json.dumps({"access_token": "tok"}), TEST_SECRET_KEY)
        account = SocialAccount(
            user_id=1,
            platform="bluesky",
            account_name="test2",
            credentials=creds,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        await session.commit()

        mock_cm = MagicMock()
        mock_cm.read_post.return_value = MagicMock(
            title="Test", content="body", labels=[], is_draft=False
        )
        mock_cm.get_plain_excerpt.return_value = "excerpt"

        results = await crosspost(
            session=session,
            content_manager=mock_cm,
            post_path="posts/test/index.md",
            platforms=["bluesky"],
            actor=MagicMock(id=1, username="u", display_name="U"),
            site_url="https://example.com",
            secret_key=TEST_SECRET_KEY,
        )

        assert len(results) == 1
        assert not results[0].success


# ── Issue #11: fm.dumps in merge_post_file can raise yaml.YAMLError ──


class TestMergePostFileYAMLDumpsError:
    """If fm.dumps raises yaml.YAMLError after merge, return the server version."""

    async def test_yaml_dumps_error_returns_server_fallback(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()

        meta = {"title": "T", "author": "A", "labels": ["#a"]}
        base = _make_post(meta, "Base body.\n")
        server = _make_post(meta, "Server body.\n")
        # Client has same body as server so no git merge needed; only frontmatter merge
        client = _make_post(meta, "Server body.\n")

        import yaml

        with patch(
            "backend.services.sync_service.fm.dumps",
            side_effect=yaml.YAMLError("yaml fail"),
        ):
            # Before fix: this would propagate the exception and crash
            # After fix: it should return the server version as fallback
            result = await merge_post_file(base, server, client, git)

        assert result.merged_content == server


# ── Issue #12: merge_file_content can raise subprocess.TimeoutExpired ──


class TestMergePostFileTimeoutExpired:
    """subprocess.TimeoutExpired from git merge-file should not crash merge_post_file."""

    async def test_timeout_expired_returns_server_with_conflict(self, tmp_path: Path) -> None:
        git = GitService(tmp_path)
        await git.init_repo()

        meta = {"title": "T"}
        base = _make_post(meta, "base line\n")
        server = _make_post(meta, "server different line\n")
        client = _make_post(meta, "client different line\n")

        with patch.object(
            git,
            "merge_file_content",
            new_callable=AsyncMock,
            side_effect=subprocess.TimeoutExpired("git merge-file", 30),
        ):
            result = await merge_post_file(base, server, client, git)

        assert result.body_conflicted
        parsed = fm.loads(result.merged_content)
        assert "server different line" in parsed.content


# ── Issue #13: update_label checks cycles against stale edges ──


class TestUpdateLabelCycleDetectionStaleEdges:
    """Cycle detection must use clean state, not stale edges."""

    async def test_reparent_works_correctly(self, session: AsyncSession) -> None:
        """Changing A->B to A->C should work without issues."""
        label_a = LabelCache(id="#a", names='["A"]')
        label_b = LabelCache(id="#b", names='["B"]')
        label_c = LabelCache(id="#c", names='["C"]')
        session.add_all([label_a, label_b, label_c])
        await session.flush()

        edge = LabelParentCache(label_id="#a", parent_id="#b")
        session.add(edge)
        await session.flush()

        result = await update_label(session, "#a", names=["A"], parents=["#c"])
        assert result is not None
        assert result.id == "#a"

    async def test_actual_cycle_still_detected(self, session: AsyncSession) -> None:
        """Real cycles must still be rejected after the fix."""
        label_a = LabelCache(id="#x", names='["X"]')
        label_b = LabelCache(id="#y", names='["Y"]')
        session.add_all([label_a, label_b])
        await session.flush()

        edge = LabelParentCache(label_id="#y", parent_id="#x")
        session.add(edge)
        await session.flush()

        with pytest.raises(ValueError, match="cycle"):
            await update_label(session, "#x", names=["X"], parents=["#y"])


# ── Issue #14: session.flush() in create_post_endpoint lacks rollback ──


class TestCreatePostFlushRollback:
    """create_post_endpoint must rollback the session if flush or label ops fail."""

    @pytest.mark.slow
    async def test_label_failure_does_not_crash_server(self, tmp_path: Path) -> None:
        """If _replace_post_labels raises, the server returns an error and stays healthy."""
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

            # Patch _replace_post_labels to raise after flush succeeds
            with patch(
                "backend.api.posts._replace_post_labels",
                new_callable=AsyncMock,
                side_effect=OperationalError("table locked", {}, Exception()),
            ):
                resp = await client.post(
                    "/api/posts",
                    json={
                        "title": "Test Post",
                        "body": "Body content",
                        "labels": ["test"],
                        "is_draft": False,
                    },
                    headers=headers,
                )

            # Should return an error status, not crash the server
            assert resp.status_code >= 400

            # Verify the server is still operational after the error
            health_resp = await client.get("/api/posts")
            assert health_resp.status_code == 200
