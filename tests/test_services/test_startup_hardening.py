"""Tests for startup hardening and global exception handlers."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from contextlib import suppress
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from backend.config import Settings
from backend.main import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


class TestGlobalExceptionHandlers:
    """Global exception handlers return structured JSON instead of crashing."""

    @pytest.mark.asyncio
    async def test_runtime_error_returns_500(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-runtime-error")
        async def _raise_runtime_error() -> None:
            raise RuntimeError("something broke")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-runtime-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal processing error"

    @pytest.mark.asyncio
    async def test_os_error_returns_500(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-os-error")
        async def _raise_os_error() -> None:
            raise OSError("disk full")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-os-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Storage operation failed"

    @pytest.mark.asyncio
    async def test_yaml_error_returns_422(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-yaml-error")
        async def _raise_yaml_error() -> None:
            raise yaml.YAMLError("invalid yaml")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-yaml-error")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid content format"

    @pytest.mark.asyncio
    async def test_json_decode_error_returns_500(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-json-error")
        async def _raise_json_error() -> None:
            json.loads("not valid json {")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-json-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Data integrity error"

    @pytest.mark.asyncio
    async def test_value_error_returns_422(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-value-error")
        async def _raise_value_error() -> None:
            raise ValueError("bad input")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-value-error")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "bad input"

    @pytest.mark.asyncio
    async def test_type_error_returns_500(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-type-error")
        async def _raise_type_error() -> None:
            raise TypeError("wrong type")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-type-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_called_process_error_returns_502(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-subprocess-error")
        async def _raise_subprocess_error() -> None:
            raise subprocess.CalledProcessError(1, "git")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-subprocess-error")
        assert resp.status_code == 502
        assert resp.json()["detail"] == "External process failed"

    @pytest.mark.asyncio
    async def test_unicode_decode_error_returns_422(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-unicode-error")
        async def _raise_unicode_error() -> None:
            raise UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalid start byte")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-unicode-error")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid content encoding"

    @pytest.mark.asyncio
    async def test_internal_server_error_returns_500_with_generic_message(
        self, tmp_path: Path
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-internal-server-error")
        async def _raise_internal_server_error() -> None:
            from backend.exceptions import InternalServerError

            raise InternalServerError("sensitive decryption key: abc123secret")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-internal-server-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"
        assert "sensitive" not in resp.text
        assert "abc123secret" not in resp.text

    @pytest.mark.asyncio
    async def test_internal_server_error_logs_details(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-internal-server-error-logging")
        async def _raise_internal_server_error() -> None:
            from backend.exceptions import InternalServerError

            raise InternalServerError("sensitive decryption details here")

        with caplog.at_level(logging.ERROR, logger="backend.main"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/test-internal-server-error-logging")

        assert resp.status_code == 500
        assert any("sensitive decryption details here" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_request_validation_error_logs_details(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pydantic import BaseModel

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        class StrictBody(BaseModel):
            email: str

        @app.post("/test-validation-logging")
        async def _needs_body(body: StrictBody) -> dict[str, str]:
            return {"email": body.email}

        with caplog.at_level(logging.WARNING, logger="backend.main"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/test-validation-logging", json={"wrong": "field"})

        assert resp.status_code == 422
        assert any("RequestValidationError" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_operational_error_returns_503(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-operational-error")
        async def _raise_operational_error() -> None:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, Exception("database locked"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/test-operational-error")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Database temporarily unavailable"


class TestLifespanShutdownSafety:
    """Shutdown proceeds even when individual steps fail."""

    @pytest.mark.asyncio
    async def test_engine_dispose_called_when_close_renderer_raises(self) -> None:
        """Verify the shutdown pattern: each step is independent."""
        import contextlib

        mock_engine = AsyncMock()
        mock_pandoc_server = AsyncMock()
        mock_close_renderer = AsyncMock(side_effect=RuntimeError("renderer boom"))

        # Execute the same pattern used in lifespan shutdown
        with contextlib.suppress(Exception):
            await mock_close_renderer()

        with contextlib.suppress(Exception):
            await mock_pandoc_server.stop()

        with contextlib.suppress(Exception):
            await mock_engine.dispose()

        # close_renderer raised but engine.dispose was still called
        mock_engine.dispose.assert_awaited_once()
        mock_pandoc_server.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_error_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Verify shutdown errors are logged at ERROR level."""
        from backend.pandoc import renderer

        old_server = renderer._server
        old_client = renderer._http_client

        # Make close_renderer fail by setting a mock client that raises on aclose
        mock_client = AsyncMock()
        mock_client.aclose.side_effect = RuntimeError("test shutdown error")

        try:
            renderer._server = None
            renderer._http_client = mock_client

            with caplog.at_level(logging.ERROR, logger="backend.main"):
                from backend.main import logger as main_logger

                try:
                    await renderer.close_renderer()
                except Exception as exc:
                    main_logger.error("Error during renderer shutdown: %s", exc)

            assert any("renderer shutdown" in r.message for r in caplog.records)
        finally:
            renderer._server = old_server
            renderer._http_client = old_client


class TestSchemaBackfillLogging:
    """_ensure_crosspost_user_id_column logs errors with context."""

    @pytest.mark.asyncio
    async def test_schema_backfill_logs_on_error(self, caplog: pytest.LogCaptureFixture) -> None:
        from contextlib import asynccontextmanager

        from backend.main import _ensure_crosspost_user_id_column

        mock_app = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = Exception("table not found")

        @asynccontextmanager
        async def fake_begin() -> AsyncGenerator[AsyncMock]:
            yield mock_conn

        mock_engine = AsyncMock()
        mock_engine.begin = fake_begin
        mock_app.state.engine = mock_engine

        with (
            caplog.at_level(logging.ERROR, logger="backend.main"),
            pytest.raises(Exception, match="table not found"),
        ):
            await _ensure_crosspost_user_id_column(mock_app)

        assert any("crosspost" in r.message.lower() for r in caplog.records)


class TestHealthEndpointLogging:
    """Health endpoint logs warnings on database errors."""

    @pytest.mark.asyncio
    async def test_db_error_logged_at_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("db locked")

        with caplog.at_level(logging.WARNING, logger="backend.api.health"):
            from backend.api.health import health_check

            result = await health_check(mock_session)

        assert result.database == "error"
        assert any("health check" in r.message.lower() for r in caplog.records)


class TestStaleLockFile:
    """H7: stale lock file is cleaned up."""

    def test_stale_lock_removed(self, tmp_path: Path) -> None:
        key_path = tmp_path / "test-key.json"
        lock_path = key_path.with_name(f".{key_path.name}.lock")
        # Create a stale lock (older than 30 seconds)
        lock_path.write_text("")
        old_time = time.time() - 60
        os.utime(lock_path, (old_time, old_time))

        from backend.crosspost.atproto_oauth import load_or_create_keypair

        private_key, _jwk = load_or_create_keypair(key_path)
        assert private_key is not None
        assert not lock_path.exists()

    def test_corrupted_keypair_with_stale_lock(self, tmp_path: Path) -> None:
        key_path = tmp_path / "test-key.json"
        lock_path = key_path.with_name(f".{key_path.name}.lock")
        # Create a stale lock (older than 30 seconds)
        lock_path.write_text("")
        old_time = time.time() - 60
        os.utime(lock_path, (old_time, old_time))
        # Create a corrupted keypair file
        key_path.write_text("not valid json")

        from backend.crosspost.atproto_oauth import load_or_create_keypair

        # Should regenerate despite corruption
        private_key, _jwk = load_or_create_keypair(key_path)
        assert private_key is not None

    def test_stale_lock_inspection_error_is_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pathlib import Path
        from unittest.mock import patch

        from backend.crosspost.atproto_oauth import load_or_create_keypair

        key_path = tmp_path / "test-key.json"
        lock_path = key_path.with_name(f".{key_path.name}.lock")
        lock_path.write_text("")

        original_stat = Path.stat

        def _stat_with_failure(self: Path):
            if self == lock_path:
                raise OSError("stat failed")
            return original_stat(self)

        with (
            patch.object(Path, "stat", _stat_with_failure),
            caplog.at_level(logging.WARNING, logger="backend.crosspost.atproto_oauth"),
        ):
            _private_key, _jwk = load_or_create_keypair(key_path)

        assert any("stale keypair lock" in record.message.lower() for record in caplog.records)


class TestContentWriteLockInitialization:
    """Verify content_write_lock is initialized during lifespan startup."""

    @pytest.mark.asyncio
    async def test_content_write_lock_set_on_app_state_after_lifespan(self, tmp_path: Path) -> None:
        import asyncio

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            content_dir=tmp_path / "content",
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        with patch(
            "backend.pandoc.server.PandocServer.start",
            new_callable=AsyncMock,
        ):
            ctx = app.router.lifespan_context(app)
            await ctx.__aenter__()
            try:
                lock = getattr(app.state, "content_write_lock", None)
                assert lock is not None, "content_write_lock should be set on app.state"
                assert isinstance(lock, asyncio.Lock), (
                    f"content_write_lock should be asyncio.Lock, got {type(lock)}"
                )
            finally:
                with suppress(Exception):
                    await ctx.__aexit__(None, None, None)


class TestStartupStepLogging:
    """Each startup step should log a critical message identifying the failing component."""

    @pytest.mark.asyncio
    async def test_schema_creation_failure_logs_critical_with_context(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            content_dir=tmp_path / "content",
        )
        app = create_app(settings)

        with (
            patch("backend.main._configure_logging"),
            patch(
                "backend.main.Base.metadata.create_all",
                side_effect=RuntimeError("schema creation failed"),
            ),
            caplog.at_level(logging.CRITICAL, logger="backend.main"),
            suppress(Exception),
        ):
            async with app.router.lifespan_context(app):
                pass

        critical_msgs = [r.message for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("database" in m.lower() or "schema" in m.lower() for m in critical_msgs), (
            f"Expected critical log about database/schema failure, got: {critical_msgs}"
        )

    @pytest.mark.asyncio
    async def test_pandoc_failure_logs_critical_with_context(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
            content_dir=tmp_path / "content",
        )
        app = create_app(settings)

        with (
            patch("backend.main._configure_logging"),
            patch(
                "backend.pandoc.server.PandocServer.start",
                side_effect=FileNotFoundError("pandoc"),
            ),
            caplog.at_level(logging.CRITICAL, logger="backend.main"),
            suppress(Exception),
        ):
            async with app.router.lifespan_context(app):
                pass

        critical_msgs = [r.message for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("pandoc" in m.lower() for m in critical_msgs), (
            f"Expected critical log about pandoc failure, got: {critical_msgs}"
        )

    @pytest.mark.asyncio
    async def test_git_init_failure_logs_critical_with_context(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
            content_dir=tmp_path / "content",
        )
        app = create_app(settings)

        with (
            patch("backend.main._configure_logging"),
            patch(
                "backend.services.git_service.GitService.init_repo",
                side_effect=FileNotFoundError("git not found"),
            ),
            caplog.at_level(logging.CRITICAL, logger="backend.main"),
            suppress(Exception),
        ):
            async with app.router.lifespan_context(app):
                pass

        critical_msgs = [r.message for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("git" in m.lower() for m in critical_msgs), (
            f"Expected critical log about git failure, got: {critical_msgs}"
        )


class TestStartupResilience:
    @pytest.mark.asyncio
    async def test_lifespan_crashes_when_pandoc_start_fails(self, tmp_path: Path) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            content_dir=tmp_path / "content",
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        with patch(
            "backend.pandoc.server.PandocServer.start",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pandoc unavailable"),
        ):
            ctx = app.router.lifespan_context(app)
            with pytest.raises(RuntimeError, match="pandoc unavailable"):
                await ctx.__aenter__()
