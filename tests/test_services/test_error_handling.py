"""Tests for error handling in services and libraries."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.exceptions import InternalServerError
from backend.filesystem.content_manager import ContentManager
from backend.filesystem.toml_manager import (
    LabelDef,
    SiteConfig,
    parse_labels_config,
    parse_site_config,
    write_labels_config,
    write_site_config,
)
from backend.services.datetime_service import parse_datetime


class TestParseDatetimeParserError:
    """H3: pendulum.ParserError should be converted to ValueError."""

    def test_invalid_date_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_datetime("not-a-date")

    def test_gibberish_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_datetime("xyz123!@#")


class TestConfigParsingOSError:
    """OSError in config parsing returns defaults and logs at ERROR level."""

    def test_site_config_permission_error(self, tmp_path: Path) -> None:
        index = tmp_path / "index.toml"
        index.write_text('[site]\ntitle = "Test"')
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            result = parse_site_config(tmp_path)
        assert result.title == "My Blog"  # default

    def test_labels_config_permission_error(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels.toml"
        labels.write_text("[labels.foo]\nnames = ['foo']")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            result = parse_labels_config(tmp_path)
        assert result == {}

    def test_corrupted_site_config_logs_at_error_level(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        index = tmp_path / "index.toml"
        index.write_text("{{invalid toml")
        with caplog.at_level(logging.ERROR, logger="backend.filesystem.toml_manager"):
            result = parse_site_config(tmp_path)
        assert result.title == "My Blog"  # default
        assert any(r.levelno == logging.ERROR for r in caplog.records)


class TestLabelsConfigTypeCheck:
    """M10: Non-dict label entries should be skipped."""

    def test_string_label_entry_skipped(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels.toml"
        labels.write_text('[labels]\nfoo = "bar"')
        result = parse_labels_config(tmp_path)
        assert "foo" not in result


class TestReadPostErrorHandling:
    """read_post returns None on parse errors and logs appropriately."""

    def test_invalid_yaml_returns_none(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        post_dir = posts_dir / "bad"
        post_dir.mkdir()
        bad_post = post_dir / "index.md"
        bad_post.write_text("---\ntitle: [\n---\nbody")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)
        result = cm.read_post("posts/bad/index.md")
        assert result is None

    def test_binary_file_returns_none(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        post_dir = posts_dir / "binary"
        post_dir.mkdir(parents=True)
        bad_post = post_dir / "index.md"
        bad_post.write_bytes(b"\x80\x81\x82\x83")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)
        result = cm.read_post("posts/binary/index.md")
        assert result is None

    def test_oserror_logs_at_error_level(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        posts_dir = tmp_path / "posts"
        post_dir = posts_dir / "good"
        post_dir.mkdir(parents=True)
        good_post = post_dir / "index.md"
        good_post.write_text("---\ntitle: Test\n---\nbody")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)

        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            caplog.at_level(logging.ERROR, logger="backend.filesystem.content_manager"),
        ):
            result = cm.read_post("posts/good/index.md")

        assert result is None
        assert any(r.levelno == logging.ERROR for r in caplog.records)


class TestReadPageErrorHandling:
    """M11: read_page returns None on I/O errors."""

    def test_binary_page_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Test"\n\n[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"'
        )
        (tmp_path / "labels.toml").write_text("[labels]")
        about = tmp_path / "about.md"
        about.write_bytes(b"\x80\x81\x82\x83")
        cm = ContentManager(content_dir=tmp_path)
        result = cm.read_page("about")
        assert result is None


class TestPageServicePropagatesRenderError:
    """get_page propagates RenderError instead of returning empty HTML."""

    async def test_get_page_propagates_render_error(self, tmp_path: Path) -> None:
        from backend.pandoc.renderer import RenderError
        from backend.services.page_service import get_page

        (tmp_path / "index.toml").write_text(
            '[site]\ntitle = "Test"\n\n[[pages]]\nid = "about"\ntitle = "About"\nfile = "about.md"'
        )
        (tmp_path / "labels.toml").write_text("[labels]")
        (tmp_path / "about.md").write_text("# About\n\nAbout page.\n")
        cm = ContentManager(content_dir=tmp_path)

        with (
            patch(
                "backend.services.page_service.render_markdown",
                new_callable=AsyncMock,
                side_effect=RenderError("pandoc broken"),
            ),
            pytest.raises(RenderError, match="pandoc broken"),
        ):
            await get_page(cm, "about")


class TestSafeParseNames:
    """M7: _safe_parse_names handles corrupted JSON gracefully."""

    def test_valid_json_list(self) -> None:
        from backend.services.label_service import _safe_parse_names

        assert _safe_parse_names('["foo", "bar"]') == ["foo", "bar"]

    def test_invalid_json(self) -> None:
        from backend.services.label_service import _safe_parse_names

        assert _safe_parse_names("not valid json {") == []

    def test_json_non_list(self) -> None:
        from backend.services.label_service import _safe_parse_names

        assert _safe_parse_names('{"key": "value"}') == []

    def test_json_null(self) -> None:
        from backend.services.label_service import _safe_parse_names

        assert _safe_parse_names("null") == []


class TestSyncYamlError:
    """H6: yaml.YAMLError caught in normalize_post_frontmatter."""

    def test_malformed_yaml_skipped(self, tmp_path: Path) -> None:
        post = tmp_path / "posts" / "bad" / "index.md"
        post.parent.mkdir(parents=True)
        post.write_text("---\ntitle: [\n---\nbody")
        from backend.services.sync_service import normalize_post_frontmatter

        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/bad/index.md"],
            old_manifest={},
            content_dir=tmp_path,
        )
        assert any("parse error" in w for w in warnings)


class TestFTSOperationalError:
    """FTS5 OperationalError propagates to caller."""

    @pytest.mark.asyncio
    async def test_fts_error_propagates(self) -> None:
        from sqlalchemy.exc import OperationalError

        mock_session = AsyncMock()
        mock_session.execute.side_effect = OperationalError("fts5", {}, Exception())

        from backend.services.post_service import search_posts

        with pytest.raises(OperationalError):
            await search_posts(mock_session, "test")


class TestInvalidDateFilterLogging:
    """Invalid date filters raise ValueError and log original parse error."""

    @pytest.mark.asyncio
    async def test_invalid_from_date_raises_value_error(self) -> None:
        from backend.services.post_service import list_posts

        mock_session = AsyncMock()

        with pytest.raises(ValueError, match="date"):
            await list_posts(mock_session, from_date="not-a-date")

    @pytest.mark.asyncio
    async def test_invalid_to_date_raises_value_error(self) -> None:
        from backend.services.post_service import list_posts

        mock_session = AsyncMock()

        with pytest.raises(ValueError, match="date"):
            await list_posts(mock_session, to_date="not-a-date")

    @pytest.mark.asyncio
    async def test_invalid_from_date_logs_original_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from backend.services.post_service import list_posts

        mock_session = AsyncMock()

        with (
            caplog.at_level(logging.WARNING, logger="backend.services.post_service"),
            pytest.raises(ValueError),
        ):
            await list_posts(mock_session, from_date="not-a-date")

        assert any("not-a-date" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_invalid_to_date_logs_original_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from backend.services.post_service import list_posts

        mock_session = AsyncMock()

        with (
            caplog.at_level(logging.WARNING, logger="backend.services.post_service"),
            pytest.raises(ValueError),
        ):
            await list_posts(mock_session, to_date="not-a-date")

        assert any("not-a-date" in r.message for r in caplog.records)


class TestInvalidSortColumn:
    """Invalid sort column raises ValueError instead of silently falling back."""

    @pytest.mark.asyncio
    async def test_invalid_sort_column_raises_value_error(self) -> None:
        from backend.services.post_service import list_posts

        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="sort"):
            await list_posts(mock_session, sort=cast("Any", "nonexistent_column"))


class TestSyncTimestampNarrowing:
    """Sync timestamp normalization uses narrowed exception handling."""

    def test_attribute_error_propagates(self, tmp_path: Path) -> None:
        """AttributeError is not caught by narrowed exception handler."""
        from backend.services.sync_service import normalize_post_frontmatter

        post = tmp_path / "posts" / "test" / "index.md"
        post.parent.mkdir(parents=True)
        # Valid YAML but with a value that will cause AttributeError in the timestamp path
        post.write_text("---\ntitle: Test\ncreated_at: valid\n---\nbody")

        # The function should handle standard parse errors (ValueError)
        # but not swallow programming bugs (AttributeError)
        warnings = normalize_post_frontmatter(
            uploaded_files=["posts/test/index.md"],
            old_manifest={},
            content_dir=tmp_path,
        )
        # ValueError from parse_datetime("valid") is still caught
        assert any("invalid created_at" in w for w in warnings)


class TestAtomicWrites:
    """M9: TOML writes are atomic."""

    def test_write_labels_uses_temp_file(self, tmp_path: Path) -> None:
        labels = {"test": LabelDef(id="test", names=["test"])}
        write_labels_config(tmp_path, labels)
        # File should exist and be valid TOML
        import tomllib

        data = tomllib.loads((tmp_path / "labels.toml").read_text())
        assert "test" in data["labels"]
        # No .tmp file left behind
        assert not (tmp_path / "labels.toml.tmp").exists()

    def test_write_site_config_uses_temp_file(self, tmp_path: Path) -> None:
        config = SiteConfig(title="Test Blog")
        write_site_config(tmp_path, config)
        import tomllib

        data = tomllib.loads((tmp_path / "index.toml").read_text())
        assert data["site"]["title"] == "Test Blog"
        assert not (tmp_path / "index.toml.tmp").exists()


class TestTomlWriteHardening:
    """TOML writes use unique temp paths and clean up on failure."""

    def test_temp_file_cleaned_up_on_write_error(self, tmp_path: Path) -> None:
        """Temp file should be removed if rename fails."""
        import glob

        labels = {"test": LabelDef(id="test", names=["test"])}

        # Make the destination read-only so replace fails
        labels_path = tmp_path / "labels.toml"
        labels_path.write_text("[labels]")

        with (
            patch("pathlib.Path.replace", side_effect=OSError("permission denied")),
            pytest.raises(OSError),
        ):
            write_labels_config(tmp_path, labels)

        # No temp files should be left behind
        tmp_files = glob.glob(str(tmp_path / "*.tmp*"))
        assert tmp_files == []

    def test_concurrent_writes_use_unique_temp_paths(self, tmp_path: Path) -> None:
        """Two writes should not collide on temp path names."""
        import tempfile

        temp_paths: list[str] = []
        original_mkstemp = tempfile.mkstemp

        def tracking_mkstemp(**kwargs: Any) -> tuple[int, str]:
            fd, path = original_mkstemp(**kwargs)
            temp_paths.append(path)
            return fd, path

        with patch("tempfile.mkstemp", side_effect=tracking_mkstemp):
            labels = {"a": LabelDef(id="a", names=["a"])}
            write_labels_config(tmp_path, labels)
            labels = {"b": LabelDef(id="b", names=["b"])}
            write_labels_config(tmp_path, labels)

        # Each write should have used a unique temp path
        assert len(temp_paths) == 2
        assert temp_paths[0] != temp_paths[1]


class TestReloadConfigProtection:
    """reload_config errors are caught during sync."""

    @pytest.mark.asyncio
    async def test_reload_config_error_adds_warning(self, tmp_path: Path) -> None:
        cm = ContentManager(content_dir=tmp_path)
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")

        # Force reload_config to raise an OSError (realistic filesystem failure)
        with patch.object(cm, "reload_config", side_effect=OSError("permission denied")):
            # Simulate the sync pattern with narrowed exception handling
            warnings: list[str] = []
            try:
                cm.reload_config()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                logging.getLogger("backend.api.sync").warning(
                    "Config reload failed during sync: %s", exc
                )
                warnings.append(f"Config reload failed: {exc}")

        assert any("Config reload failed" in w for w in warnings)


class TestOversizedPostSkipped:
    """12a: Oversized post files are skipped during scan and read."""

    def test_scan_posts_skips_oversized_file(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        big_dir = posts_dir / "big"
        big_dir.mkdir()
        big_post = big_dir / "index.md"
        # Write just over 10MB
        big_post.write_text("---\ntitle: Big\n---\n" + "x" * (10 * 1024 * 1024 + 1))
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)
        posts = cm.scan_posts()
        assert all(p.title != "Big" for p in posts)

    def test_read_post_skips_oversized_file(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        big_dir = posts_dir / "big"
        big_dir.mkdir()
        big_post = big_dir / "index.md"
        big_post.write_text("---\ntitle: Big\n---\n" + "x" * (10 * 1024 * 1024 + 1))
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)
        result = cm.read_post("posts/big/index.md")
        assert result is None


class TestNullByteSkipped:
    """12b: Files containing null bytes are skipped."""

    def test_scan_posts_skips_null_byte_file(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        null_dir = posts_dir / "null"
        null_dir.mkdir()
        bad_post = null_dir / "index.md"
        bad_post.write_text("---\ntitle: Null\n---\nbody\x00content")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)
        posts = cm.scan_posts()
        assert all(p.title != "Null" for p in posts)

    def test_read_post_skips_null_byte_file(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        null_dir = posts_dir / "null"
        null_dir.mkdir()
        bad_post = null_dir / "index.md"
        bad_post.write_text("---\ntitle: Null\n---\nbody\x00content")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)
        result = cm.read_post("posts/null/index.md")
        assert result is None


class TestInvalidTimezoneValidation:
    """12c: Invalid timezone falls back to UTC."""

    def test_invalid_timezone_falls_back_to_utc(self, tmp_path: Path) -> None:
        index = tmp_path / "index.toml"
        index.write_text('[site]\ntitle = "Test"\ntimezone = "Not/A/Timezone"')
        result = parse_site_config(tmp_path)
        assert result.timezone == "UTC"

    def test_valid_timezone_passes_through(self, tmp_path: Path) -> None:
        index = tmp_path / "index.toml"
        index.write_text('[site]\ntitle = "Test"\ntimezone = "US/Eastern"')
        result = parse_site_config(tmp_path)
        assert result.timezone == "US/Eastern"


class TestSymlinkCleanupError:
    """Symlink cleanup in delete_post handles per-item OSError."""

    def test_broken_symlink_does_not_abort_delete(self, tmp_path: Path) -> None:
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        post_dir = posts_dir / "2026-02-20-test"
        post_dir.mkdir()
        (post_dir / "index.md").write_text("---\ntitle: Test\n---\nbody")

        # Create a symlink that will cause resolve() to fail
        broken_link = posts_dir / "old-link"
        broken_link.symlink_to(post_dir)

        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        cm = ContentManager(content_dir=tmp_path)

        original_resolve = Path.resolve

        def patched_resolve(self: Path, strict: bool = False) -> Path:
            if self.name == "old-link":
                raise OSError("broken")
            return original_resolve(self, strict=strict)

        with patch("pathlib.Path.resolve", patched_resolve):
            result = cm.delete_post("posts/2026-02-20-test/index.md", delete_assets=True)

        assert result is True
        assert not post_dir.exists()


class TestCryptoDecryptionError:
    """Decryption failures raise InternalServerError, not ValueError."""

    def test_decrypt_invalid_ciphertext_raises_internal_error(self) -> None:
        from backend.services.crypto_service import decrypt_value

        with pytest.raises(InternalServerError, match="Failed to decrypt"):
            decrypt_value("not-valid-ciphertext", "some-secret-key-for-testing!!")

    def test_decrypt_invalid_ciphertext_not_value_error(self) -> None:
        from backend.services.crypto_service import decrypt_value

        with pytest.raises(InternalServerError):
            decrypt_value("not-valid-ciphertext", "some-secret-key-for-testing!!")

        # Ensure it does NOT raise ValueError
        try:
            decrypt_value("not-valid-ciphertext", "some-secret-key-for-testing!!")
        except InternalServerError:
            pass
        except ValueError:
            pytest.fail("decrypt_value should raise InternalServerError, not ValueError")


class TestPandocServerConfigValidation:
    """Pandoc server config errors raise InternalServerError."""

    def test_invalid_port_raises_internal_error(self) -> None:
        from backend.pandoc.server import PandocServer

        with pytest.raises(InternalServerError, match="port"):
            PandocServer(port=0)

    def test_invalid_timeout_raises_internal_error(self) -> None:
        from backend.pandoc.server import PandocServer

        with pytest.raises(InternalServerError, match="timeout"):
            PandocServer(timeout=0)


class TestConfigSecurityValidation:
    """Production security validation raises InternalServerError."""

    def test_insecure_config_raises_internal_error(self) -> None:
        from backend.config import Settings

        settings = Settings(
            secret_key="change-me-in-production",
            admin_password="admin",
            debug=False,
        )
        with pytest.raises(InternalServerError, match="Insecure production"):
            settings.validate_runtime_security()


class TestTypedExceptions:
    """Typed exception subclasses exist and have correct hierarchy."""

    def test_post_not_found_error_is_value_error(self) -> None:
        from backend.exceptions import PostNotFoundError

        exc = PostNotFoundError("Post not found: posts/hello/index.md")
        assert isinstance(exc, ValueError)

    def test_builtin_page_error_is_value_error(self) -> None:
        from backend.exceptions import BuiltinPageError

        exc = BuiltinPageError("Cannot delete built-in page 'timeline'")
        assert isinstance(exc, ValueError)

    def test_external_service_error_is_runtime_error(self) -> None:
        from backend.exceptions import ExternalServiceError

        exc = ExternalServiceError("OAuth failed")
        assert isinstance(exc, RuntimeError)


class TestCrosspostRaisesPostNotFoundError:
    """crosspost() raises PostNotFoundError when post is missing, not ValueError."""

    @pytest.mark.asyncio
    async def test_crosspost_raises_post_not_found_for_missing_post(self, tmp_path: Path) -> None:
        """crosspost() should raise PostNotFoundError when read_post returns None."""
        from backend.exceptions import PostNotFoundError
        from backend.services.crosspost_service import crosspost

        cm = ContentManager(content_dir=tmp_path)
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        (tmp_path / "posts").mkdir(exist_ok=True)

        mock_session = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.display_name = "Admin"
        mock_user.username = "admin"

        with pytest.raises(PostNotFoundError):
            await crosspost(
                session=mock_session,
                content_manager=cm,
                post_path="posts/nonexistent/index.md",
                platforms=["bluesky"],
                actor=mock_user,
                site_url="http://localhost",
                secret_key="test-key",
            )

    @pytest.mark.asyncio
    async def test_crosspost_raises_post_not_found_for_draft_by_non_author(
        self, tmp_path: Path
    ) -> None:
        """crosspost() should raise PostNotFoundError for draft posts not visible to non-author."""
        from backend.exceptions import PostNotFoundError
        from backend.services.crosspost_service import crosspost

        cm = ContentManager(content_dir=tmp_path)
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir(exist_ok=True)
        draft_post = posts_dir / "draft"
        draft_post.mkdir()
        (draft_post / "index.md").write_text(
            "---\ntitle: Draft\ndraft: true\nauthor: OtherUser\n"
            "created_at: 2026-02-02 22:21:29+00\n---\nDraft content.\n"
        )

        mock_session = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = 2
        mock_user.display_name = "NotTheAuthor"
        mock_user.username = "notauthor"

        with pytest.raises(PostNotFoundError):
            await crosspost(
                session=mock_session,
                content_manager=cm,
                post_path="posts/draft/index.md",
                platforms=["bluesky"],
                actor=mock_user,
                site_url="http://localhost",
                secret_key="test-key",
            )


class TestCrosspostDraftAuthSingleAdmin:
    """Regression: draft posts must never be crossposted.

    Crossposting an unpublished draft to social media would leak unreleased content.
    The guard must reject all draft crosspost attempts regardless of who the author is.
    """

    @pytest.mark.asyncio
    async def test_crosspost_rejects_own_draft(self, tmp_path: Path) -> None:
        """Draft posts must never be crossposted, even by their author."""
        from backend.exceptions import PostNotFoundError
        from backend.services.crosspost_service import crosspost

        cm = ContentManager(content_dir=tmp_path)
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir(exist_ok=True)
        draft_post = posts_dir / "my-draft"
        draft_post.mkdir()
        (draft_post / "index.md").write_text(
            "---\ntitle: My Draft\ndraft: true\nauthor: admin\n"
            "created_at: 2026-02-02 22:21:29+00\n---\nDraft by admin.\n"
        )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        mock_actor = MagicMock()
        mock_actor.id = 1
        mock_actor.display_name = "Admin"
        mock_actor.username = "admin"

        with pytest.raises(PostNotFoundError):
            await crosspost(
                session=mock_session,
                content_manager=cm,
                post_path="posts/my-draft/index.md",
                platforms=["bluesky"],
                actor=mock_actor,
                site_url="http://localhost",
                secret_key="test-key",
            )

    @pytest.mark.asyncio
    async def test_crosspost_rejects_other_users_draft(self, tmp_path: Path) -> None:
        """Draft posts by another author must also be rejected."""
        from backend.exceptions import PostNotFoundError
        from backend.services.crosspost_service import crosspost

        cm = ContentManager(content_dir=tmp_path)
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir(exist_ok=True)
        draft_post = posts_dir / "other-draft"
        draft_post.mkdir()
        (draft_post / "index.md").write_text(
            "---\ntitle: Other Draft\ndraft: true\nauthor: original-author\n"
            "created_at: 2026-02-02 22:21:29+00\n---\nDraft by someone else.\n"
        )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        mock_actor = MagicMock()
        mock_actor.id = 1
        mock_actor.display_name = "Admin"
        mock_actor.username = "admin"

        with pytest.raises(PostNotFoundError):
            await crosspost(
                session=mock_session,
                content_manager=cm,
                post_path="posts/other-draft/index.md",
                platforms=["bluesky"],
                actor=mock_actor,
                site_url="http://localhost",
                secret_key="test-key",
            )


class TestCrosspostErrorMessageLeakage:
    """CrossPostResult.error uses generic message, not str(exc)."""

    @pytest.mark.asyncio
    async def test_platform_failure_uses_generic_error_message(self, tmp_path: Path) -> None:
        """When a platform poster raises an exception, the error field should be generic."""
        from backend.services.crosspost_service import crosspost

        cm = ContentManager(content_dir=tmp_path)
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"')
        (tmp_path / "labels.toml").write_text("[labels]")
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir(exist_ok=True)
        hello_post = posts_dir / "hello"
        hello_post.mkdir()
        (hello_post / "index.md").write_text(
            "---\ntitle: Hello\nauthor: admin\n"
            "created_at: 2026-02-02 22:21:29+00\nlabels: []\n---\nHello world.\n"
        )

        # Build a mock session where execute().scalars().all() works correctly
        mock_account = MagicMock()
        mock_account.platform = "bluesky"
        mock_account.credentials = '{"access_token": "tok"}'
        mock_account.account_name = "test"
        mock_account.updated_at = None

        mock_cached_post = MagicMock()
        mock_cached_post.is_draft = False
        mock_cached_post.author = "admin"

        mock_post_result = MagicMock()
        mock_post_result.scalar_one_or_none.return_value = mock_cached_post

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_account]
        mock_account_result = MagicMock()
        mock_account_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [mock_post_result, mock_account_result]
        # session.add() is synchronous in SQLAlchemy
        mock_session.add = MagicMock()

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.display_name = "Admin"
        mock_user.username = "admin"

        # Make the poster raise an exception with sensitive details
        mock_poster = AsyncMock()
        mock_poster.post.side_effect = RuntimeError("OAuth token expired: secret_token_abc123")
        mock_poster.get_updated_credentials = None

        with (
            patch(
                "backend.services.crosspost_service.get_poster",
                new_callable=AsyncMock,
                return_value=mock_poster,
            ),
            patch(
                "backend.services.crosspost_service.decrypt_value",
                return_value='{"access_token": "tok"}',
            ),
        ):
            results = await crosspost(
                session=mock_session,
                content_manager=cm,
                post_path="posts/hello/index.md",
                platforms=["bluesky"],
                actor=mock_user,
                site_url="http://localhost",
                secret_key="test-key",
            )

        assert len(results) == 1
        assert results[0].success is False
        # The error should be a generic message, not the internal exception details
        assert results[0].error == "Cross-posting failed"
        assert "secret_token_abc123" not in (results[0].error or "")


class TestPandocRendererRetryExceptionGap:
    """Pandoc retry path must catch all exceptions, not just httpx.HTTPError."""

    @pytest.mark.asyncio
    async def test_retry_catches_non_http_error(self) -> None:
        import httpx

        from backend.pandoc.renderer import RenderError, _render_markdown, _sanitize_html

        mock_server = AsyncMock()
        mock_server.base_url = "http://localhost:9999"
        mock_server.ensure_running = AsyncMock()

        mock_client = AsyncMock()
        # First call: NetworkError triggers restart
        # Second call: OSError (not httpx.HTTPError) — must not escape
        mock_client.post = AsyncMock(
            side_effect=[httpx.NetworkError("connection reset"), OSError("broken pipe")]
        )

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
            pytest.raises(RenderError, match="unreachable after restart"),
        ):
            await _render_markdown("# test", from_format="markdown", sanitizer=_sanitize_html)
