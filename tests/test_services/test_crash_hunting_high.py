"""Regression tests for HIGH severity crash issues.

Issue #1: scan_posts / read_post missing KeyError/TypeError in exception handler.
Issue #2: _load_existing() OSError not caught in atproto OAuth keypair loading.
Issue #3: Rare httpx exceptions from Pandoc not wrapped in RenderError.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.crosspost.atproto_oauth import load_or_create_keypair
from backend.filesystem.content_manager import ContentManager
from backend.pandoc.renderer import RenderError, _render_markdown

if TYPE_CHECKING:
    from pathlib import Path


class TestScanPostsKeyErrorTypeError:
    """Issue #1: KeyError/TypeError from malformed YAML should be caught, not crash."""

    def test_scan_posts_skips_post_raising_key_error(self, tmp_path: Path) -> None:
        """scan_posts should catch KeyError from parse_post and skip the bad post."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        bad_post = posts_dir / "bad"
        bad_post.mkdir()
        (bad_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Bad")
        good_post = posts_dir / "good"
        good_post.mkdir()
        (good_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Good Post")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)

        from backend.filesystem.frontmatter import parse_post

        original_parse_post = parse_post

        def _parse_post_raising_key_error(
            raw_content: str, file_path: str = "", fallback_tz: str = "UTC"
        ) -> Any:
            if "Bad" in raw_content:
                raise KeyError("missing_key")
            return original_parse_post(raw_content, file_path=file_path, fallback_tz=fallback_tz)

        with patch(
            "backend.filesystem.content_manager.parse_post",
            side_effect=_parse_post_raising_key_error,
        ):
            posts = cm.scan_posts()

        assert len(posts) == 1
        assert posts[0].title == "Good Post"

    def test_scan_posts_skips_post_raising_type_error(self, tmp_path: Path) -> None:
        """scan_posts should catch TypeError from parse_post and skip the bad post."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        bad_post = posts_dir / "bad"
        bad_post.mkdir()
        (bad_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Bad")
        good_post = posts_dir / "good"
        good_post.mkdir()
        (good_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Good Post")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)

        from backend.filesystem.frontmatter import parse_post

        original_parse_post = parse_post

        def _parse_post_raising_type_error(
            raw_content: str, file_path: str = "", fallback_tz: str = "UTC"
        ) -> Any:
            if "Bad" in raw_content:
                raise TypeError("unexpected type")
            return original_parse_post(raw_content, file_path=file_path, fallback_tz=fallback_tz)

        with patch(
            "backend.filesystem.content_manager.parse_post",
            side_effect=_parse_post_raising_type_error,
        ):
            posts = cm.scan_posts()

        assert len(posts) == 1
        assert posts[0].title == "Good Post"

    def test_read_post_returns_none_on_key_error(self, tmp_path: Path) -> None:
        """read_post should catch KeyError from parse_post and return None."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        bad_post = posts_dir / "bad"
        bad_post.mkdir()
        (bad_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Bad")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)

        with patch(
            "backend.filesystem.content_manager.parse_post",
            side_effect=KeyError("missing_key"),
        ):
            result = cm.read_post("posts/bad/index.md")

        assert result is None

    def test_read_post_returns_none_on_type_error(self, tmp_path: Path) -> None:
        """read_post should catch TypeError from parse_post and return None."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        bad_post = posts_dir / "bad"
        bad_post.mkdir()
        (bad_post / "index.md").write_text("---\ncreated_at: 2025-01-01\n---\n# Bad")
        (tmp_path / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (tmp_path / "labels.toml").write_text("")

        cm = ContentManager(content_dir=tmp_path)

        with patch(
            "backend.filesystem.content_manager.parse_post",
            side_effect=TypeError("unexpected type"),
        ):
            result = cm.read_post("posts/bad/index.md")

        assert result is None


class TestAtprotoOAuthOSError:
    """Issue #2: OSError from _load_existing() not caught (TOCTOU race)."""

    def test_load_or_create_handles_os_error_on_initial_load(self, tmp_path: Path) -> None:
        """If path.exists() is True but read_text() raises OSError, should regenerate."""
        keypair_path = tmp_path / "keypair.json"
        # Create a file so path.exists() returns True
        keypair_path.write_text("placeholder")

        # Mock _load_existing at the inner function level is hard.
        # Instead, mock path.read_text to raise OSError after path.exists() returns True.
        # We create a real file then delete it between exists() check and read_text().
        # Simpler: just make the file unreadable via mock.
        def _read_text_oserror(*args: Any, **kwargs: Any) -> str:
            raise OSError("file was deleted between exists() and read_text()")

        with patch.object(type(keypair_path), "read_text", _read_text_oserror):
            # This should not crash - it should regenerate a fresh keypair
            _, jwk = load_or_create_keypair(keypair_path)

        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert "kid" in jwk

    def test_load_or_create_handles_os_error_during_lock_wait(self, tmp_path: Path) -> None:
        """OSError during lock-wait _load_existing should not crash.

        Simulates: lock file exists, keypair file exists but read_text raises OSError.
        After a few failed attempts, remove the lock file so the lock can be acquired.
        """

        keypair_path = tmp_path / "keypair.json"
        lock_path = keypair_path.with_name(f".{keypair_path.name}.lock")

        # Create lock file to force the FileExistsError branch
        lock_path.write_text("")

        # Create keypair file so path.exists() returns True inside the loop
        keypair_path.write_text("placeholder")

        os_open_call_count = 0
        original_os_open = os.open

        def _os_open_eventually_succeeds(path_arg: str, flags: int, mode: int = 0o777) -> int:
            nonlocal os_open_call_count
            os_open_call_count += 1
            if os_open_call_count <= 3:
                raise FileExistsError("lock exists")
            # After 3 attempts, remove the lock and let it succeed
            lock_path.unlink(missing_ok=True)
            return original_os_open(str(path_arg), flags, mode)

        original_read_text = type(keypair_path).read_text

        read_call_count = 0

        def _read_text_fails_initially(self_path: Path, *args: Any, **kwargs: Any) -> str:
            nonlocal read_call_count
            read_call_count += 1
            if read_call_count <= 3:
                raise OSError("TOCTOU race")
            return original_read_text(self_path, *args, **kwargs)

        with (
            patch.object(type(keypair_path), "read_text", _read_text_fails_initially),
            patch("os.open", side_effect=_os_open_eventually_succeeds),
            patch("time.sleep"),
        ):
            _, jwk = load_or_create_keypair(keypair_path)

        assert jwk["kty"] == "EC"

    def test_load_or_create_handles_os_error_after_lock_acquired(self, tmp_path: Path) -> None:
        """OSError in _load_existing after lock acquired should regenerate."""
        from backend.crosspost.atproto_oauth import generate_es256_keypair, serialize_keypair

        keypair_path = tmp_path / "keypair.json"

        # Create a valid keypair so the file exists
        pk, jwk_data = generate_es256_keypair()
        serialize_keypair(pk, jwk_data, keypair_path)

        original_read_text = type(keypair_path).read_text
        read_call_count = 0

        def _read_text_fails_then_works(self_path: Path, *args: Any, **kwargs: Any) -> str:
            nonlocal read_call_count
            read_call_count += 1
            # Fail on all read_text calls from _load_existing (1st = initial check,
            # 2nd = after lock acquired). serialize_keypair doesn't call read_text.
            if read_call_count <= 2:
                raise OSError("file vanished between exists and read")
            return original_read_text(self_path, *args, **kwargs)

        with patch.object(type(keypair_path), "read_text", _read_text_fails_then_works):
            _, jwk = load_or_create_keypair(keypair_path)

        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"


class TestPandocHttpErrorWrapped:
    """Issue #3: Non-NetworkError/TimeoutException httpx errors should be wrapped in RenderError."""

    async def test_decoding_error_wrapped_in_render_error(self) -> None:
        """httpx.DecodingError should be caught and wrapped in RenderError."""
        mock_server = MagicMock()
        mock_server.base_url = "http://localhost:1234"
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.DecodingError("bad encoding")

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
            pytest.raises(RenderError, match="communication error"),
        ):
            await _render_markdown(
                "# test",
                from_format="markdown",
                sanitizer=lambda x: x,
            )

    async def test_protocol_error_wrapped_in_render_error(self) -> None:
        """httpx.ProtocolError should be caught and wrapped in RenderError."""
        mock_server = MagicMock()
        mock_server.base_url = "http://localhost:1234"
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.ProtocolError("protocol violation")

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
            pytest.raises(RenderError, match="communication error"),
        ):
            await _render_markdown(
                "# test",
                from_format="markdown",
                sanitizer=lambda x: x,
            )

    async def test_network_error_still_triggers_restart(self) -> None:
        """httpx.NetworkError should still trigger restart (existing behavior preserved)."""
        mock_server = MagicMock()
        mock_server.base_url = "http://localhost:1234"
        mock_server.ensure_running = AsyncMock()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # First call: NetworkError. Second call (after restart): also fails
        mock_client.post.side_effect = [
            httpx.ConnectError("connection refused"),
            httpx.ConnectError("still refused"),
        ]

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
            pytest.raises(RenderError, match="unreachable after restart"),
        ):
            await _render_markdown(
                "# test",
                from_format="markdown",
                sanitizer=lambda x: x,
            )

        # Verify restart was attempted
        mock_server.ensure_running.assert_awaited_once()

    async def test_timeout_still_raises_render_error(self) -> None:
        """httpx.TimeoutException should still be wrapped (existing behavior preserved)."""
        mock_server = MagicMock()
        mock_server.base_url = "http://localhost:1234"
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.ReadTimeout("timed out")

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
            pytest.raises(RenderError, match="timed out"),
        ):
            await _render_markdown(
                "# test",
                from_format="markdown",
                sanitizer=lambda x: x,
            )
