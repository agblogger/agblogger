# PR Review: Reliability Hardening (2026-03-05)

Commits reviewed: 27e488a..423296a (origin/main)

## Critical Issues (2)

1. **Write lock initialization race condition** — `backend/api/deps.py:76-82`
   `get_content_write_lock` lazily creates an `asyncio.Lock()` on first access via `getattr`/`setattr`. If two requests arrive concurrently before the lock is set, both could create separate lock instances, completely defeating serialization. **Fix**: Initialize `app.state.content_write_lock = asyncio.Lock()` in the lifespan handler in `main.py`.

2. **Pandoc degraded mode is invisible to users/admins** — `backend/main.py:237-245`
   When pandoc fails to start, the server continues but every rendering operation will fail with RuntimeError (returned as 502). `startup_errors` is populated but never exposed through any API. **Resolution**: Pandoc is a core dependency -- the server should not start without it. Remove degraded mode entirely and let pandoc startup failure be fatal.

## Important Issues (6)

3. **`_parse_json_object` duplicated across 4 crosspost modules** — `backend/crosspost/{facebook,mastodon,x,atproto_oauth}.py`
   Nearly identical function copy-pasted 4 times. CLAUDE.md says "Avoid code duplication." **Fix**: Extract into `backend/crosspost/http_utils.py`.

4. **Symlink failure silently breaks old URLs** — `backend/api/posts.py` (update endpoint)
   Changed from rollback-and-500 to warn-via-header. The `X-Path-Compatibility-Warning` header is invisible in the UI. **Fix**: Include warning in JSON response body.

5. **Misleading log messages in `except ValueError` blocks** — `backend/crosspost/mastodon.py:218`, `backend/crosspost/x.py:240`
   Logs say "auth HTTP error" for JSON parsing errors. **Fix**: Use accurate messages.

6. **Duplicate `except` blocks in mastodon/x** — `backend/crosspost/mastodon.py:212-220`, `backend/crosspost/x.py`
   Separate `except httpx.HTTPError` and `except ValueError` with identical bodies. **Fix**: Combine into `except (httpx.HTTPError, ValueError)`.

7. **Missing security telemetry for race detection** — `backend/services/auth_service.py:148-149, 247-260`
   Refresh token and invite code concurrent-consume races return silently. **Fix**: Add `logger.warning`.

8. **No tests for deps.py 503 responses** when services are missing from app state. Also no test for `sync_status` when `git_service.head_commit()` fails.

## Suggestions (6)

9. Write lock tests only cover 2 of 10+ endpoints.
10. No test for non-dict JSON responses in crosspost `_parse_json_object`.
11. `deps.py` module docstring is stale.
12. Sync docs slightly inaccurate for `sync_status` behavior.
13. Comment at `posts.py:689` lost design rationale about symlink behavior change.
14. Broad `except Exception` in `backend/api/sync.py:388-391` for config reload.

## Strengths

- Atomic race prevention with `DELETE ... WHERE token_hash` and `UPDATE ... WHERE used_at IS NULL`
- Safe JSON parsing across all 4 crosspost platforms
- Graceful dependency injection with 503 responses during partial startup
- Good test coverage with concurrency tests and regression tests
- Architecture docs updated
