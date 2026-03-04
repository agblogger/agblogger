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

Recommended deployment path is the interactive helper:

```bash
uv run agblogger-deploy
```

## Production HTTPS

When enabled in the deploy helper, Caddy is configured as a reverse proxy in front of AgBlogger with automatic Let's Encrypt TLS, static asset caching with `Cache-Control: immutable`, gzip/zstd compression, and request-body caps for multipart upload endpoints (`55 MB` for post upload/assets, `100 MB` for sync commit).
