"""Tests for Alembic migration integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import inspect, text

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine


async def _upgrade_durable_migrations(db_engine: AsyncEngine, revision: str) -> None:
    """Run durable Alembic migrations to a specific revision."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "backend/migrations")

    def _do_upgrade(sync_conn: Connection) -> None:
        alembic_cfg.attributes["connection"] = sync_conn
        command.upgrade(alembic_cfg, revision)

    async with db_engine.begin() as conn:
        await conn.run_sync(_do_upgrade)


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

    async def test_setup_cache_tables_creates_posts_fts_with_subtitle_column(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """setup_cache_tables should recreate posts_fts as the expected FTS5 schema."""
        from backend.main import run_durable_migrations, setup_cache_tables

        await run_durable_migrations(db_engine)
        await setup_cache_tables(db_engine)

        async with db_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'posts_fts'")
            )
            create_sql = result.scalar_one()

        assert create_sql is not None
        assert "CREATE VIRTUAL TABLE" in create_sql
        assert "title, subtitle, content" in create_sql

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


class TestMigrationForeignKeyTargets:
    """Verify FK constraints point to the correct tables after all migrations."""

    async def test_social_accounts_fk_points_to_admin_users(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """social_accounts.user_id FK must reference admin_users, not users."""
        from backend.main import run_durable_migrations

        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            rows = (await conn.execute(text("PRAGMA foreign_key_list(social_accounts)"))).fetchall()

        # PRAGMA foreign_key_list returns (id, seq, table, from, to, on_update, on_delete, match)
        user_id_fks = [row for row in rows if row[3] == "user_id"]
        assert len(user_id_fks) == 1, f"Expected exactly one FK on user_id, got {user_id_fks}"
        assert user_id_fks[0][2] == "admin_users", (
            f"social_accounts.user_id FK points to '{user_id_fks[0][2]}', expected 'admin_users'"
        )

    async def test_cross_posts_fk_points_to_admin_users(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """cross_posts.user_id FK must reference admin_users, not users."""
        from backend.main import run_durable_migrations

        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            rows = (await conn.execute(text("PRAGMA foreign_key_list(cross_posts)"))).fetchall()

        user_id_fks = [row for row in rows if row[3] == "user_id"]
        assert len(user_id_fks) == 1, f"Expected exactly one FK on user_id, got {user_id_fks}"
        assert user_id_fks[0][2] == "admin_users", (
            f"cross_posts.user_id FK points to '{user_id_fks[0][2]}', expected 'admin_users'"
        )

    async def test_admin_refresh_tokens_fk_points_to_admin_users(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """admin_refresh_tokens.user_id FK must reference admin_users, not users."""
        from backend.main import run_durable_migrations

        await run_durable_migrations(db_engine)

        async with db_engine.connect() as conn:
            rows = (
                await conn.execute(text("PRAGMA foreign_key_list(admin_refresh_tokens)"))
            ).fetchall()

        user_id_fks = [row for row in rows if row[3] == "user_id"]
        assert len(user_id_fks) == 1, f"Expected exactly one FK on user_id, got {user_id_fks}"
        assert user_id_fks[0][2] == "admin_users", (
            f"admin_refresh_tokens.user_id FK points to '{user_id_fks[0][2]}',"
            " expected 'admin_users'"
        )


class TestLegacyUserMigration:
    """Verify migration from the legacy multi-user schema preserves auth boundaries."""

    async def test_upgrade_removes_non_admin_users_and_their_dependent_data(
        self,
        db_engine: AsyncEngine,
    ) -> None:
        """Upgrading to the single-admin schema must not promote legacy non-admin users."""
        await _upgrade_durable_migrations(db_engine, "b5d91f3e7a02")

        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users "
                    "("
                    "id, username, email, password_hash, display_name, "
                    "is_admin, created_at, updated_at"
                    ") "
                    "VALUES "
                    "("
                    "1, 'admin', 'admin@example.com', 'hash-1', 'Admin', "
                    "1, '2026-01-01', '2026-01-01'"
                    "), "
                    "("
                    "2, 'member', 'member@example.com', 'hash-2', 'Member', "
                    "0, '2026-01-01', '2026-01-01'"
                    ")"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO refresh_tokens "
                    "(id, user_id, token_hash, expires_at, created_at) "
                    "VALUES "
                    "(1, 1, 'admin-token', '2027-01-01', '2026-01-01'), "
                    "(2, 2, 'member-token', '2027-01-01', '2026-01-01')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO social_accounts "
                    "(id, user_id, platform, account_name, credentials, created_at, updated_at) "
                    "VALUES "
                    "(1, 2, 'mastodon', 'member@example.social', '{}', '2026-01-01', '2026-01-01')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO cross_posts "
                    "("
                    "id, user_id, post_path, platform, platform_id, "
                    "status, posted_at, error, created_at"
                    ") "
                    "VALUES "
                    "("
                    "1, 2, 'posts/member-post', 'mastodon', 'abc123', "
                    "'posted', NULL, NULL, '2026-01-01'"
                    ")"
                )
            )

        await _upgrade_durable_migrations(db_engine, "head")

        async with db_engine.connect() as conn:
            admin_users = (
                (await conn.execute(text("SELECT id, username FROM admin_users ORDER BY id")))
                .tuples()
                .all()
            )
            admin_refresh_tokens = (
                (
                    await conn.execute(
                        text("SELECT user_id, token_hash FROM admin_refresh_tokens ORDER BY id")
                    )
                )
                .tuples()
                .all()
            )
            social_accounts = (
                (
                    await conn.execute(
                        text("SELECT user_id, account_name FROM social_accounts ORDER BY id")
                    )
                )
                .tuples()
                .all()
            )
            cross_posts = (
                (await conn.execute(text("SELECT user_id, post_path FROM cross_posts ORDER BY id")))
                .tuples()
                .all()
            )

        assert admin_users == [(1, "admin")]
        assert admin_refresh_tokens == [(1, "admin-token")]
        assert social_accounts == []
        assert cross_posts == []


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
