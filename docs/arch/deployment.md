# Deployment

## Docker

Multi-stage build:

1. **Stage 1** (Node 22 Alpine): `npm ci && npm run build` to produce `frontend/dist/`.
2. **Stage 2** (Python 3.14 slim builder): Builds a dedicated `agblogger-server` wheel from the `backend/` package only.
3. **Stage 3** (Python 3.14 slim runtime): Installs Pandoc from GitHub releases (pinned version with `+server` support), copies uv from astral-sh image, installs the server wheel, copies `frontend/dist`, and runs as non-root `agblogger` user on port 8000. No CLI tools are shipped in the runtime image. The pandoc server runs as a child process of the application, started during app startup and stopped on shutdown.

Volumes: `/data/content` (blog content) and `/data/db` (SQLite database).

Health check: `curl -f http://localhost:8000/api/health`.

`docker-compose.yml` is Caddy-first: AgBlogger is internal-only (`expose: 8000`), Caddy publishes `127.0.0.1:80:80` and `127.0.0.1:443:443`, and Caddy forwards to `agblogger:8000`.

For public Caddy deployment, the script generates `docker-compose.caddy-public.yml` that overrides Caddy ports to `80:80` and `443:443`.

For deployments without Caddy, the deploy script generates `docker-compose.nocaddy.yml` that publishes AgBlogger directly on `${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000`.

For remote deployments that should not build on the target host, the deploy helper generates image-only compose files:

- `docker-compose.image.yml` for the Caddy-first topology
- `docker-compose.image.nocaddy.yml` for direct AgBlogger exposure

These files use `${AGBLOGGER_IMAGE}` instead of `build: .`, so the remote host only needs the image plus the generated deployment bundle.

## Deploy helper

Recommended deployment path is the interactive helper:

```bash
uv run agblogger-deploy
```

The deploy helper supports three deployment modes:

1. **Local**: current behavior. Write production config in the repo, optionally scan the image with Trivy, then run `docker compose up -d --build` on the current machine.
2. **Registry**: build locally, optionally scan locally, push the image to a registry, and write a self-contained bundle under `dist/deploy/` for the remote server.
3. **Tarball**: build locally, optionally scan locally, export the image to a tarball, and write the same style of self-contained bundle under `dist/deploy/`.

In all modes the helper:

1. Collects configuration interactively (secret key, admin credentials, deployment mode, Caddy/HTTPS setup, trusted hosts, API docs exposure).
2. Validates all inputs (key length, password strength, trusted hosts without catch-all wildcards, domain format, port range).
3. Backs up any existing generated config files (`.env.production.bak`, etc.) before overwriting.
4. Writes `.env.production` (chmod 600), `Caddyfile.production`, and compose files as needed.
5. Builds the Docker image and scans it with Trivy (if installed) before local deploy, registry push, or tarball export.
6. Either starts local containers, pushes the image to a registry, or saves the image tarball depending on the selected mode.
7. Prints lifecycle commands for the selected mode.

### Non-interactive mode

For CI/CD or scripted deployments, pass all values as CLI arguments:

```bash
uv run agblogger-deploy --non-interactive \
  --admin-username admin \
  --admin-password "your-strong-password" \
  --deployment-mode registry \
  --image-ref ghcr.io/example/agblogger:1.2.3 \
  --caddy-domain blog.example.com \
  --caddy-email ops@example.com \
  --caddy-public \
  --trusted-hosts "blog.example.com" \
  --expose-docs
```

The `--secret-key` flag is optional; one is auto-generated if omitted.

For tarball mode, add `--deployment-mode tarball` and optionally `--tarball-filename agblogger-image.tar`.

### Dry run

Preview generated config files without writing or deploying:

```bash
uv run agblogger-deploy --dry-run
```

Secrets are masked in dry-run output. Combine with `--non-interactive` for fully automated previews.

### Re-run safety

Running the helper again backs up existing config files (`.env.production` → `.env.production.bak`, etc.) before overwriting, preventing accidental loss of manual edits. Remote bundle runs apply the same backup behavior inside the bundle directory for generated config files.

### Generated .env settings

The generated `.env.production` includes locked-down production defaults:

- `DEBUG=false`, `EXPOSE_DOCS` (configurable), `AUTH_ENFORCE_LOGIN_ORIGIN=true`
- Auth hardening: `AUTH_SELF_REGISTRATION=false`, `AUTH_INVITES_ENABLED=true`, `AUTH_LOGIN_MAX_FAILURES=5`, `AUTH_RATE_LIMIT_WINDOW_SECONDS=300`

If Bluesky cross-posting is enabled, set `BLUESKY_CLIENT_URL` to the public `https://` origin of the deployed app. Production startup rejects non-HTTPS values and URLs with paths, query strings, fragments, or userinfo.

### DNS prerequisite

When Caddy HTTPS is enabled, the helper reminds users that DNS A/AAAA records must point to the server before deployment. Caddy's automatic TLS provisioning requires Let's Encrypt to reach the server via the configured domain.

### Remote deployment bundles

Registry and tarball modes generate a self-contained bundle in `dist/deploy/` containing:

- `.env.production`
- `Caddyfile.production` when Caddy is enabled
- `docker-compose.image.yml` or `docker-compose.image.nocaddy.yml`
- `docker-compose.caddy-public.yml` when public Caddy exposure is enabled
- `DEPLOY-REMOTE.md` with the exact remote-server commands

Tarball mode also writes the exported image tarball into the bundle directory. The remote server then runs `docker load -i <tarball>` followed by `docker compose up -d` against the image-only compose file. Registry mode instead runs `docker compose pull` first and then `docker compose up -d`.

## Production HTTPS

When enabled in the deploy helper, Caddy is configured as a reverse proxy in front of AgBlogger with automatic Let's Encrypt TLS, static asset caching with `Cache-Control: immutable`, gzip/zstd compression, and request-body caps for multipart upload endpoints (`55 MB` for post upload/assets, `100 MB` for sync commit).

## Security scanning

When Trivy is installed, the deploy helper builds the Docker image and scans it for vulnerabilities (MEDIUM/HIGH/CRITICAL severity) **before** starting containers. The scan uses `--exit-code 1` so deployment is aborted if vulnerabilities are found.
