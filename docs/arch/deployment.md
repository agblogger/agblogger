# Deployment

## Deployment Model

AgBlogger is packaged as a single backend runtime plus a built frontend bundle. In production, the common deployment shape is:

- one application container serving the API and SPA
- an optional reverse proxy in front for TLS termination and public ingress
- persistent volumes for content and database state

This matches the project's self-hosted deployment model.

## Runtime Topology

The preferred production topology places a reverse proxy in front of the application. A direct-exposure mode also exists for simpler environments, but the architectural shape stays the same: durable content storage, durable database storage, and one application runtime.

## Packaging

The production image contains the backend runtime, the built frontend assets, and the external tools the application depends on at runtime. Containerization preserves the filesystem-first content model by mounting persistent storage for content and database state instead of baking them into the image.

## Schema Migrations

Database schema migrations run programmatically during application startup, before the server begins accepting requests. Durable tables (user accounts, authentication tokens, social account connections) are managed by Alembic, so upgrades apply schema changes without data loss. Cache tables are regenerated from the filesystem on every startup and do not require migrations.

## Deployment Workflows

The repository includes deployment tooling for local and remote deployments. These workflows differ in how they deliver the image and configuration, but they converge on the same runtime architecture.

## Verification Path

The project also supports a packaged local deployment profile for deployment-style verification and dynamic scanning. It is separate from the day-to-day development server so production-like serving paths can be exercised before or alongside real deployments.

## Code Entry Points

- `Dockerfile` defines the production image.
- `docker-compose.yml` defines the standard container topology.
- `cli/deploy_production.py` contains the deployment helper and configuration generation workflow.
- `tests/test_cli/test_deploy_production.py` covers the deployment helper behavior.
