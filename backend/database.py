"""Database engine and session management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from backend.config import Settings


def _set_sqlite_pragmas(dbapi_conn: Any, _connection_record: Any) -> None:
    """Configure SQLite for concurrent access on each new connection.

    - WAL mode allows readers to proceed concurrently with a single writer.
    - busy_timeout makes writers retry for up to 5 s instead of failing immediately.
    - synchronous=NORMAL is safe under WAL and avoids redundant fsync on every commit.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_engine(
    settings: Settings,
) -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
]:
    """Create async engine and session factory.

    Returns (engine, session_factory) tuple.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
    )

    if settings.database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Yield an async database session."""
    async with session_factory() as session:
        yield session
