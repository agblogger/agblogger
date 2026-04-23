# Deployment Guide

AgBlogger ships a single Docker image that serves both the API and the built frontend, plus a GoatCounter analytics sidecar. The deployment wizard generates all necessary configuration files and orchestrates the deployment.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose V2 (`docker compose` subcommand)
- Optional: [Trivy](https://trivy.dev) for automatic image vulnerability scanning before deployment

## Quick Start

Run the deployment wizard from the project root:

```bash
just deploy
```

The wizard walks through all configuration choices interactively, shows a summary, and asks for confirmation before deploying. Every prompt has a default value shown in brackets.

### Non-Interactive Mode

All configuration can be passed via CLI flags for automation:

```bash
uv run agblogger-deploy --non-interactive \
  --admin-username admin \
  --admin-password 'your-password' \
  --trusted-hosts blog.example.com \
  --caddy-domain blog.example.com \
  --caddy-email you@example.com \
  --caddy-public
```

### Dry Run

Preview the generated configuration files without writing anything:

```bash
uv run agblogger-deploy --dry-run
```

In non-interactive mode:

```bash
uv run agblogger-deploy --dry-run --non-interactive \
  --admin-username admin --admin-password pass --trusted-hosts blog.example.com
```

## Deployment Modes

The first wizard choice is the **deployment mode**, which determines where the Docker image comes from.

### Local (`local`)

Builds the image from the local source tree and runs it on the same machine. Use this when deploying directly on the server that has the source code.

**What happens:**
1. Generates `.env.production` and compose/Caddyfile configs in the project directory.
2. Builds the Docker image from the local `Dockerfile`.
3. Scans the image with Trivy (if installed and `--skip-scan` is not set).
4. Starts containers with `docker compose up -d --build`.
5. Polls until all services (AgBlogger, GoatCounter, and Caddy if enabled) are healthy.

**Lifecycle commands (printed after deployment):**
```bash
# Using docker-compose.yml (bundled Caddy example)
docker compose --env-file .env.production -f docker-compose.yml up -d        # start
docker compose --env-file .env.production -f docker-compose.yml down          # stop
docker compose --env-file .env.production -f docker-compose.yml ps            # status
docker compose --env-file .env.production -f docker-compose.yml logs -f       # logs
docker compose --env-file .env.production -f docker-compose.yml up -d --build # upgrade
```

### Registry (`registry`)

Builds the image locally, pushes it to a container registry, and produces a deployment bundle that pulls from that registry on the remote server.

**What the wizard asks additionally:**
- Container image reference (e.g., `ghcr.io/yourname/agblogger:v1.0`)

**What happens:**
1. Builds the Docker image for `linux/amd64` (overridable with `--platform`).
2. Scans the image with Trivy (if installed).
3. Pushes the image to the registry.
4. Writes a self-contained deployment bundle to `dist/deploy/`.

**Bundle contents:**
- `.env.production.generated` — secrets and configuration (renamed to `.env.production` on first install by `setup.sh`; preserved on upgrades)
- `docker-compose.image.yml` (or variant) — compose file referencing the registry image (with `.generated` suffix, placed by `setup.sh`)
- `Caddyfile.production` — Caddy config (if Caddy is enabled, with `.generated` suffix)
- `goatcounter/entrypoint.sh` — GoatCounter sidecar startup script
- `setup.sh` — idempotent setup/upgrade script
- `DEPLOY-REMOTE.md` — instructions for the remote server
- `VERSION` — version marker for upgrade tracking
- `content/` — empty content directory seed

### Tarball (`tarball`)

Same as registry mode, but instead of pushing to a registry, the image is saved as a gzip-compressed tarball and included in the bundle. Use this when the remote server has no registry access.

**What the wizard asks additionally:**
- Container image reference (used as the image tag)
- Tarball filename (default: `agblogger-image.tar.gz`)

**What happens:**
1. Builds the Docker image for `linux/amd64`.
2. Scans the image with Trivy (if installed and `--skip-scan` is not set).
3. Saves the image to a gzipped tarball with `docker save` + gzip compression.
4. Writes the deployment bundle to `dist/deploy/`, including the tarball.

## Deploying to a Remote Server

For `registry` and `tarball` modes, the wizard produces a bundle at `dist/deploy/`. Transfer it to the remote server and run the setup script:

```bash
# From your local machine
rsync -av dist/deploy/ user@your-server:~/agblogger/

# On the remote server
cd ~/agblogger
bash setup.sh
```

### What `setup.sh` Does

The setup script is idempotent — safe to run on both fresh installs and upgrades:

1. **Preflight checks**: verifies Docker, Docker Compose V2, and `.env.production` (or `.env.production.generated`) are present.
2. **File placement**: moves `.generated` config files (compose, Caddyfile) into their final names, backing up existing versions to `.bak`. For `.env.production`, the generated file is only placed on first install — existing env files are preserved on upgrades.
3. **Stack teardown on mode change**: if the Caddy mode changed since the last deployment, tears down the old stack before starting the new one.
4. **Image loading**: runs `docker load -i <tarball>` (tarball mode) or `docker compose pull` (registry mode).
5. **Shared Caddy bootstrap** (external Caddy mode only): creates the shared Caddy directory, writes the root Caddyfile and compose file, starts the Caddy container directly with Docker, detects the Docker network subnet, writes the site snippet, and reloads Caddy.
6. **Starts AgBlogger**: runs `docker compose up -d`.
7. **Health check**: polls for up to 60 seconds until all services report healthy.

### Upgrading a Remote Deployment

1. Regenerate the bundle locally (run the wizard again).
2. Replace all files on the remote server **except** `.env.production` (keep your existing secrets).
3. If the image tag changed, update `AGBLOGGER_IMAGE` in `.env.production`.
4. Run `bash setup.sh` again.

### Rolling Back

Compose files and Caddyfile are backed up to `.bak` by `setup.sh`. To roll back:

```bash
# Restore the previous compose file (example for bundled Caddy)
cp docker-compose.image.yml.bak docker-compose.image.yml
# Then start with the previous configuration
docker compose --env-file .env.production -f <compose-file> up -d
```

## Caddy Reverse Proxy Modes

The second major wizard choice is the **Caddy mode**, which determines how TLS termination and reverse proxying work.

### Bundled (default)

A dedicated Caddy container runs alongside AgBlogger in the same Docker Compose stack. Caddy automatically provisions TLS certificates from Let's Encrypt.

**Best for:** Single-service servers where AgBlogger is the only web application.

**What the wizard asks:**
- Public domain (e.g., `blog.example.com`)
- Email for TLS certificate notices (optional but recommended)
- Whether to expose Caddy ports 80/443 publicly (default: yes; TCP `443` and UDP `443` are both published so HTTP/3 can negotiate)

**How it works:**
- The compose stack includes `agblogger`, `caddy`, and `goatcounter` services on a shared bridge network (`172.30.0.0/24`).
- Caddy listens on ports 80 and 443, publishes both TCP and UDP `443`, explicitly enables `h1`/`h2`/`h3`, and reverse-proxies to `agblogger:8000`.
- The Caddy subnet (`172.30.0.0/24`) is automatically added to `TRUSTED_PROXY_IPS`.
- If public exposure is disabled, Caddy binds to `127.0.0.1` only (useful when another proxy sits in front).

**Generated files:**
- `Caddyfile.production` — domain-specific Caddy config with request body limits, HSTS, explicit `h1`/`h2`/`h3` support, caching headers, and compression
- `docker-compose.yml` — compose file for local deploys (includes AgBlogger, Caddy, and GoatCounter). For local deploys with public Caddy, `docker-compose.caddy-public.yml` is used as an additional overlay to bind Caddy to `0.0.0.0`.
- `docker-compose.image.yml` — compose file for remote bundles (Caddy public/private ports are baked in based on the wizard choice, no separate overlay needed)

**DNS requirement:** Your domain's A/AAAA record must point to the server *before* starting. Caddy will fail to start if it cannot reach Let's Encrypt to provision a certificate.

### External

AgBlogger joins a shared Caddy instance that lives in a separate shared runtime. Each service on the server drops a site snippet into the shared Caddy's `sites/` directory.

**Best for:** Multi-service servers with multiple subdomains served by a single Caddy instance.

**What the wizard asks:**
- Public domain
- Email for TLS certificate notices
- Shared Caddy directory (default: `~/.local/share/caddy`)
- ACME email for the shared Caddy instance (defaults to the certificate email)

**How it works:**
- A shared Caddy container is bootstrapped automatically if not already running. The deployment helper writes a reference `docker-compose.yml` into the shared Caddy directory, but starts the container directly with Docker so the default home-scoped path works on hosts that use snap-packaged Docker.
- The shared Caddyfile uses `import /etc/caddy/sites/*.caddy` to load per-service site snippets and explicitly enables `h1`/`h2`/`h3`.
- AgBlogger's compose file joins the external `caddy` Docker network instead of running its own Caddy container.
- The Caddy network subnet is auto-detected at deploy time and written into `TRUSTED_PROXY_IPS`.
- Configuration changes are applied via `docker exec caddy caddy reload` (no container restart needed).

**Shared Caddy directory structure** (e.g., at `~/.local/share/caddy`):
```
~/.local/share/caddy/
  Caddyfile              # Global config with import directive
  docker-compose.yml     # Shared Caddy container definition
  sites/
    blog.example.com.caddy   # AgBlogger site snippet
    other.example.com.caddy  # Other services
```

**Generated files:**
- `docker-compose.external-caddy.yml` / `docker-compose.image.external-caddy.yml` — compose file that joins the external Caddy network
- Site snippet at `<caddy-dir>/sites/<domain>.caddy`

### None

No Caddy reverse proxy. AgBlogger's port is exposed directly.

**Best for:** Environments where another reverse proxy (nginx, Traefik, etc.) is already in place, or for testing.

**What the wizard asks:**
- Whether to expose AgBlogger directly on the Internet (bind `0.0.0.0` vs `127.0.0.1`)
- Host port (default: 8000)

**Generated files:**
- `docker-compose.nocaddy.yml` / `docker-compose.image.nocaddy.yml` — compose file with AgBlogger and GoatCounter services, AgBlogger ports exposed directly

**No TLS:** In this mode there is no automatic HTTPS. Use this behind an existing reverse proxy that handles TLS, or only for local/testing use.

## Wizard Prompts Reference

The interactive wizard asks the following questions in order:

| # | Prompt | Default | Notes |
|---|--------|---------|-------|
| 1 | Reuse existing credentials? | Yes | Only shown if `.env.production` already exists |
| 2 | SECRET_KEY | Auto-generated | Leave blank to generate a random 64-byte key |
| 3 | Admin username | `admin` | |
| 4 | Admin display name | Same as username | |
| 5 | Admin password | — | Must be 8+ characters, confirmed twice |
| 6 | Deployment mode | `tarball` | `tarball`, `registry`, or `local` |
| 7 | Image reference | `agblogger:latest` | Only for registry/tarball modes |
| 8 | Tarball filename | `agblogger-image.tar.gz` | Only for tarball mode |
| 9 | Caddy mode | `bundled` | `bundled`, `external`, or `none` |
| 10 | Public domain | — | Only for bundled/external Caddy |
| 11 | TLS email | — | Optional, for Let's Encrypt notices |
| 12 | Expose Caddy publicly? | Yes | Only for bundled Caddy |
| 13 | Shared Caddy directory | `~/.local/share/caddy` | Only for external Caddy |
| 14 | ACME email for shared Caddy | Same as TLS email | Only for external Caddy |
| 15 | Expose directly on Internet? | No | Only for no-Caddy mode |
| 16 | Host port | 8000 | Only for no-Caddy mode |
| 17 | Additional trusted hosts | — | Domain auto-included if Caddy is enabled |
| 18 | Additional trusted proxy IPs | — | Caddy subnet auto-configured |
| 19 | Expose API docs? | No | Enables `/docs` endpoint |

After all prompts, the wizard prints a configuration summary and asks for confirmation before proceeding.

## Deploying Locally (Production-Like)

To run a production-like deployment on your development machine:

```bash
just deploy
```

Choose `local` deployment mode and `bundled` Caddy (or `none` for simplicity). For local testing without a real domain, choose Caddy mode `none`:

```bash
uv run agblogger-deploy --non-interactive \
  --deployment-mode local \
  --admin-username admin \
  --admin-password 'testpassword' \
  --trusted-hosts localhost \
  --host-port 8000
```

This starts AgBlogger at `http://localhost:8000`.

Note: This is separate from the development server (`just start`). The local production deployment uses the Docker image and production configuration, which is useful for verifying deployment behavior.

## Environment Variables

The generated `.env.production` contains:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing key (auto-generated or user-provided) |
| `ADMIN_USERNAME` | Initial admin account username |
| `ADMIN_PASSWORD` | Initial admin account password |
| `ADMIN_DISPLAY_NAME` | Admin display name |
| `TRUSTED_HOSTS` | JSON array of allowed Host header values |
| `TRUSTED_PROXY_IPS` | JSON array of trusted reverse proxy IP ranges |
| `HOST_PORT` | Port to expose (no-Caddy mode only) |
| `HOST_BIND_IP` | Bind address: `127.0.0.1` or `0.0.0.0` |
| `DEBUG` | Always `false` for production |
| `EXPOSE_DOCS` | Whether `/docs` is accessible |
| `AUTH_ENFORCE_LOGIN_ORIGIN` | Origin validation for login requests |
| `AUTH_LOGIN_MAX_FAILURES` | Max failed login attempts before lockout |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Rate limit window duration |
| `BLUESKY_CLIENT_URL` | Bluesky cross-posting URL (commented out by default) |
| `AGBLOGGER_IMAGE` | Image reference (registry/tarball modes only) |

## Data Persistence

- **Content**: stored in `./content/` (bind mount). This is the canonical source of truth for all posts and site configuration.
- **Database**: stored in the `agblogger-db` Docker volume. Contains user accounts, auth tokens, connected social accounts, and the regenerable content cache.
- **GoatCounter**: analytics data stored in the `goatcounter-db` Docker volume. The `goatcounter-token` volume shares the API token between GoatCounter and AgBlogger.
- **Caddy**: TLS certificates and configuration state stored in `caddy-data` and `caddy-config` Docker volumes (only when using bundled Caddy mode).
- All persistent volumes and the content bind mount must be preserved during upgrades. Schema migrations run automatically on startup.

## CLI Reference

```
uv run agblogger-deploy [OPTIONS]

Options:
  --version                   Show version and exit
  --project-dir PATH          Project directory (default: current directory)
  --dry-run                   Preview config without writing or deploying
  --non-interactive           Skip interactive prompts; use CLI flags

Configuration:
  --secret-key TEXT           JWT signing key (auto-generated if omitted)
  --admin-username TEXT       Initial admin username
  --admin-password TEXT       Admin password (also via ADMIN_PASSWORD env var)
  --admin-display-name TEXT   Admin display name (defaults to username)
  --caddy-domain TEXT         Enable Caddy HTTPS with this domain
  --caddy-email TEXT          Email for TLS certificate notifications
  --caddy-public              Expose Caddy ports 80/443 publicly
  --caddy-external            Use a shared external Caddy instance
  --shared-caddy-dir PATH    Shared Caddy directory (default: ~/.local/share/caddy)
  --shared-caddy-email TEXT   ACME email for shared Caddy
  --trusted-hosts TEXT        Comma-separated allowed Host header values
  --trusted-proxy-ips TEXT    Comma-separated trusted proxy IPs
  --host-port INT             Host port (default: 8000, no-Caddy mode)
  --bind-public               Bind to 0.0.0.0 (no-Caddy mode only)
  --expose-docs               Enable /docs endpoint
  --deployment-mode MODE      tarball, registry, or local (default: tarball)
  --image-ref TEXT            Image reference (registry/tarball modes)
  --bundle-dir PATH           Bundle output directory (default: dist/deploy)
  --tarball-filename TEXT     Tarball name (default: agblogger-image.tar.gz)
  --platform TEXT             Docker build platform (default: linux/amd64 for remote)
  --skip-scan                 Skip the Trivy security scan of the Docker image
```
