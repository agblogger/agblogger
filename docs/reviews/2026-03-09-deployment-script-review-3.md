# Deployment Script Review (Third Pass)

Date: 2026-03-09

## Scope

Third review of `cli/deploy_production.py`, `Dockerfile`, `docker-compose.yml`, generated compose variants, and `Caddyfile.production` for correctness, user-friendliness, and out-of-the-box deployability.

## Previous Review Status

### First review (2026-03-09-deployment-script-review.md) — all 8 issues fixed

### Second review (2026-03-09-deployment-script-review-2.md) — all 7 issues addressed

1. **`content/` bind mount owned by root** — Already handled: `docker-entrypoint.sh` runs as root (compose sets `user: root`), does `mkdir -p` and `chown agblogger:agblogger /data/content /data/db`, then drops to non-root via gosu. Since it's a bind mount, the chown affects the host directory.
2. **Implicit compose file selection picks up overrides** — Fixed: `_compose_filenames()` now returns `["docker-compose.yml"]` explicitly for local Caddy mode.
3. **Caddy starts before AgBlogger is healthy** — Fixed: `docker-compose.yml` uses `depends_on: agblogger: condition: service_healthy`.
4. **`asyncio.run()` wrapping of sync subprocess calls** — Fixed: `_run_command` now calls `subprocess.run` directly.
5. **Opaque error messages** — Fixed: `CalledProcessError` handler now includes the failed command string.
6. **Caddy header matcher depth** — Fixed: generated Caddyfile uses `@html path_regexp \.html$` (regex, matches any depth).
7. **JSON-quoted `.env` values break shell `source`** — Still present; superseded by the more severe `$` escaping bug below.

## New Issues Found

### 1. Bug: `$` in secrets silently corrupted by Docker Compose env file parsing

**File:** `cli/deploy_production.py:116-118`

`_quote_env_value()` uses `json.dumps()`, which produces double-quoted values like `"my$ecret"`. Docker Compose's env file parser (godotenv) interprets `$` inside double-quoted values as variable references, silently replacing `$ecret` with an empty string. The password `my$ecret` becomes `my`.

This affects `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `AGBLOGGER_IMAGE` — all values written via `_quote_env_value`.

Auto-generated secret keys (via `secrets.token_urlsafe`) use the alphabet `A-Za-z0-9_-`, so they are safe. But user-supplied passwords and manually provided secret keys are vulnerable.

**Fix:** Escape `$` as `\$` within double-quoted values:

```python
def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{escaped}"'
```

### 2. UX: Prerequisites checked after interactive config collection

**File:** `cli/deploy_production.py:1176-1188`

In `main()`, `check_prerequisites(project_dir)` runs after `collect_config()`. If Docker isn't installed, the user answers all interactive questions before finding out. A basic `shutil.which("docker")` check should run before config collection.

### 3. Missing: `logs` lifecycle command

**File:** `cli/deploy_production.py:389-407`

The printed lifecycle commands include start/stop/status but not `logs`. For troubleshooting a new deployment, `docker compose ... logs -f` is essential — especially for first-time self-hosters.

### 4. Caddy domain validation accepts IP addresses

**File:** `cli/deploy_production.py:436`

The validation `"." not in domain` rejects `localhost` but accepts `127.0.0.1` and other IPs (which contain dots). Let's Encrypt cannot issue certificates for IP addresses, so Caddy TLS would fail at startup. At minimum, reject values that look like IPv4 addresses.

### 5. Interactive "expose publicly" defaults to `True` without Caddy

**File:** `cli/deploy_production.py:973-979`

When the user declines Caddy, "Expose AgBlogger directly on the Internet?" defaults to `True`, binding to `0.0.0.0` without TLS. Security-by-default would suggest defaulting to `False` (localhost only), since exposing without encryption is the more dangerous choice.

### 6. No `VERSION` file in Docker image

**File:** `Dockerfile` (no `COPY VERSION` instruction)

`backend/version.py:get_version()` first looks for a `VERSION` file at the project root (`Path(__file__).resolve().parents[1] / "VERSION"`), then falls back to `importlib.metadata`. In the Docker image, `VERSION` is absent so the fallback is always exercised. This works (the `agblogger-server` wheel contains version metadata), but copying `VERSION` to the image would be cleaner.

## Minor Observations

- **`HOST_PORT` written to `.env.production` but unused in Caddy topology** — When Caddy is enabled, the base `docker-compose.yml` uses `expose: 8000` (internal only). `HOST_PORT` is only referenced by no-caddy compose files. Not a bug, but confusing for users reading the env file.
- **No `--version` flag** on the deploy CLI.
- **`_prompt_host_port` accepts privileged ports (<1024)** without warning that these require root on Linux.

## Positive Notes

All 15 issues from the two prior reviews have been addressed. The script is well-structured with clean separation between content builders, validation, file management, and orchestration. The three deployment modes (local/registry/tarball) with appropriate compose file generation/cleanup cover common self-hosted scenarios well. Test coverage is thorough (30+ tests). Dry-run with secret masking, backup safety, stale file cleanup, auto-Caddy proxy subnet, and DNS reminders are all excellent UX touches.

The most impactful fix would be issue #1 (the `$` escaping bug), as it silently corrupts credentials containing a common shell metacharacter.

## Summary

| # | Issue | Severity |
|---|-------|----------|
| 1 | `$` in secrets silently corrupted by Docker Compose env parsing | High |
| 2 | Prerequisites checked after interactive config collection | Medium |
| 3 | Missing `logs` lifecycle command | Low |
| 4 | Caddy domain validation accepts IP addresses | Low |
| 5 | Interactive "expose publicly" defaults to True without Caddy | Low |
| 6 | No `VERSION` file in Docker image | Low |
