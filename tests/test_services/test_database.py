"""Tests for database engine and session management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from backend.config import Settings
from backend.database import _set_sqlite_pragmas, create_engine

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class TestDatabase:
    @pytest.mark.asyncio
    async def test_engine_connects(self, db_engine: AsyncEngine) -> None:
        async with db_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_session_works(self, db_session: AsyncSession) -> None:
        result = await db_session.execute(text("SELECT 42"))
        assert result.scalar() == 42


class TestSQLitePragmas:
    """Verify that SQLite connections are configured for concurrency."""

    @pytest.fixture
    def sqlite_settings(self, tmp_path: Path) -> Settings:
        db_path = tmp_path / "pragma_test.db"
        return Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=tmp_path / "content",
            frontend_dir=tmp_path / "frontend",
        )

    @pytest.mark.asyncio
    async def test_wal_mode_set_automatically(self, sqlite_settings: Settings) -> None:
        """WAL mode must be enabled on every new connection without manual PRAGMA calls."""
        engine, _session_factory = create_engine(sqlite_settings)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("PRAGMA journal_mode"))
                mode = result.scalar()
                assert mode == "wal"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_busy_timeout_set(self, sqlite_settings: Settings) -> None:
        """busy_timeout must be set so concurrent access retries instead of failing."""
        engine, _session_factory = create_engine(sqlite_settings)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("PRAGMA busy_timeout"))
                timeout = result.scalar()
                assert timeout is not None
                assert timeout >= 5000
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_synchronous_normal_with_wal(self, sqlite_settings: Settings) -> None:
        """synchronous=NORMAL is safe with WAL and avoids unnecessary fsync overhead."""
        engine, _session_factory = create_engine(sqlite_settings)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("PRAGMA synchronous"))
                # NORMAL = 1
                level = result.scalar()
                assert level == 1
        finally:
            await engine.dispose()


class TestSetSQLitePragmasErrorHandling:
    """Verify error handling and cursor lifecycle in _set_sqlite_pragmas."""

    def test_cursor_closed_even_when_pragma_fails(self) -> None:
        """cursor.close() must be called even when a PRAGMA execute raises."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("disk I/O error")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with pytest.raises(RuntimeError, match="disk I/O error"):
            _set_sqlite_pragmas(mock_conn, None)

        mock_cursor.close.assert_called_once()

    def test_pragma_failure_raises_and_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """A PRAGMA failure must propagate an exception and log a clear error message."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("database is locked")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with (
            caplog.at_level(logging.ERROR, logger="backend.database"),
            pytest.raises(RuntimeError),
        ):
            _set_sqlite_pragmas(mock_conn, None)

        assert any(
            "PRAGMA" in record.message or "pragma" in record.message.lower()
            for record in caplog.records
            if record.levelno >= logging.ERROR
        )

    def test_cursor_closed_on_success(self) -> None:
        """cursor.close() must be called on the happy path too."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        _set_sqlite_pragmas(mock_conn, None)

        mock_cursor.close.assert_called_once()


class TestNonSQLiteURLSkipsPragmaListener:
    """Verify that the pragma event listener is not attached for non-SQLite URLs."""

    def test_non_sqlite_url_does_not_attach_pragma_listener(self, tmp_path: Path) -> None:
        """A non-SQLite database URL must not register the pragma connect listener."""
        settings = Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url="postgresql+asyncpg://user:pass@localhost/testdb",
            content_dir=tmp_path / "content",
            frontend_dir=tmp_path / "frontend",
        )

        mock_engine = MagicMock()
        mock_sync_engine = MagicMock()
        mock_engine.sync_engine = mock_sync_engine
        mock_session_factory = MagicMock()

        with (
            patch("backend.database.create_async_engine", return_value=mock_engine),
            patch("backend.database.async_sessionmaker", return_value=mock_session_factory),
            patch("backend.database.event.listen") as mock_listen,
        ):
            create_engine(settings)
            mock_listen.assert_not_called()
