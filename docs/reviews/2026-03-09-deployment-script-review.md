# Deployment Script Review

Date: 2026-03-09

## Scope

Review of `cli/deploy_production.py`, `Dockerfile`, `docker-compose.yml`, generated compose variants, and `Caddyfile.production` for correctness, user-friendliness, and out-of-the-box deployability.

## Overall Assessment

The deploy script is well-structured, has good test coverage, and handles many edge cases (backup/restore, dry-run, secret masking, validation, multiple deployment modes). The interactive flow is thoughtful with sensible defaults. However, there are several issues that would prevent a fully working out-of-the-box deployment.

## Critical: Environment Variables Don't Reach the Container

**Files:** All compose files (`docker-compose.yml`, generated nocaddy/image variants)

`docker compose --env-file .env.production` loads variables for **compose-level `${}` interpolation only** -- it does NOT inject them into the container. The `environment:` sections in every compose file explicitly list only 7 variables:

```
SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD, TRUSTED_HOSTS,
TRUSTED_PROXY_IPS, CONTENT_DIR, DATABASE_URL
```

But `.env.production` also generates these, which **never reach the container**:

| Variable | Impact |
|----------|--------|
| `EXPOSE_DOCS` | **Broken** -- user chooses "yes", docs remain hidden |
| `AUTH_ENFORCE_LOGIN_ORIGIN` | Works by coincidence (Settings default = `True`) |
| `AUTH_SELF_REGISTRATION` | Works by coincidence (Settings default = `False`) |
| `AUTH_INVITES_ENABLED` | Works by coincidence (Settings default = `True`) |
| `AUTH_LOGIN_MAX_FAILURES` | Works by coincidence (Settings default = `5`) |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Works by coincidence (Settings default = `300`) |
| `DEBUG` | Works by coincidence (Settings default = `False`) |
| `HOST`, `PORT` | Dead variables -- Dockerfile already sets them, compose doesn't reference them |

**Fix:** Either add an `env_file:` directive to the compose services, or explicitly list all app env vars in the `environment:` section. The `env_file:` approach is cleaner:

```yaml
services:
  agblogger:
    env_file: .env.production
    environment:
      - CONTENT_DIR=/data/content
      - DATABASE_URL=sqlite+aiosqlite:////data/db/agblogger.db
```

## Critical: Rate Limiting Broken Behind Caddy

**Files:** `cli/deploy_production.py:941`, `backend/api/auth.py:92-100`

In `_get_client_ip`, `X-Forwarded-For` is only trusted when `client_host in settings.trusted_proxy_ips`. With the default `TRUSTED_PROXY_IPS=[]`, all requests through Caddy appear to come from Caddy's Docker-internal IP. This means:

- After 5 failed logins from **any** user, **all** users are rate-limited
- The rate limiter is effectively a global lockout, not per-user

The deploy script's interactive prompt ("Trusted proxy IPs (comma-separated, optional):") gives no guidance that Caddy's Docker IP should be included. Since Docker IPs are dynamic, a CIDR range or `depends_on` network alias would be needed.

**Fix:** When Caddy is enabled, auto-populate `TRUSTED_PROXY_IPS` with the Caddy service name's Docker network range, or at minimum warn the user and suggest a value.

## Bug: Double Image Build in Local + Trivy Mode

**File:** `cli/deploy_production.py:673-679`

```python
if trivy_available:
    build_and_scan(project_dir, SCAN_IMAGE_TAG)   # builds agblogger-deploy-scan:latest
_run_compose_up(config, project_dir)               # builds AGAIN via --build
```

The scanned image (`agblogger-deploy-scan:latest`) is never the image that runs. Compose builds a second image from scratch. This is wasteful and technically the deployed image was never scanned.

**Fix:** Tag the scanned image appropriately and reference it in compose, or use `docker compose build` + scan + `docker compose up -d` (without `--build`).

## Bug: DEPLOY-REMOTE.md Step Numbering

**File:** `cli/deploy_production.py:512-544`

For tarball mode, the generated README has:

```
1. docker load -i agblogger-image.tar
2. docker compose ... up -d
4. docker compose ... ps        <-- step 3 is missing
```

The unconditional `f"4. {commands['status']}"` should be `3` for tarball mode and `4` for registry mode.

## Issue: Trusted Hosts Not Format-Validated at Deploy Time

**File:** `cli/deploy_production.py:389-390`

`_validate_config` only checks `if not config.trusted_hosts:` -- it doesn't validate individual host formats. A user could enter `*` (catch-all wildcard), which the deploy script would accept, write to `.env.production`, and then the server would crash at startup with `validate_runtime_security()`. Early validation in the deploy script would give a much better UX.

## UX: No Guidance on Content Directory for Remote Bundles

The generated `DEPLOY-REMOTE.md` doesn't mention that a `content/` directory will be created by Docker's bind mount. For users who want to bring existing content, or who expect to understand where their data lives, this is a gap. A single note like "Blog content will be stored in `./content/`" would help.

## UX: Admin Password Visible in Process List

The `--admin-password` CLI flag exposes the password in `ps` output and shell history. Consider accepting it via stdin or an env var in non-interactive mode, and add a warning to the help text.

## Minor: Dead Variables in .env.production

`HOST=0.0.0.0` and `PORT=8000` are written to `.env.production` but:

1. No compose file references `${HOST}` or `${PORT}`
2. The Dockerfile already sets these as `ENV` directives
3. Even if they were in the compose environment section, they'd be redundant

They create confusion for anyone reading the env file. Remove them or add comments explaining they're for documentation only.

## Positive Notes

- **Backup safety** -- automatic `.bak` creation before overwriting is excellent
- **Dry-run with secret masking** -- well done for auditability
- **Stale file cleanup** -- removing compose files from previous configurations prevents confusion
- **Validation** -- secret key length, password length, port range, domain format checks are solid
- **DNS reminder** -- prompting about DNS A/AAAA records for Caddy TLS is a nice touch
- **Three deployment modes** -- local/registry/tarball covers the common self-hosted scenarios well
- **Test coverage** -- the test suite is thorough with 30+ tests covering each workflow path
- **chmod 600 on .env** -- good security hygiene with graceful fallback
