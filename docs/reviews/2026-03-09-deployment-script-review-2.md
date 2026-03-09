# Deployment Script Review (Follow-up)

Date: 2026-03-09

## Scope

Review of `cli/deploy_production.py`, `Dockerfile`, `docker-compose.yml`, generated compose variants, and `Caddyfile.production` for correctness, user-friendliness, and out-of-the-box deployability. This is a follow-up to the initial review (`2026-03-09-deployment-script-review.md`); all issues from that review were addressed in commit `da3a05e`.

## Overall Assessment

The script is production-quality and well-hardened. The current state is solid — a fresh deployment should work out-of-the-box across all three modes (local, registry, tarball). Below are remaining observations, grouped by severity.

## High: `content/` Bind Mount Owned by Root on Linux

**Files:** All compose files, `Dockerfile:48`

The compose files mount `./content:/data/content`. On a fresh remote Linux server, `./content/` won't exist. Docker will auto-create it as a directory owned by `root:root`, and the container's non-root `agblogger` user may not have write access.

The Dockerfile does `mkdir -p /data/content /data/db && chown -R agblogger:agblogger /data`, but this only affects the image layer. When `./content` is bind-mounted from the host, the host's ownership takes precedence.

The `agblogger-db` volume is fine because it's a Docker named volume, which gets the correct ownership from the image.

**Fix options:**

1. Create `content/` in the bundle directory with appropriate permissions
2. Add a note to `DEPLOY-REMOTE.md` that `mkdir -p content && chown 1000:1000 content` is needed
3. Use an entrypoint script that handles ownership (common Docker pattern)

## Medium: Implicit Compose File Selection May Pick Up Override Files

**File:** `cli/deploy_production.py:361-365`

When `use_caddy=True, caddy_public=False`, `_compose_filenames()` returns `[]`, which means `docker compose` picks up the default `docker-compose.yml` implicitly. Docker compose automatically merges `docker-compose.override.yml` when no `-f` flags are given, which could cause unexpected behavior if the user has override files in the directory.

**Fix:** Explicitly pass `-f docker-compose.yml` even in the non-public Caddy case.

## Medium: Caddy Starts Before AgBlogger Is Healthy

**File:** `docker-compose.yml:43-44`

The Caddy service has `depends_on: agblogger` but doesn't use `condition: service_healthy`. If the agblogger container takes a while to start (e.g., long `rebuild_cache()`), Caddy will start immediately and return 502 to incoming requests.

**Fix:** Use `depends_on: agblogger: condition: service_healthy` so Caddy doesn't accept traffic until AgBlogger is healthy.

## Low: `asyncio.run()` Wrapping of Sync Subprocess Calls

**File:** `cli/deploy_production.py:135-142`

`_run_docker` and `_run_trivy` each call `asyncio.run(_run_command(...))`, creating and tearing down an event loop per invocation. This works today because the script is fully synchronous, but `asyncio.run()` cannot be nested — if the deploy helper is ever called from an async context, it will raise `RuntimeError`. These could simply call `subprocess.run` directly.

## Low: Opaque Error Messages on Command Failure

**File:** `cli/deploy_production.py:1194-1196`

When a subprocess fails, the error message is:

```
Deployment failed: command returned exit code 1
```

For a multi-step pipeline (build, scan, push, up), knowing which step failed matters. The actual command output goes to the console live, but the summary line gives no indication of which command failed.

**Suggestion:** Include the command in the error: `f"Command failed (exit code {exc.returncode}): {' '.join(exc.cmd)}"`.

## Low: Caddy Header Matcher Depth for Nested Assets

**File:** `cli/deploy_production.py:188-198` (generated Caddyfile)

The `/*.html` pattern only matches HTML files at the root level. This likely works for the SPA (Vite produces `index.html` at the root). The `header /assets/*` pattern should also be fine since Caddy's `path` matching does match subdirectories, but worth verifying against the deployed asset structure.

## Low: JSON-Quoted `.env` Values Break Shell `source`

**File:** `cli/deploy_production.py:117-119`

`_quote_env_value()` uses `json.dumps()`, producing double-quoted values. Docker compose V2 handles this correctly, but if someone sources `.env.production` in a shell script (common practice), the JSON-escaped quotes will cause issues.

## Positive Notes

- All previous review issues fixed (env var pass-through, rate limiting behind Caddy, double build, step numbering, trusted host validation, content directory note, password env var fallback)
- Three deployment modes with clean separation and appropriate file generation/cleanup
- Interactive flow is well-designed: sensible defaults, password confirmation, DNS reminder, auto-appending Caddy domain to trusted hosts
- Non-interactive mode covers CI/CD well with proper required-argument validation
- Test coverage is thorough (1143 lines of tests for 1224 lines of code)
- Dry-run with secret masking is excellent for auditability
- Backup safety prevents accidental config loss
- chmod 600 on `.env` with graceful fallback is good security hygiene
- Stale file cleanup prevents configuration ghosts from previous runs

## Summary

| # | Issue | Severity |
|---|-------|----------|
| 1 | `content/` bind mount owned by root on Linux — container can't write | High |
| 2 | Implicit compose file selection may pick up override files | Medium |
| 3 | Caddy starts before AgBlogger is healthy — temporary 502s | Medium |
| 4 | `asyncio.run()` wrapping of sync subprocess calls | Low |
| 5 | Opaque error messages on command failure | Low |
| 6 | Caddy header matcher depth for nested assets | Low |
| 7 | JSON-quoted `.env` values break shell `source` | Low |
