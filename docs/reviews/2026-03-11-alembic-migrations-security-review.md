# Security Review: Alembic Migration Support

## Scope

Reviewed 16 commits ahead of `origin/main` introducing Alembic migration infrastructure: DurableBase/CacheBase split, programmatic migration execution on startup, initial migration script, env.py configuration, and cache table drop-and-recreate logic.

## Methodology

Examined all modified production files against the project's security guidelines (`docs/guidelines/security.md`, `docs/arch/security.md`), focusing on:

- SQL injection in migration scripts and env.py
- Template injection in the Mako script template
- Sensitive data exposure in startup error handling
- Path traversal in migration script resolution
- Durable data loss from cache table drop-and-recreate
- Authorization bypass potential
- Hardcoded secrets

## Findings

**No high-confidence exploitable security vulnerabilities were identified.**

### Areas Analyzed

| Area | Result |
|------|--------|
| **SQL injection (env.py, migrations)** | All SQL uses Alembic's `op.create_table()`/`op.drop_table()` with static literals. No dynamic query construction. |
| **Mako template injection** | `script.py.mako` renders only at developer-time CLI (`alembic revision`), not at runtime. Uses `${repr(...)}` for safe escaping. |
| **Startup error exposure** | Migration failures log to server-side only with `logger.critical(...)`. The exception is re-raised before the server accepts requests, so no error details reach HTTP clients. |
| **Path traversal** | `script_location` is hardcoded as `"backend/migrations"` — not influenced by user input. |
| **Durable data safety** | `CacheBase` and `DurableBase` are separate `DeclarativeBase` subclasses with independent `MetaData`. `CacheBase.metadata.drop_all` only drops cache tables. No cross-base foreign keys exist. |
| **Authorization** | No changes touch auth, sessions, CSRF, or API endpoints. |
| **Hardcoded secrets** | Migration defines schema only — no seed data, no default credential values. |

## Conclusion

This PR introduces well-structured Alembic migration infrastructure with no new attack surface. All database operations use parameterized Alembic/SQLAlchemy APIs rather than string interpolation, error handling follows server-side-only logging patterns, and the DurableBase/CacheBase partition correctly protects durable authentication data from cache rebuild operations.
