"""Tests for database engine and session management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from backend.config import Settings
from backend.database import create_engine

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
