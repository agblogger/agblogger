# Alembic Migration System for Durable Tables

## Problem

AgBlogger stores user accounts, tokens, invites, and social account data exclusively in SQLite. The database is currently initialized via `Base.metadata.create_all` on every startup, which cannot alter existing tables. Schema changes to durable tables require either manual intervention or data loss. Alembic is scaffolded but inert (`target_metadata = None`, no migration scripts).

## Design

### Separation of Base Classes

Split `backend/models/base.py` into two declarative bases:

- **`DurableBase`** — tables that persist across restarts and upgrades: `users`, `refresh_tokens`, `personal_access_tokens`, `invite_codes`, `social_accounts`, `cross_posts`
- **`CacheBase`** — tables that are dropped and regenerated on startup and during sync: `posts_cache`, `labels_cache`, `label_parents_cache`, `post_labels_cache`, `sync_manifest`

Each model file uses the appropriate base. The `posts_fts` virtual table stays as raw SQL (not an ORM model).

### Alembic Configuration

- Set `target_metadata = DurableBase.metadata` in `backend/migrations/env.py`
- Wire up the database URL from settings/env vars so the CLI works for generating migrations during development
- Generate one initial migration that creates all six durable tables with their current schema
- Remove `_ensure_crosspost_user_id_column` from `main.py` — the initial migration includes `user_id` on `cross_posts`

### Startup Flow

The new startup sequence in `main.py` lifespan:

1. Create engine and session factory (unchanged)
2. Run `alembic upgrade head` programmatically — creates/migrates all durable tables
3. `CacheBase.metadata.drop_all` — drops cache tables (replaces hardcoded SQL strings)
4. `CacheBase.metadata.create_all` — recreates cache tables
5. Create FTS5 virtual table via raw SQL (unchanged)
6. Bootstrap admin user, start Pandoc, rebuild cache (unchanged)

Durable tables are never dropped. Cache tables are always regenerated. The drop logic uses `CacheBase.metadata` instead of hardcoded table names, staying in sync with models automatically.

### Testing

- Verify `alembic upgrade head` on a fresh database creates the expected durable tables
- Verify cache tables are absent until `CacheBase.metadata.create_all`
- Existing startup and integration tests continue to pass (observable behavior unchanged)
- No downgrade tests (no backward compatibility requirement)

### Architecture Doc Updates

Update `docs/arch/backend.md` and `docs/arch/deployment.md` to reflect:

- The two-base-class model (DurableBase vs CacheBase)
- Alembic manages durable table schema; cache tables are regenerated on startup
- Migrations run programmatically in the app lifespan, not via entrypoint scripts

## Files Changed

| File | Change |
|---|---|
| `backend/models/base.py` | Add `DurableBase` and `CacheBase` |
| `backend/models/user.py` | Switch to `DurableBase` |
| `backend/models/crosspost.py` | Switch to `DurableBase` |
| `backend/models/cache.py` | Switch to `CacheBase` |
| `backend/migrations/env.py` | Set `target_metadata = DurableBase.metadata`, wire DB URL |
| `backend/migrations/versions/` | Initial migration for six durable tables |
| `backend/main.py` | Programmatic Alembic upgrade, CacheBase drop/create, remove ad-hoc backfill |
| `alembic.ini` | Update URL handling for dev CLI |
| `docs/arch/backend.md` | Document two-base model and migration strategy |
| `docs/arch/deployment.md` | Document migrations running in app lifespan |
| Tests | Add migration tests |
