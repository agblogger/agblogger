"""Tests for Alembic migration integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import inspect, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class TestAlembicMigration:
    """Verify Alembic creates durable tables on a fresh database."""

    DURABLE_TABLES: ClassVar[set[str]] = {
        "admin_users",
        "admin_refresh_tokens",
        "social_accounts",
        "cross_posts",
        "analytics_settings",
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

        expected_cache = {
            "posts_cache",
            "labels_cache",
            "label_parents_cache",
            "post_labels_cache",
            "sync_manifest",
            "posts_fts",
        }
        assert expected_cache.issubset(table_names)

    async def test_setup_cache_tables_preserves_durable_data(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """setup_cache_tables must not destroy durable table data."""
        from backend.main import run_durable_migrations, setup_cache_tables

        await run_durable_migrations(db_engine)

        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO admin_users (username, email, password_hash,"
                    " created_at, updated_at)"
                    " VALUES ('testuser', 'test@test.com', 'hash',"
                    " '2026-01-01', '2026-01-01')"
                )
            )

        await setup_cache_tables(db_engine)

        async with db_engine.connect() as conn:
            result = await conn.execute(text("SELECT username FROM admin_users"))
            rows = result.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "testuser"


class TestMigrationSchemaMatch:
    """Verify Alembic migration produces the same schema as ORM models."""

    async def test_migration_columns_match_orm_models(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """The Alembic migration should produce the same columns as DurableBase models."""
        from backend.main import run_durable_migrations
        from backend.models.base import DurableBase

        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            migrated_columns: dict[str, set[str]] = await conn.run_sync(
                lambda sc: {
                    table_name: {col["name"] for col in inspect(sc).get_columns(table_name)}
                    for table_name in inspect(sc).get_table_names()
                    if table_name != "alembic_version"
                }
            )

        for table_name, table in DurableBase.metadata.tables.items():
            assert table_name in migrated_columns, f"Table {table_name} missing from migration"
            orm_cols = {col.name for col in table.columns}
            migration_cols = migrated_columns[table_name]
            assert orm_cols == migration_cols, (
                f"Column mismatch in {table_name}: "
                f"ORM-only={orm_cols - migration_cols}, "
                f"migration-only={migration_cols - orm_cols}"
            )


class TestTablePartitionInvariants:
    """Verify DurableBase/CacheBase partition is correct and complete."""

    async def test_durable_tables_match_expected_set(self) -> None:
        """DurableBase.metadata must contain exactly the expected tables."""
        from backend.models.base import DurableBase

        expected = {
            "admin_users",
            "admin_refresh_tokens",
            "social_accounts",
            "cross_posts",
            "analytics_settings",
        }
        assert set(DurableBase.metadata.tables.keys()) == expected

    async def test_cache_tables_match_expected_set(self) -> None:
        """CacheBase.metadata must contain exactly the expected tables."""
        from backend.models.base import CacheBase

        expected = {
            "posts_cache",
            "labels_cache",
            "label_parents_cache",
            "post_labels_cache",
            "sync_manifest",
            "posts_fts",
        }
        assert set(CacheBase.metadata.tables.keys()) == expected

    async def test_no_cross_base_foreign_keys(self) -> None:
        """No CacheBase table should reference a DurableBase table or vice versa."""
        from backend.models.base import CacheBase, DurableBase

        durable_names = set(DurableBase.metadata.tables.keys())
        cache_names = set(CacheBase.metadata.tables.keys())

        for table in CacheBase.metadata.tables.values():
            for fk in table.foreign_keys:
                assert fk.column.table.name not in durable_names, (
                    f"Cache table {table.name} has FK to durable table {fk.column.table.name}"
                )
        for table in DurableBase.metadata.tables.values():
            for fk in table.foreign_keys:
                assert fk.column.table.name not in cache_names, (
                    f"Durable table {table.name} has FK to cache table {fk.column.table.name}"
                )
