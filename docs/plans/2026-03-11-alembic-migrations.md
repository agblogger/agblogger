# Alembic Migration System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up Alembic to manage durable database tables (users, tokens, invites, social accounts, cross-posts) so schema changes preserve data across upgrades. Cache tables remain drop-and-recreate.

**Architecture:** Split the single `Base` declarative base into `DurableBase` (Alembic-managed, persistent) and `CacheBase` (dropped and regenerated on startup/sync). Alembic runs programmatically in the app lifespan before cache setup. No backward compatibility with pre-existing databases.

**Tech Stack:** SQLAlchemy 2.x, Alembic, async SQLite (aiosqlite)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/models/base.py` | Modify | Define `DurableBase` and `CacheBase` declarative bases |
| `backend/models/user.py` | Modify | Switch from `Base` to `DurableBase` |
| `backend/models/crosspost.py` | Modify | Switch from `Base` to `DurableBase` |
| `backend/models/post.py` | Modify | Switch from `Base` to `CacheBase` |
| `backend/models/label.py` | Modify | Switch from `Base` to `CacheBase` |
| `backend/models/sync.py` | Modify | Switch from `Base` to `CacheBase` |
| `backend/models/__init__.py` | Modify | Export `DurableBase` and `CacheBase` instead of `Base` |
| `backend/migrations/env.py` | Modify | Set `target_metadata = DurableBase.metadata`, wire DB URL from env |
| `alembic.ini` | Modify | Add env var override for database URL |
| `backend/main.py` | Modify | Replace `create_all` + ad-hoc backfill with Alembic upgrade + `CacheBase` drop/create |
| `backend/services/cache_service.py` | Modify | Update `ensure_tables` to use `CacheBase` |
| `tests/conftest.py` | Modify | Update `create_test_client` and `db_engine` to use new base classes |
| `backend/migrations/versions/0001_initial_durable_tables.py` | Create | Initial migration for all six durable tables |
| `tests/test_services/test_migrations.py` | Create | Migration tests |
| `tests/test_api/test_crosspost_helpers.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `tests/test_api/test_error_handling.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `tests/test_services/test_post_author_display_name.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `tests/test_services/test_invite_code.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `tests/test_services/test_pat_last_used.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `tests/test_services/test_auth_service.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `tests/test_services/test_crosspost_decrypt_fallback.py` | Modify | Replace `Base` import with `DurableBase`/`CacheBase` |
| `docs/arch/backend.md` | Modify | Document two-base model and Alembic migration strategy |
| `docs/arch/deployment.md` | Modify | Document migrations running in app lifespan |

---

## Chunk 1: Split Base Classes and Update Models

### Task 1: Create DurableBase and CacheBase

**Files:**
- Modify: `backend/models/base.py`

- [ ] **Step 1: Update base.py with two declarative bases**

Replace the single `Base` with `DurableBase` and `CacheBase`:

```python
"""Base models for durable and cache tables."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class DurableBase(DeclarativeBase):
    """Base class for durable tables managed by Alembic migrations.

    Tables: users, refresh_tokens, personal_access_tokens, invite_codes,
    social_accounts, cross_posts.
    """


class CacheBase(DeclarativeBase):
    """Base class for cache tables dropped and regenerated on startup.

    Tables: posts_cache, labels_cache, label_parents_cache,
    post_labels_cache, sync_manifest, posts_fts.
    """


# Temporary alias so existing consumers that import Base keep working
# while migration to DurableBase/CacheBase is in progress.
# Removed in Task 12 after all consumers are updated.
Base = DurableBase
```

- [ ] **Step 2: Commit**

```bash
git add backend/models/base.py
git commit -m "refactor: split Base into DurableBase and CacheBase"
```

### Task 2: Switch durable models to DurableBase

**Files:**
- Modify: `backend/models/user.py` — change `from backend.models.base import Base` to `from backend.models.base import DurableBase`, change `class User(Base):` to `class User(DurableBase):`, same for `RefreshToken`, `PersonalAccessToken`, `InviteCode`
- Modify: `backend/models/crosspost.py` — same pattern for `SocialAccount` and `CrossPost`

- [ ] **Step 1: Update user.py**

Change the import on line 10:
```python
from backend.models.base import DurableBase
```

Change all four model classes to inherit from `DurableBase` instead of `Base`:
- `class User(DurableBase):` (line 16)
- `class RefreshToken(DurableBase):` (line 52)
- `class PersonalAccessToken(DurableBase):` (line 68)
- `class InviteCode(DurableBase):` (line 87)

- [ ] **Step 2: Update crosspost.py**

Change the import on line 10:
```python
from backend.models.base import DurableBase
```

Change both model classes:
- `class SocialAccount(DurableBase):` (line 17)
- `class CrossPost(DurableBase):` (line 37)

- [ ] **Step 3: Commit**

```bash
git add backend/models/user.py backend/models/crosspost.py
git commit -m "refactor: switch durable models to DurableBase"
```

### Task 3: Switch cache models to CacheBase

**Files:**
- Modify: `backend/models/post.py` — change to `CacheBase` for `PostCache` and `PostsFTS`
- Modify: `backend/models/label.py` — change to `CacheBase` for `LabelCache`, `LabelParentCache`, `PostLabelCache`
- Modify: `backend/models/sync.py` — change to `CacheBase` for `SyncManifest`

- [ ] **Step 1: Update post.py**

Change import on line 11:
```python
from backend.models.base import CacheBase
```

Change classes:
- `class PostCache(CacheBase):` (line 17)
- `class PostsFTS(CacheBase):` (line 43)

- [ ] **Step 2: Update label.py**

Change import on line 10:
```python
from backend.models.base import CacheBase
```

Change classes:
- `class LabelCache(CacheBase):` (line 16)
- `class LabelParentCache(CacheBase):` (line 40)
- `class PostLabelCache(CacheBase):` (line 56)

- [ ] **Step 3: Update sync.py**

Change import on line 8:
```python
from backend.models.base import CacheBase
```

Change class:
- `class SyncManifest(CacheBase):` (line 11)

- [ ] **Step 4: Commit**

```bash
git add backend/models/post.py backend/models/label.py backend/models/sync.py
git commit -m "refactor: switch cache models to CacheBase"
```

### Task 4: Update models __init__.py

**Files:**
- Modify: `backend/models/__init__.py`

- [ ] **Step 1: Update exports**

Replace contents with:

```python
"""SQLAlchemy ORM models for AgBlogger."""

from backend.models.base import Base, CacheBase, DurableBase
from backend.models.crosspost import CrossPost, SocialAccount
from backend.models.label import LabelCache, LabelParentCache, PostLabelCache
from backend.models.post import PostCache, PostsFTS
from backend.models.sync import SyncManifest
from backend.models.user import InviteCode, PersonalAccessToken, RefreshToken, User

__all__ = [
    "Base",
    "CacheBase",
    "CrossPost",
    "DurableBase",
    "InviteCode",
    "LabelCache",
    "LabelParentCache",
    "PersonalAccessToken",
    "PostCache",
    "PostLabelCache",
    "PostsFTS",
    "RefreshToken",
    "SocialAccount",
    "SyncManifest",
    "User",
]
```

- [ ] **Step 2: Verify no import breakage**

```bash
python -c "from backend.models.base import Base, DurableBase, CacheBase; print('OK')"
```

Expected: prints `OK`. The `Base` alias keeps all existing consumers working during the transition.

- [ ] **Step 3: Commit**

```bash
git add backend/models/__init__.py
git commit -m "refactor: export DurableBase and CacheBase from models"
```

---

## Chunk 2: Wire Up Alembic and Create Initial Migration

### Task 5: Configure Alembic env.py

**Files:**
- Modify: `backend/migrations/env.py`

- [ ] **Step 1: Wire up target_metadata and DB URL**

Replace the full contents of `backend/migrations/env.py`:

```python
"""Alembic environment configuration for async SQLite."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import DurableBase so Alembic sees only durable table metadata.
# Cache tables use a separate CacheBase and are not managed by Alembic.
from backend.models.base import DurableBase

# Ensure all durable model modules are imported so their tables register
# on DurableBase.metadata before autogenerate runs.
import backend.models.user  # noqa: F401
import backend.models.crosspost  # noqa: F401

target_metadata = DurableBase.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow DATABASE_URL env var to override alembic.ini for CLI usage.
env_url = os.environ.get("DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Note: The `noqa: F401` comments on the model imports are necessary here because Alembic's autogenerate relies on models being imported as a side effect to register tables on `DurableBase.metadata`. Without these imports, autogenerate would see an empty metadata and generate no tables. The imports are intentionally unused — their purpose is registration, not direct use.

- [ ] **Step 2: Commit**

```bash
git add backend/migrations/env.py
git commit -m "feat: wire Alembic env.py to DurableBase metadata"
```

### Task 6: Write the initial migration

**Files:**
- Create: `backend/migrations/versions/0001_initial_durable_tables.py`

- [ ] **Step 1: Generate the migration using Alembic CLI**

Run from repo root:
```bash
DATABASE_URL="sqlite+aiosqlite:///data/db/agblogger.db" alembic revision --autogenerate -m "initial durable tables"
```

This will generate a migration file in `backend/migrations/versions/`. Verify it creates exactly six tables: `users`, `refresh_tokens`, `personal_access_tokens`, `invite_codes`, `social_accounts`, `cross_posts`. It must NOT contain any cache tables (`posts_cache`, `labels_cache`, etc.).

If running autogenerate fails or produces incorrect output, write the migration manually. The upgrade function should create all six durable tables with their columns, constraints, indexes, and foreign keys matching the current model definitions in `backend/models/user.py` and `backend/models/crosspost.py`. The downgrade function should drop all six tables in reverse dependency order.

- [ ] **Step 2: Review the generated migration**

Open the generated file and verify:
- Only durable tables are present (no cache tables)
- All columns match the model definitions
- Foreign keys, unique constraints, and indexes are correct
- The `cross_posts.user_id` column is nullable (matching the model)

- [ ] **Step 3: Rename migration file for clarity**

Rename the generated file to `0001_initial_durable_tables.py` (keeping the revision ID inside the file unchanged).

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/0001_initial_durable_tables.py
git commit -m "feat: add initial Alembic migration for durable tables"
```

---

## Chunk 3: Update Application Startup

### Task 7: Add programmatic Alembic upgrade to main.py lifespan

**Files:**
- Modify: `backend/main.py:37,105-120,152-179`

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_migrations.py`:

```python
"""Tests for Alembic migration integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class TestAlembicMigration:
    """Verify Alembic creates durable tables on a fresh database."""

    DURABLE_TABLES = {
        "users",
        "refresh_tokens",
        "personal_access_tokens",
        "invite_codes",
        "social_accounts",
        "cross_posts",
    }

    CACHE_TABLES = {
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
        # alembic_version table should also exist
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

        # Durable tables must exist first (cache tables have no FK to them,
        # but we test the real startup order).
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_services/test_migrations.py -v
```

Expected: FAIL — `run_durable_migrations` and `setup_cache_tables` don't exist yet.

- [ ] **Step 3: Implement run_durable_migrations and setup_cache_tables in main.py**

Add these two functions to `backend/main.py` (after the imports, before the `lifespan` function). Also update imports.

Add to the imports at the top of main.py:
```python
from backend.models.base import CacheBase
```

Remove the existing import of `Base`:
```python
# DELETE: from backend.models.base import Base
```

Add the two new functions:

```python
async def run_durable_migrations(engine: AsyncEngine) -> None:
    """Run Alembic migrations for durable tables."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    # Use the engine's URL so migrations target the same database.
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: command.upgrade(alembic_cfg, "head"))


async def setup_cache_tables(engine: AsyncEngine) -> None:
    """Drop and recreate all cache tables.

    Cache tables use CacheBase and are regenerated from the filesystem
    on every startup. This replaces hardcoded DROP TABLE statements.
    """
    async with engine.begin() as conn:
        # Drop posts_fts first (virtual table, not in CacheBase metadata).
        await conn.execute(text("DROP TABLE IF EXISTS posts_fts"))
        await conn.run_sync(CacheBase.metadata.drop_all)
        await conn.run_sync(CacheBase.metadata.create_all)
        # Recreate FTS5 virtual table (not managed by ORM).
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                "title, content, content='posts_cache', content_rowid='id')"
            )
        )
```

Note: `AsyncEngine` is already imported at top level via `from sqlalchemy.ext.asyncio import ...` — check the existing imports and add it if missing. The `text` import is already present.

- [ ] **Step 4: Update the lifespan function**

Replace the database schema setup block in `lifespan()` (lines 152-176, from `try:` through FTS creation) with:

```python
        try:
            await run_durable_migrations(engine)
            await setup_cache_tables(engine)
        except Exception as exc:
            logger.critical("Failed to set up database schema: %s", exc)
            raise
```

Also delete the `_ensure_crosspost_user_id_column` function (lines 105-120) and its call (line 167). The initial migration already includes `user_id` on `cross_posts`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_services/test_migrations.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_services/test_migrations.py
git commit -m "feat: run Alembic migrations programmatically on startup"
```

---

## Chunk 4: Update Test Infrastructure and cache_service

### Task 8: Update test conftest.py

**Files:**
- Modify: `tests/conftest.py:174,190-200`

- [ ] **Step 1: Update create_test_client**

In `tests/conftest.py`, in the `create_test_client` function:

Change the import on line 174:
```python
# OLD: from backend.models.base import Base
from backend.models.base import CacheBase, DurableBase
```

Replace the `Base.metadata.create_all` block (lines 190-200) with:

```python
        # Set up durable tables via Alembic, then cache tables.
        from backend.main import run_durable_migrations, setup_cache_tables

        await run_durable_migrations(engine)
        await setup_cache_tables(engine)
```

This removes the manual FTS creation from conftest since `setup_cache_tables` handles it.

- [ ] **Step 2: Run the full test suite to check for regressions**

```bash
just test
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "refactor: update test conftest to use Alembic migrations"
```

### Task 9: Update cache_service.py ensure_tables

**Files:**
- Modify: `backend/services/cache_service.py:149-163`

- [ ] **Step 1: Update ensure_tables to use both bases**

Replace the `ensure_tables` function (lines 149-163):

```python
async def ensure_tables(session: AsyncSession) -> None:
    """Create all tables if they don't exist (for development)."""
    from backend.models.base import CacheBase, DurableBase

    conn = await session.connection()
    await conn.run_sync(DurableBase.metadata.create_all)
    await conn.run_sync(CacheBase.metadata.create_all)

    # Create FTS table
    await session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
            "title, content, content='posts_cache', content_rowid='id')"
        )
    )
    await session.commit()
```

- [ ] **Step 2: Run tests**

```bash
just test
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/services/cache_service.py
git commit -m "refactor: update ensure_tables to use DurableBase and CacheBase"
```

---

## Chunk 5: Update Architecture Docs and Final Verification

### Task 10: Update architecture docs

**Files:**
- Modify: `docs/arch/backend.md`
- Modify: `docs/arch/deployment.md`

- [ ] **Step 1: Update backend.md**

Add a new section after "Persistence layer" in the Architectural Layers section (around line 20). Update the "Persistence layer" bullet:

```
- **Persistence layer**: SQLAlchemy models split into durable tables (Alembic-managed) and regenerable cache tables
```

Add a new section after "Write Coordination" (after line 49):

```markdown
## Database Schema Management

The database uses two separate declarative bases to distinguish durable state from derived cache state:

- **DurableBase** tables (users, tokens, invites, social accounts, cross-posts) are managed by Alembic migrations. Schema changes are applied programmatically during application startup via `alembic upgrade head`. These tables persist across restarts and upgrades.
- **CacheBase** tables (posts cache, labels cache, label associations, sync manifest) are dropped and recreated on every startup. Their content is rebuilt from the filesystem.

This separation means adding a column to a durable table requires an Alembic migration, while cache table schema changes take effect automatically on the next restart.
```

- [ ] **Step 2: Update deployment.md**

Add a new section after "Packaging" (after line 19):

```markdown
## Schema Migrations

Database schema migrations run programmatically during application startup, before the server begins accepting requests. Durable tables (user accounts, authentication tokens, social account connections) are managed by Alembic, so upgrades apply schema changes without data loss. Cache tables are regenerated from the filesystem on every startup and do not require migrations.
```

- [ ] **Step 3: Commit**

```bash
git add docs/arch/backend.md docs/arch/deployment.md
git commit -m "docs: document Alembic migration strategy in architecture docs"
```

### Task 11: Remove Base alias and update remaining consumers

**Files:**
- Modify: `backend/models/base.py` — remove `Base = DurableBase` alias
- Modify: `backend/models/__init__.py` — remove `Base` from imports and `__all__`
- Modify: any remaining test files that import `Base`

- [ ] **Step 1: Find all remaining Base imports**

```bash
grep -rn "from backend.models.base import Base" backend/ tests/
grep -rn "from backend.models import Base" backend/ tests/
```

For each file found, determine if it uses `Base` for durable tables (replace with `DurableBase`) or for all tables via `Base.metadata.create_all` (replace with both `DurableBase` and `CacheBase` as appropriate).

Known files from the current codebase that import `Base` and need updating (beyond those already handled in earlier tasks):
- `tests/test_api/test_crosspost_helpers.py`
- `tests/test_api/test_error_handling.py`
- `tests/test_services/test_post_author_display_name.py`
- `tests/test_services/test_invite_code.py`
- `tests/test_services/test_pat_last_used.py`
- `tests/test_services/test_auth_service.py`
- `tests/test_services/test_crosspost_decrypt_fallback.py`

In each file, replace `from backend.models.base import Base` (or `from backend.models import Base`) with the appropriate import (`DurableBase`, `CacheBase`, or both) and update all usages. In test files that call `Base.metadata.create_all` to set up a test database, replace with:
```python
from backend.models.base import CacheBase, DurableBase
# ...
await conn.run_sync(DurableBase.metadata.create_all)
await conn.run_sync(CacheBase.metadata.create_all)
```

- [ ] **Step 2: Remove the Base alias from base.py**

In `backend/models/base.py`, delete the line:
```python
Base = DurableBase
```

- [ ] **Step 3: Remove Base from __init__.py**

In `backend/models/__init__.py`, remove `Base` from the import line and from `__all__`.

- [ ] **Step 4: Run full test suite**

```bash
just test
```

Expected: All tests pass with no references to the old `Base`.

- [ ] **Step 5: Commit**

```bash
git add -u backend/models/base.py backend/models/__init__.py tests/
git commit -m "refactor: remove Base alias, all consumers use DurableBase or CacheBase"
```

### Task 12: Final verification

- [ ] **Step 1: Verify no references to old Base remain**

```bash
grep -rn "from backend.models.base import Base" backend/ tests/
grep -rn "from backend.models import Base" backend/ tests/
```

Expected: No matches. All imports should reference `DurableBase` or `CacheBase`.

- [ ] **Step 2: Run full static checks and tests**

```bash
just check
```

Expected: All static checks and tests pass.

- [ ] **Step 3: Commit any remaining fixes**

If any issues were found, fix and commit with an appropriate message.
