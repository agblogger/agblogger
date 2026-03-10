# Deployment

## Docker

Multi-stage build:

1. **Stage 1** (Node 22 Alpine): `npm ci && npm run build` to produce `frontend/dist/`.
2. **Stage 2** (Python 3.14 slim builder): Builds a dedicated `agblogger-server` wheel from the `backend/` package only.
3. **Stage 3** (Python 3.14 slim runtime): Installs Pandoc and gosu from GitHub releases, copies uv from astral-sh image, installs the server wheel, copies `frontend/dist`, and runs as non-root `agblogger` user on port 8000. No CLI tools are shipped in the runtime image. The pandoc server runs as a child process of the application, started during app startup and stopped on shutdown.

A `docker-entrypoint.sh` script handles bind-mount permissions: when the container starts as root (the default in compose), the entrypoint recursively fixes ownership of `/data/content` and `/data/db`, then drops privileges to the `agblogger` user via gosu before executing the CMD. This ensures the `content/` bind mount works out-of-the-box on Linux without manual permission setup, even when the host directory contains pre-existing files from a previous installation. The Dockerfile retains `USER agblogger` for direct `docker run` usage and security scanning compliance.

Volumes: `/data/content` (blog content) and `/data/db` (SQLite database). The containerized runtime uses an absolute SQLite URL rooted at `/data/db`, so the database file is created inside the mounted volume rather than under the application worktree.

Health check: `curl -f http://localhost:8000/api/health`.

`docker-compose.yml` is Caddy-first: AgBlogger is internal-only (`expose: 8000`), Caddy publishes `127.0.0.1:80:80` and `127.0.0.1:443:443`, and Caddy forwards to `agblogger:8000`. Caddy uses `depends_on` with `condition: service_healthy` so it doesn't accept traffic until AgBlogger passes its health check. A custom Docker network (`172.30.0.0/24`) assigns Caddy a static IP (`172.30.0.2`) so the backend can trust `X-Forwarded-For` headers for accurate per-client rate limiting. All compose files set `user: root` on the agblogger service so the entrypoint can fix bind-mount permissions before dropping to the non-root user.

All compose files pass the full set of application environment variables (auth hardening, `EXPOSE_DOCS`, `DEBUG`, etc.) to the container via the `environment:` section with safe defaults. Compose-level variables (`HOST_BIND_IP`, `HOST_PORT`, `AGBLOGGER_IMAGE`) are interpolated from `.env.production` via `--env-file`.

For local DAST, `docker-compose.caddy-local.yml` overrides the Caddy port mapping to `127.0.0.1:8080:80` and mounts `Caddyfile.local`, which serves both `localhost` and `host.docker.internal` over plain HTTP. The ZAP harness uses this local-only profile so scans exercise the packaged app behind Caddy without relying on production TLS or the Vite dev server.

For manual deployment-style testing on a workstation, the same local Caddy-backed profile can be managed with `just start-caddy-local`, `just health-caddy-local`, and `just stop-caddy-local`. These commands preserve the existing Vite-based `just start`/`just stop`/`just health` workflow and provide a separate packaged-app path on `localhost`.

For public Caddy deployment, the script generates `docker-compose.caddy-public.yml` that overrides Caddy ports to `80:80` and `443:443`.

For deployments without Caddy, the deploy script generates `docker-compose.nocaddy.yml` that publishes AgBlogger directly on `${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8000}:8000`.

For remote deployments that should not build on the target host, the deploy helper generates image-only compose files:

- `docker-compose.image.yml` for the Caddy-first topology (includes the custom network and Caddy static IP)
- `docker-compose.image.nocaddy.yml` for direct AgBlogger exposure

These files use `${AGBLOGGER_IMAGE}` instead of `build: .`, so the remote host only needs the image plus the generated deployment bundle.

## Deploy helper

Recommended deployment path is the interactive helper:

```bash
uv run agblogger-deploy
```

The deploy helper supports three deployment modes:

1. **Local**: Write production config in the repo, build via `docker compose build`, optionally scan the built image with Trivy, then start containers on the current machine.
2. **Registry**: build locally, optionally scan locally, push the image to a registry, and write a self-contained bundle under `dist/deploy/` for the remote server.
3. **Tarball**: build locally, optionally scan locally, export the image to a tarball, and write the same style of self-contained bundle under `dist/deploy/`.

In all modes the helper:

1. Collects configuration interactively (secret key, admin credentials, deployment mode, Caddy/HTTPS setup, trusted hosts, API docs exposure).
2. Validates all inputs (key length, password strength, trusted host format, domain format, port range).
3. Shows a configuration summary and asks for confirmation before proceeding (interactive mode only).
4. Backs up any existing generated config files (`.env.production.bak`, etc.) before overwriting.
5. Writes `.env.production` (chmod 600), `Caddyfile.production`, and compose files as needed.
6. Builds the Docker image via `docker compose build` and scans the exact built image with Trivy (if installed) before deployment, registry push, or tarball export. Progress messages are printed before each long-running operation.
7. For local deployments, starts containers and polls their health status until healthy or timeout (60 s).
8. Either starts local containers, pushes the image to a registry, or saves the image tarball depending on the selected mode.
9. Prints lifecycle commands for the selected mode.

### Caddy proxy auto-configuration

When Caddy is enabled, the deploy helper automatically configures `TRUSTED_PROXY_IPS` with the compose network subnet (`172.30.0.0/24`). This ensures the backend trusts `X-Forwarded-For` headers from Caddy for per-client rate limiting. The backend supports both exact IP matching and CIDR ranges in `TRUSTED_PROXY_IPS`. No manual proxy IP configuration is needed.

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

The `--secret-key` flag is optional; one is auto-generated if omitted. The `--admin-password` can alternatively be set via the `ADMIN_PASSWORD` environment variable to avoid exposing it in process listings.

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

The generated `DEPLOY-REMOTE.md` includes upgrade instructions (pull/load + restart) and, when Caddy is publicly exposed, firewall guidance (ports 80, 443, and SSH).

## Production HTTPS

When enabled in the deploy helper, Caddy is configured as a reverse proxy in front of AgBlogger with automatic Let's Encrypt TLS, HSTS (`Strict-Transport-Security: max-age=31536000`) on HTTPS responses, static asset caching with `Cache-Control: immutable`, gzip/zstd compression, and request-body caps for multipart upload endpoints (`55 MB` for post upload/assets, `100 MB` for sync commit). The local ZAP/DAST profile intentionally stays on plain HTTP and does not emit HSTS.

## Security scanning

When Trivy is installed, the deploy helper builds the Docker image via `docker compose build` and scans the exact built image (`agblogger:latest`) for vulnerabilities (MEDIUM/HIGH/CRITICAL severity) **before** starting containers. The scan uses `--exit-code 1` so deployment is aborted if vulnerabilities are found.
