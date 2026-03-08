# Deployment

## Docker

Multi-stage build:

1. **Stage 1** (Node 22 Alpine): `npm ci && npm run build` to produce `frontend/dist/`.
2. **Stage 2** (Python 3.13 slim): Installs Pandoc from GitHub releases (pinned version with `+server` support), copies uv from astral-sh image, installs Python dependencies, copies backend + CLI + frontend dist, runs as non-root `agblogger` user on port 8000. The pandoc server runs as a child process of the application, started during app startup and stopped on shutdown.

Volumes: `/data/content` (blog content) and `/data/db` (SQLite database).

Health check: `curl -f http://localhost:8000/api/health`.

`docker-compose.yml` is Caddy-first: AgBlogger is internal-only (`expose: 8000`), Caddy publishes `127.0.0.1:80:80` and `127.0.0.1:443:443`, and Caddy forwards to `agblogger:8000`.

For public Caddy deployment, the script generates `docker-compose.caddy-public.yml` that overrides Caddy ports to `80:80` and `443:443`.

For deployments without Caddy, the deploy script generates `docker-compose.nocaddy.yml` that publishes AgBlogger directly on `${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000`.

## Deploy helper

Recommended deployment path is the interactive helper:

```bash
uv run agblogger-deploy
```

The deploy helper:

1. Collects configuration interactively (secret key, admin credentials, Caddy/HTTPS setup, trusted hosts, API docs exposure).
2. Validates all inputs (key length, password strength, domain format, port range).
3. Backs up any existing generated config files (`.env.production.bak`, etc.) before overwriting.
4. Writes `.env.production` (chmod 600), `Caddyfile.production`, and compose overrides as needed.
5. Builds the Docker image and scans it with Trivy (if installed) **before** starting containers.
6. Starts containers via `docker compose up -d`.
7. Prints lifecycle commands (start/stop/status) for ongoing management.

### Non-interactive mode

For CI/CD or scripted deployments, pass all values as CLI arguments:

```bash
uv run agblogger-deploy --non-interactive \
  --admin-username admin \
  --admin-password "your-strong-password" \
  --caddy-domain blog.example.com \
  --caddy-email ops@example.com \
  --caddy-public \
  --trusted-hosts "blog.example.com" \
  --expose-docs
```

The `--secret-key` flag is optional; one is auto-generated if omitted.

### Dry run

Preview generated config files without writing or deploying:

```bash
uv run agblogger-deploy --dry-run
```

Secrets are masked in dry-run output. Combine with `--non-interactive` for fully automated previews.

### Re-run safety

Running the helper again backs up existing config files (`.env.production` → `.env.production.bak`, etc.) before overwriting, preventing accidental loss of manual edits.

### Generated .env settings

The generated `.env.production` includes locked-down production defaults:

- `DEBUG=false`, `EXPOSE_DOCS` (configurable), `AUTH_ENFORCE_LOGIN_ORIGIN=true`
- Auth hardening: `AUTH_SELF_REGISTRATION=false`, `AUTH_INVITES_ENABLED=true`, `AUTH_LOGIN_MAX_FAILURES=5`, `AUTH_RATE_LIMIT_WINDOW_SECONDS=300`

### DNS prerequisite

When Caddy HTTPS is enabled, the helper reminds users that DNS A/AAAA records must point to the server before deployment. Caddy's automatic TLS provisioning requires Let's Encrypt to reach the server via the configured domain.

## Production HTTPS

When enabled in the deploy helper, Caddy is configured as a reverse proxy in front of AgBlogger with automatic Let's Encrypt TLS, static asset caching with `Cache-Control: immutable`, gzip/zstd compression, and request-body caps for multipart upload endpoints (`55 MB` for post upload/assets, `100 MB` for sync commit).

## Security scanning

When Trivy is installed, the deploy helper builds the Docker image and scans it for vulnerabilities (MEDIUM/HIGH/CRITICAL severity) **before** starting containers. The scan uses `--exit-code 1` so deployment is aborted if vulnerabilities are found.
