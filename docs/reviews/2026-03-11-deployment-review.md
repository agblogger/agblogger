# Deployment Script Review — 2026-03-11

Review of `cli/deploy_production.py` for user-friendliness and out-of-the-box experience.

## 1. Easy deployment with minimal configuration

**Good:**
- Interactive wizard has sensible defaults (auto-generated SECRET_KEY, admin username defaults to "admin", deployment mode defaults to local, Caddy defaults to yes)
- Three clear deployment modes (local/registry/tarball)
- Caddy prompt has a helpful explanation of what Caddy does
- Non-interactive mode with CLI flags for automation
- Dry-run mode for previewing generated config

**Issues:**
- Trusted hosts prompt is confusing for beginners. When the user already provided a Caddy domain (e.g. `blog.example.com`), they're still asked "Hostnames/IPs clients will use to reach your blog". Most users only need their domain — which is already auto-included. The prompt should default to just the Caddy domain and let users add extras, rather than requiring them to understand Host header validation.
- Trusted proxy IPs prompt shown to everyone. For typical single-server deployments this is irrelevant. When Caddy is enabled the subnet is auto-configured, but the "Additional trusted proxy IPs" prompt still appears.

## 2. Works when deploying from local machine to remote server

**Good:**
- Registry and tarball modes build locally and produce a self-contained bundle (`dist/deploy/`) with all config files, compose files, and a DEPLOY-REMOTE.md
- The tarball mode is genuinely zero-registry — just copy the directory and run

**Issues:**
- DEPLOY-REMOTE.md doesn't list remote server prerequisites. Docker and Docker Compose are required on the remote server but aren't mentioned. A user who copies the bundle to a fresh VPS won't know what to install first.
- No transfer assistance. The script creates the bundle but the user must figure out how to copy it. An `scp` or `rsync` example in the output or DEPLOY-REMOTE.md would help.

## 3. Deploy to remote without additional configuration

**Good:**
- Tarball mode is truly self-contained: the bundle has .env, compose files, Caddyfile, image tarball, and instructions
- Registry mode requires registry auth on the remote server (additional config), but this is inherent to the approach

No major issues here — tarball mode meets this requirement well.

## 4. Upgrade without data loss

**Critical issue — misleading documentation:**

`DEPLOY-REMOTE.md` says: "The database is a regenerable cache — only `./content/` needs to be preserved."

This is **wrong**. The database has **durable tables** (users, tokens, invites, social accounts, cross-posts) managed by Alembic migrations. Only the cache tables are regenerable. Telling users the database is expendable could lead to actual data loss if they delete the `agblogger-db` volume.

The compose files use a named volume (`agblogger-db:`) which persists across container recreations, and Alembic migrations run on startup — so the mechanism for safe upgrades exists. But the documentation actively undermines it.

**Tarball upgrade instructions are incomplete:** The upgrade section says to load the new tarball and run `start`, but doesn't mention updating `AGBLOGGER_IMAGE` in `.env.production` if the image tag changes between versions.

## 5. Handles upgrading existing installations gracefully

This is the weakest area. Several problems:

**a) Re-running the script regenerates secrets (data loss risk):**

The interactive wizard always generates a new SECRET_KEY. There's no detection of an existing `.env.production`. Re-running the script to "upgrade" would:
- Generate a new SECRET_KEY, invalidating all existing sessions and API tokens
- Prompt for a new admin password, could overwrite the existing admin's credentials

The script should detect an existing `.env.production` and offer to reuse existing secrets, or have an `--upgrade` mode.

**b) No upgrade lifecycle command:**

The lifecycle commands printed at the end are: start, stop, status, logs. For local mode, the actual upgrade path is `docker compose up -d --build` (or pull+start for remote), but this isn't shown. Users don't know how to upgrade without re-running the full wizard.

**c) No rollback guidance:**

Config files are backed up to `.bak`, which is good. But there's no guidance on how to roll back if a new version breaks. The output could mention the backup files and how to restore them.

**d) Local-mode upgrade has no documented path:**

After initial deployment, there's no documented way to upgrade the local installation. The user would need to figure out that `docker compose --env-file .env.production -f docker-compose.yml up -d --build` is the right command.

## Fixes (by priority)

| Priority | Issue | Fix |
|----------|-------|-----|
| **High** | "Database is a regenerable cache" in DEPLOY-REMOTE.md | Fix to: "The database volume contains user accounts and settings. Both `./content/` and the database volume must be preserved." |
| **High** | Re-running script overwrites secrets | Detect existing `.env.production`, offer to reuse existing SECRET_KEY and admin credentials |
| **High** | No upgrade lifecycle command | Add an "Upgrade" command to the lifecycle output |
| **Medium** | Tarball upgrade instructions missing image tag update | Add step: "Update AGBLOGGER_IMAGE in .env.production if the tag changed" |
| **Medium** | DEPLOY-REMOTE.md missing prerequisites | Add: "Prerequisites: Docker and Docker Compose must be installed on the remote server" |
| **Low** | Trusted hosts prompt confusing with Caddy | Default to just the Caddy domain; only ask for extras |
| **Low** | No transfer command in output | Print scp example |
| **Low** | No rollback guidance | Mention .bak files and how to restore if upgrade fails |
