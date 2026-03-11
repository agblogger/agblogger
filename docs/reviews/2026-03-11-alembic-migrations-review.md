# PR Review: Alembic Migration Support

**Date:** 2026-03-11
**Scope:** 27 files, ~1,282 additions — Alembic migration support with DurableBase/CacheBase split
**Reviewed against:** origin/main

## Critical Issues (2 found)

### 1. `noqa` comment violates CLAUDE.md
- **File:** `backend/migrations/env.py:16`
- `# noqa: F401` is forbidden by project rules, inconsistent (line 15 has same import without it), and inert (directory excluded from linting).

### 2. Factually incorrect comment about `posts_fts`
- **File:** `backend/main.py:138`
- Says "not in CacheBase metadata" but `PostsFTS` inherits from `CacheBase` and IS in its metadata. The real reason for explicit drop is SQLAlchemy can't correctly handle FTS5 virtual tables via `drop_all`/`create_all`.

## Important Issues (4 found)

### 3. Missing `render_as_batch=True` for SQLite
- **File:** `backend/migrations/env.py` — both `context.configure()` calls
- Without batch mode, future migrations modifying columns will fail on SQLite's limited `ALTER TABLE` support.

### 4. `ensure_tables` bypasses Alembic
- **File:** `backend/services/cache_service.py`
- Calls `DurableBase.metadata.create_all` directly without stamping `alembic_version`. Should use `run_durable_migrations` instead.

### 5. Single try/except for two distinct startup steps
- **File:** `backend/main.py:179-185`
- Both `run_durable_migrations` and `setup_cache_tables` in one try block with a generic message. Should be separate for debuggability.

### 6. No `exc_info=True` on critical startup log
- **File:** `backend/main.py:184`
- CRITICAL log doesn't include traceback, losing valuable debugging info.

## Test Coverage Gaps (3 found)

### 7. No migration-vs-ORM schema match test
- Nothing verifies the hand-written migration produces the same schema as `DurableBase.metadata.create_all`. Schema drift is a real risk.

### 8. No test that `setup_cache_tables` preserves durable data
- If `CacheBase.metadata.drop_all` accidentally touched durable tables, users would lose all auth data on every restart.

### 9. Cache idempotency test assertion too weak
- `test_setup_cache_tables_is_idempotent` only checks `posts_cache`, not all expected cache tables.

## Suggestions (5 found)

### 10. `PostsFTS` docstring references Alembic incorrectly
- **File:** `backend/models/post.py:46-47`
- Says "rather than through Alembic" but issue is SQLAlchemy's `create_all`, not Alembic.

### 11. `ensure_tables` docstring is stale
- **File:** `backend/services/cache_service.py:150`
- Says "for development" but only used in tests. Should warn about Alembic bypass.

### 12. `setup_cache_tables` docstring references removed code
- **File:** `backend/main.py:135`
- "This replaces hardcoded DROP TABLE statements" is historical context that won't help post-merge.

### 13. Incomplete enumeration in deployment docs
- **File:** `docs/arch/deployment.md:21`
- Lists only some durable tables, omits invite codes and cross-posts.

### 14. Add partition regression tests
- Assert `DurableBase.metadata.tables.keys()` and `CacheBase.metadata.tables.keys()` match expected sets, and that no cross-base foreign keys exist.

## Strengths

- **DurableBase/CacheBase split is well-designed** — separate `MetaData` registries provide structural protection
- **All models correctly categorized** — auth/identity durable, content-derived cache
- **No cross-base foreign keys** — essential for drop-and-recreate safety
- **Test infrastructure mirrors production** — `conftest.py` uses same startup path
- **Clean elimination of ad-hoc migration shims** — old `_ensure_crosspost_user_id_column` properly replaced
- **Good docstrings on new functions** — `run_durable_migrations` explains both "how" and "why"
