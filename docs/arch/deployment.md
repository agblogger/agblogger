# Deployment

## Deployment Model

AgBlogger is packaged as a single backend runtime plus a built frontend bundle. In production, the common deployment shape is:

- one application container serving the API and SPA
- an optional reverse proxy in front for TLS termination and public ingress
- persistent volumes for content and database state

This matches the project's self-hosted deployment model.

## Runtime Topology

The preferred production topology places a reverse proxy in front of the application, with a GoatCounter analytics sidecar on the internal network:

- one application container serving the API and SPA
- a GoatCounter container for page view analytics (internal network only, no public exposure)
- an optional reverse proxy in front for TLS termination and public ingress
- persistent volumes for content, database state, and GoatCounter data (including the shared API token)

GoatCounter is a soft dependency — the application starts and serves content normally when GoatCounter is unavailable. The GoatCounter container provisions itself on first boot via a custom entrypoint script (`goatcounter/entrypoint.sh`) that creates the site, generates an API token, and writes it to a shared volume.

## Packaging

The production image contains the backend runtime, the built frontend assets, and the external tools the application depends on at runtime. Containerization preserves the filesystem-first content model by mounting persistent storage for content and database state instead of baking them into the image.

## Schema Migrations

Database schema migrations run programmatically during application startup, before the server begins accepting requests. Durable tables (users, tokens, invites, social accounts, cross-posts) are managed by Alembic, so upgrades apply schema changes without data loss. Cache tables are regenerated from the filesystem on every startup and do not require migrations.

## Deployment Workflows

The repository includes deployment tooling for local and remote deployments. These workflows differ in how they deliver the image and configuration, but they converge on the same runtime architecture.

Remote deployment bundles include a `setup.sh` deployment orchestrator script. The script handles file placement, image loading/pulling, external Caddy bootstrapping, old-stack teardown on mode switches, container startup, and health checking. The script is idempotent — safe to run on both fresh installs and upgrades.

The upgrade workflow is: regenerate the bundle locally, copy all files to the server, run `bash setup.sh`.

## Caddy Reverse Proxy Modes

The deployment helper supports three Caddy configurations:

- **Bundled** (default): a dedicated Caddy container is deployed alongside AgBlogger in the same compose stack. Suitable for single-service servers.
- **External**: AgBlogger joins a shared Caddy instance that lives in a separate compose stack at a configurable host directory (default `/opt/caddy`). Each service drops a site snippet into the shared `sites/` directory. Local deploys resolve the live shared-network subnet into `TRUSTED_PROXY_IPS`, and remote bundles do the same during `setup.sh` using the first configured shared-network subnet before the app starts. Suitable for multi-service servers with distinct subdomains.
- **None**: no Caddy; AgBlogger is exposed directly. Suitable when another reverse proxy is already in place.

Switching between Caddy modes is handled automatically by `setup.sh`.

## Verification Path

The project also supports a packaged local deployment profile for deployment-style verification and dynamic scanning. It is separate from the day-to-day development server so production-like serving paths can be exercised before or alongside real deployments.

## Code Entry Points

- `Dockerfile` defines the production image.
- `docker-compose.yml` defines the standard container topology (application, Caddy, GoatCounter).
- `goatcounter/entrypoint.sh` is the GoatCounter container's first-boot provisioning and startup script.
- `cli/deploy_production.py` contains the deployment helper, configuration generation, and `setup.sh` script generation workflow.
- `cli/release.py` contains release workflow tooling.
- `tests/test_cli/test_deploy_production.py` covers the deployment helper behavior.
