# AgBlogger

A markdown-first blogging platform where markdown files with YAML front matter are the source of truth. A lightweight SQLite database serves as a cache for search/filtering and stores authentication data. Configuration lives in TOML files. A bidirectional sync engine keeps a local directory and the server in lockstep.

## Features

- **Markdown-first** — Pandoc rendering with KaTeX math, syntax highlighting, and custom filters (callouts, tabsets, video embeds)
- **Label DAG** — Hierarchical labels forming a directed acyclic graph with interactive visualization
- **Bidirectional sync** — SHA-256 hash-based sync with three-way merge and conflict resolution
- **Cross-posting** — Publish to Bluesky, Mastodon, X (Twitter), and Facebook
- **Full-text search** — SQLite FTS5 index over post content and metadata
- **Hardened authentication** — HttpOnly cookie sessions for web, invite-based registration, PATs for CLI/API

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Backend | Python 3.14+, FastAPI, SQLAlchemy 2.0, SQLite (WAL mode), Pandoc |
| Frontend | React 19, TypeScript, Vite, TailwindCSS 4, Zustand, React Flow |
| Infrastructure | Docker, Caddy, uv |

## Prerequisites

- Python 3.14+
- Node.js 20+
- [Pandoc](https://pandoc.org/installing.html)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [just](https://just.systems/) (command runner)
- Docker & Docker Compose (for containerized deployment)

## Quick Start

```bash
# Set up a fresh worktree (deps + .env + local db dir)
just setup

# Start both backend and frontend dev servers in the background
just start

# Or with custom ports (useful when running multiple worktrees)
just start backend_port=9000 frontend_port=9173
# If requested/default ports are busy, just start automatically picks free ports
# and prints the actual backend/frontend ports it chose.

# Stop the dev server
just stop

# Start the packaged app behind local Caddy on http://localhost:8080
just start-caddy-local

# Check or stop the local Caddy-backed packaged app profile
just health-caddy-local
just stop-caddy-local
```

`just setup` creates `.env` from `.env.example` only when `.env` is missing.

This starts the backend at http://localhost:8000 and the frontend at http://localhost:5173 (proxying API calls to the backend). API docs are at http://localhost:8000/docs.
`just start` now waits until both services are actually healthy before reporting success. If startup fails, inspect `.local/backend.log` and `.local/frontend.log`.
`just start-caddy-local` starts the packaged frontend/backend stack behind Caddy on `http://localhost:8080` by default. Override the port with `LOCAL_CADDY_PORT` or `just start-caddy-local local_caddy_port=9080`.

Default credentials: `admin` / `admin` (change via `.env`).
Self-registration is disabled by default; create invite codes from the admin account.

## Testing

```bash
# Run full quality gate (static checks, then tests)
just check

# Run extra checks not covered by just check (full npm audit + Checkov + Gitleaks + CodeQL + Semgrep + Snyk OSS + slow backend tests)
just check-extra

# Run Checkov against Dockerfile and docker-compose.yml
just checkov

# Run Gitleaks against the repo (excluding tests/)
just check-gitleaks

# Run full Gitleaks scan with default rules, bypassing repo test exclusions
just check-gitleaks-full

# Run Snyk code analysis
just check-snyk
# Test code is excluded via the repo-root .snyk policy

# Run noisy scans kept outside the default gate
just check-noisy

# Run static checks only (backend + frontend + Vulture + Trivy)
just check-static

# Run OWASP ZAP passive baseline scan against the local app
just zap-baseline

# Run OWASP ZAP full active scan against the local app
just zap-full
just zap-full 5

# Run tests only (backend + frontend)
just test
just test coverage=true

# Backend static checks only
just check-backend-static

# Backend tests only
just test-backend
just test-backend coverage=true

# Backend combined (static checks + tests)
just check-backend

# Frontend static checks only
just check-frontend-static

# Frontend tests only
just test-frontend
just test-frontend coverage=true

# Frontend combined (static checks + tests)
just check-frontend

# CodeQL analysis (requires existing databases)
just codeql

# Rebuild CodeQL databases and analyze
just check-codeql

# Create/rebuild CodeQL databases only
just setup-codeql
```

`just zap-baseline` and `just zap-full` use the official ZAP Docker image, auto-start a dedicated local Caddy-backed Docker Compose profile when needed, and write reports to `reports/zap/baseline/` or `reports/zap/full/`. That profile serves the built frontend through Caddy on `http://localhost:8080` by default, so ZAP scans the packaged app surface instead of the Vite dev server. Override the local scan port with `ZAP_CADDY_PORT` if needed. By default these commands do not pass a ZAP time limit. If you want one, use a positional minute override like `just zap-full 5`, or set `ZAP_BASELINE_MINUTES` / `ZAP_FULL_MINUTES` in the environment.

## Sync Client

The CLI sync client keeps a local content directory in sync with the server using SHA-256 hash-based three-way merge.

```bash
# Initialize a local directory for syncing
python cli/sync_client.py --dir ./my-blog --server https://your-server.com init

# Preview what would change
python cli/sync_client.py --dir ./my-blog status

# Full bidirectional sync
python cli/sync_client.py --dir ./my-blog sync
```

Authentication supports either username/password login or a personal access token (`--pat`). Conflicts are resolved by keeping the server version; the local copy is saved as a `.conflict-backup` file.

### Standalone Executable

Build a single-file executable that runs without a Python installation:

```bash
just build-cli
```

This produces `dist/cli/agblogger` (or `agblogger.exe` on Windows). The binary bundles the Python interpreter and all dependencies. Distribute it to users as-is:

```bash
./agblogger --dir ./my-blog --server https://your-server.com init
```

The build targets the current platform — cross-compile by running `just build-cli` on each target OS.

## Releases

Create a GitHub release with a semantic version bump, git tag, and tarballed source snapshot:

```bash
just release patch
```

Use `major`, `minor`, or `patch`. The release workflow requires a clean git worktree, updates the project version everywhere it is tracked, creates a `release: vX.Y.Z` commit, tags it, pushes the branch and tag, and creates a GitHub release with `dist/releases/agblogger-X.Y.Z.tar.gz` attached.

## Deployment

### 1. Run the interactive deploy script

```bash
just deploy
```

The script asks for all required production settings:

- `SECRET_KEY` (or auto-generate)
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- public hostnames/IPs for your blog (`TRUSTED_HOSTS`)
- `TRUSTED_PROXY_IPS` (optional)
- host port mapping (`HOST_PORT`, only used when Caddy is disabled)
- whether to set up HTTPS with Caddy (recommended)

Caddy is a web server and reverse proxy. It sits in front of AgBlogger, handles HTTPS certificates automatically, and forwards traffic to the app container.

If you enable Caddy, the script also generates:

- `Caddyfile.production`
- `docker-compose.caddy-public.yml` (only when you choose public Internet exposure)

If you disable Caddy, the script generates:

- `docker-compose.nocaddy.yml`

### 2. Manage the deployed server

After deployment, use the exact commands printed by the script.

```bash
docker compose --env-file .env.production up -d   # start (Caddy, localhost-only)
docker compose --env-file .env.production down    # stop (Caddy, localhost-only)
docker compose --env-file .env.production ps      # status (Caddy, localhost-only)
```

With Caddy and public Internet exposure enabled, commands include the generated public override:

```bash
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.caddy-public.yml up -d
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.caddy-public.yml down
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.caddy-public.yml ps
```

With Caddy disabled, commands use the generated no-Caddy compose file:

```bash
docker compose --env-file .env.production -f docker-compose.nocaddy.yml up -d
docker compose --env-file .env.production -f docker-compose.nocaddy.yml down
docker compose --env-file .env.production -f docker-compose.nocaddy.yml ps
```

### 3. Admin user creation

On first startup the server automatically creates an admin account using `ADMIN_USERNAME` and `ADMIN_PASSWORD` from the environment. The password is bcrypt-hashed before storage — the plaintext value is never persisted.

The admin user is only created if no user with that username already exists. To reset the admin password, delete the database volume and restart:

```bash
docker compose --env-file .env.production down -v   # removes the db volume
docker compose --env-file .env.production up -d     # recreates admin from .env.production
```

### 4. Log in

Visit `https://<your-domain>/login` when Caddy is enabled, or `http://<your-server>:<host-port>/login` when Caddy is disabled. Sign in with the admin credentials from `.env.production`.

Self-registration is disabled by default. To add more users, create invite codes from the admin account — other users can then register at `/login` with an invite code.

### 5. HTTPS behavior

If Caddy is enabled, users access the app at `https://<your-domain>/login`.
If Caddy is not enabled, users access the app directly via `http://<your-server>:<host-port>/login`.

### Data volumes

| Volume | Path in container | Purpose |
|--------|-------------------|---------|
| `./content` | `/data/content` | Blog content — markdown, TOML, assets (bind mount) |
| `agblogger-db` | `/data/db` | SQLite database (named volume) |

The `content/` directory is the source of truth. Back it up to preserve your blog. The database is fully regenerable from content files on startup (auth data like user accounts is the exception).

### Environment variables

Key deployment variables used by `.env.production`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | generated by script | JWT signing key |
| `ADMIN_USERNAME` | `admin` | Bootstrap admin username |
| `ADMIN_PASSWORD` | prompt input | Bootstrap admin password (hashed on storage) |
| `TRUSTED_HOSTS` | prompt input | Allowed Host headers in production |
| `TRUSTED_PROXY_IPS` | `[]` | Trusted proxy source IPs |
| `HOST_PORT` | `8000` | Host port mapped to container port 8000 in no-Caddy mode |
| `HOST_BIND_IP` | script-selected | Bind IP for no-Caddy mode |

Cross-posting credentials (Bluesky, Mastodon, X, Facebook) are configured through additional environment variables documented in `.env.example`.

### Backup

```bash
# Content (the source of truth)
rsync -av /data/content/ /backups/content/

# Database (cache + auth data)
cp /data/db/agblogger.db /backups/agblogger.db
```

## Project Structure

```
backend/          Python FastAPI application (API, services, models, sync engine)
frontend/         React + TypeScript SPA (Vite, TailwindCSS)
cli/              Sync and deployment CLIs
tests/            pytest test suite
content/          Sample blog content (markdown, TOML, assets)
docs/             Design documentation
```

## Content Authoring

Posts are markdown files with YAML front matter in the `content/posts/` directory:

```markdown
---
title: Hello World
created_at: 2026-02-02 22:21:29.975359+00
modified_at: 2026-02-02 22:21:35.000000+00
author: admin
labels: ["#swe"]
---

Post content here with **markdown**, $\LaTeX$ math, and `code blocks`.
```

Site configuration lives in `content/index.toml` and labels are defined in `content/labels.toml`.
