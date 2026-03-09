# Deployment Script Review (Fourth Pass)

Date: 2026-03-09

## Scope

Fourth review of `cli/deploy_production.py`, `Dockerfile`, `docker-compose.yml`, generated compose variants, and `Caddyfile.production` for correctness, user-friendliness, and out-of-the-box deployability.

## Prior Review Status

All 21 issues from the three prior reviews have been addressed. Key fixes confirmed in the current code:
- `$` escaping in env values (line 135: `replace("$", "\\$")`)
- Docker prerequisite check before interactive prompts (line 1269)
- `logs` lifecycle command (line 423)
- Caddy domain rejects IP addresses (lines 458-460)
- "Expose publicly" defaults to `False` (line 1065)
- `VERSION` file copied to Docker image (Dockerfile line 53)
- Entrypoint fixes bind-mount ownership via gosu (docker-entrypoint.sh)
- All env vars passed through to container (compose env section)
- Auto Caddy subnet for trusted proxy IPs (line 1083)

## New Issues Found

### 1. `_wait_for_healthy` vacuous truth — reports success when agblogger is absent

**File:** `cli/deploy_production.py:745`

```python
if lines and all("(healthy)" in line for line in lines if "agblogger" in line):
    print("All services healthy.")
    return
```

If `docker compose ps` returns output (e.g., Caddy is running) but no line contains "agblogger" (container was removed, renamed, or crashed hard enough to be reaped), `all(...)` iterates over zero items and returns `True`. The function reports "All services healthy" even though the application container is gone.

In practice this is unlikely since `docker compose ps` always lists defined services regardless of state, but it's a logic bug.

**Severity:** Low

### 2. No inline domain validation during interactive prompts

**File:** `cli/deploy_production.py:1046`

When the user enters a Caddy domain, no validation occurs until `_validate_config()` runs inside `deploy()` — after the user has answered all remaining questions (trusted hosts, proxy IPs, expose docs) and confirmed the summary. An invalid domain (e.g., `foo`, `127.0.0.1`) causes a late error after significant user effort.

Compare with `_prompt_secret_key()` and `_prompt_password()`, which validate inline. Domain and trusted host prompts should do the same.

**Severity:** Medium

### 3. Static `Caddyfile` and `Caddyfile.production` use different HTML matching than generated output

**Files:** `Caddyfile:42`, `Caddyfile.production:29` vs `cli/deploy_production.py:203-206`

The static template files use `header /*.html` while the deploy-script-generated Caddyfile uses `@html path_regexp \.html$`. The static files only match root-level `.html` files; the generated one matches any depth. The static `Caddyfile.production` is overwritten by the deploy script, and the static `Caddyfile` is a manual reference template. Neither causes a deployment bug, but the inconsistency could confuse someone reading the templates directly.

**Severity:** Low

### 4. No timeout on Docker build/push/save operations

**File:** `cli/deploy_production.py:141-143`

`_run_command` calls `subprocess.run` without a `timeout` parameter. If a Docker build hangs (common with network issues during package install), the deploy script blocks indefinitely. The health poll has a 60s timeout, but the build/push/save steps don't.

**Severity:** Low

### 5. `HOST_PORT` and `HOST_BIND_IP` written to `.env.production` in Caddy mode but unused

**File:** `cli/deploy_production.py:163-164`

When Caddy is enabled, the base `docker-compose.yml` uses `expose: 8000` (internal only). `HOST_PORT` and `HOST_BIND_IP` are only referenced by no-Caddy compose files. Writing them to `.env.production` is harmless but confusing for users reading the file.

**Severity:** Low

### 6. DEPLOY-REMOTE.md mixes step descriptions with raw commands

**File:** `cli/deploy_production.py:576-609`

Registry mode generates steps where step 1 is a description but steps 2-4 are raw commands without a "Run:" prefix, making them look like descriptions rather than executable commands.

**Severity:** Low

### 7. No `BLUESKY_CLIENT_URL` in generated `.env.production` or compose env section

**File:** `cli/deploy_production.py:156-177`

The deploy script doesn't prompt for or write `BLUESKY_CLIENT_URL`. The backend validates this at startup — if set via other means but not HTTPS, the server crashes. Since cross-posting is opt-in and the default empty string passes validation, this is low risk, but a commented-out line in `.env.production` would serve as documentation.

**Severity:** Low

## Overall Assessment

The deployment script is production-ready. All critical and medium-severity issues from three prior reviews have been fixed. The remaining issues are low severity — cosmetic, edge-case, or minor UX improvements. A fresh deployment will work out-of-the-box across all three modes (local, registry, tarball).

## Summary

| # | Issue | Severity |
|---|-------|----------|
| 1 | `_wait_for_healthy` vacuous truth when agblogger line absent | Low |
| 2 | No inline domain validation in interactive prompts | Medium |
| 3 | Static Caddyfile templates inconsistent with generated output | Low |
| 4 | No timeout on Docker build/push/save operations | Low |
| 5 | HOST_PORT/HOST_BIND_IP written in Caddy mode but unused | Low |
| 6 | DEPLOY-REMOTE.md mixes descriptions with raw commands | Low |
| 7 | No BLUESKY_CLIENT_URL prompt or documentation in env file | Low |
