"""Tests for Alembic migration integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import inspect

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class TestAlembicMigration:
    """Verify Alembic creates durable tables on a fresh database."""

    DURABLE_TABLES: ClassVar[set[str]] = {
        "users",
        "refresh_tokens",
        "personal_access_tokens",
        "invite_codes",
        "social_accounts",
        "cross_posts",
    }

    CACHE_TABLES: ClassVar[set[str]] = {
        "posts_cache",
        "labels_cache",
        "label_parents_cache",
        "post_labels_cache",
        "sync_manifest",
    }

    async def test_run_durable_migrations_creates_durable_tables(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """Alembic upgrade head should create all durable tables."""
        from backend.main import run_durable_migrations

        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )

        assert self.DURABLE_TABLES.issubset(table_names)
        assert "alembic_version" in table_names

    async def test_run_durable_migrations_does_not_create_cache_tables(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """Alembic upgrade head should NOT create cache tables."""
        from backend.main import run_durable_migrations

        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )

        assert not self.CACHE_TABLES.intersection(table_names)

    async def test_run_durable_migrations_is_idempotent(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """Running migrations twice should succeed without error."""
        from backend.main import run_durable_migrations

        await run_durable_migrations(db_engine)
        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )

        assert self.DURABLE_TABLES.issubset(table_names)


class TestCacheTableSetup:
    """Verify cache tables are created separately from durable tables."""

    async def test_setup_cache_tables_creates_cache_tables(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """setup_cache_tables should create all cache tables."""
        from backend.main import run_durable_migrations, setup_cache_tables

        await run_durable_migrations(db_engine)
        await setup_cache_tables(db_engine)

        async with db_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )

        expected_cache = {
            "posts_cache",
            "labels_cache",
            "label_parents_cache",
            "post_labels_cache",
            "sync_manifest",
            "posts_fts",
        }
        assert expected_cache.issubset(table_names)

    async def test_setup_cache_tables_is_idempotent(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """Running cache setup twice should succeed (drop + recreate)."""
        from backend.main import run_durable_migrations, setup_cache_tables

        await run_durable_migrations(db_engine)
        await setup_cache_tables(db_engine)
        await setup_cache_tables(db_engine)

        async with db_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )

        assert "posts_cache" in table_names
