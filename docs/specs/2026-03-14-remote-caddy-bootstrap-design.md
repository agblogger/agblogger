# Remote Caddy Bootstrap Setup Script

## Problem

Remote deployments (tarball/registry) with external Caddy mode don't work out of the box. The bundle is generated locally but the shared Caddy bootstrapping only runs during local deployments. The DEPLOY-REMOTE.md inaccurately claims "the deployment script will bootstrap the shared Caddy instance." Users must manually create the Caddy directory structure, write config files, start the container, and reload — none of which is documented with actionable steps.

Additionally, several related bugs affect the deployment experience:
- External Caddy mode hardcodes the wrong proxy subnet (172.30.0.0/24 instead of the `caddy` network's actual subnet)
- The base `docker-compose.yml` (used for bundled-Caddy local deployments) is missing `ADMIN_DISPLAY_NAME` — the generated compose files already include it via `_agblogger_env_section()`
- `--caddy-external` without `--caddy-domain` results in no-Caddy mode without any warning in non-interactive mode (the interactive flow uses a prompt menu so this doesn't apply there)
- Local deployments don't seed the `content/` directory (the bundle path already does this)

## Design

### Setup script (`setup.sh`)

A new function `build_setup_script_content(config: DeployConfig) -> str` generates a bash script tailored to the deployment configuration. The script is written into the bundle by `write_bundle_files()` and made executable. `setup.sh` is added to the `BUNDLE_CONFIG_FILES` list so it is backed up on re-deployment like other generated files. The setup script is only generated for remote deployments (tarball/registry mode).

The script is idempotent — safe to run on fresh installs and upgrades alike. Partial failures are safe because each step uses if-not-exists guards or overwrite-safe operations, so re-running the script after a mid-run failure converges to the correct state. If any step fails, `set -euo pipefail` halts the script immediately; the user can fix the issue and re-run.

The script uses `set -euo pipefail` for safety and prints clear progress messages at each step.

It performs these steps in order:

1. **Preflight checks**: verify Docker is installed and the daemon is running.
2. **Load/pull image** (mode-dependent):
   - Tarball: `docker load -i <tarball>`
   - Registry: `docker compose <flags> pull`
3. **External Caddy bootstrap** (external mode only):
   - Create shared Caddy directory (path from `shared_caddy_config.caddy_dir`, default `/opt/caddy/`) and `sites/` subdirectory if they don't exist. All paths in the script are parameterized from the config, not hardcoded.
   - Write `Caddyfile` and `docker-compose.yml` for the shared instance if they don't exist. On upgrade, these are preserved so user customizations are not lost. If a future AgBlogger version requires changes to the shared Caddy compose file, the upgrade instructions will need to note this — but this is expected to be rare. The files are embedded as heredocs in the script so the bundle is self-contained.
   - Create the `caddy` Docker network if it doesn't exist
   - Start the shared Caddy container if not running (`docker compose up -d` in the shared Caddy directory)
   - Detect the `caddy` network's IPv4 subnet and update `TRUSTED_PROXY_IPS` in `.env.production` (see proxy subnet fix below). This depends on the network existing (from the previous steps); if Caddy startup failed, the script will have already halted due to `set -e`.
   - Write/overwrite the AgBlogger site snippet into `sites/<domain>.caddy`. The site snippet is always overwritten (unlike the shared Caddyfile) because it reflects the current deployment config and must stay in sync with the bundle.
   - Reload Caddy (`docker exec caddy caddy reload --config /etc/caddy/Caddyfile`)
4. **Start/restart AgBlogger**: `docker compose <flags> up -d`, using the same compose file flags (`-f <file> --env-file .env.production`) as the lifecycle commands.
5. **Health check**: poll `docker compose <flags> ps --format "{{.Service}}: {{.Status}}"` (with the same compose file flags and format string as the Python `_wait_for_healthy`) until the agblogger service reports `(healthy)` or a timeout (60s) is reached. Print status updates during polling.

#### Container name resolution on external networks

The external Caddy compose files join the `caddy` Docker network. The site snippet uses `reverse_proxy agblogger:8000`. Docker Compose registers the service name as a DNS alias on all networks the service is connected to, including external ones, so `agblogger` resolves correctly from the Caddy container. If multiple compose projects on the same network define an `agblogger` service, there would be a naming conflict — but this is a single-purpose deployment and not a realistic scenario.

### DEPLOY-REMOTE.md changes

The README is simplified and generated per-config (as it already is). The primary getting-started instructions become:

```
## Prerequisites

- Docker Engine (20.10+)
- Docker Compose V2 (`docker compose` subcommand)
```

For Caddy-enabled deployments (bundled or external), a DNS prerequisite is added: "DNS A/AAAA record pointing your domain to this server (required for TLS certificate provisioning)." This does not appear for no-Caddy mode.

```
## Getting started

1. Copy this directory to the remote server
2. Run ./setup.sh
```

The existing "Shared Caddy Setup" section (which inaccurately says "The deployment script will bootstrap the shared Caddy instance") is removed — `setup.sh` now handles bootstrapping automatically.

Individual management commands (start, stop, logs, status) remain documented for day-to-day use. The upgrade instructions become: regenerate the bundle locally, copy to server replacing existing files, run `./setup.sh` again.

### Bug fixes

**Wrong proxy subnet for external Caddy mode**: In external Caddy mode, the `caddy` Docker network has a Docker-managed subnet, not the hardcoded `COMPOSE_SUBNET` (172.30.0.0/24). The fix has two parts:

- *Python side*: Both `collect_config` (interactive) and `config_from_args` (non-interactive) stop adding `COMPOSE_SUBNET` to `TRUSTED_PROXY_IPS` when `caddy_mode == CADDY_MODE_EXTERNAL`. Instead, a placeholder `__CADDY_NETWORK_SUBNET__` is added to the proxy IPs list. The Python-generated `.env.production` serializes this placeholder inside the JSON array (e.g., `TRUSTED_PROXY_IPS=["__CADDY_NETWORK_SUBNET__"]` or `TRUSTED_PROXY_IPS=["10.0.0.0/8","__CADDY_NETWORK_SUBNET__"]` if the user also supplied IPs). In the interactive flow, a message explains that the proxy subnet will be auto-detected at deploy time.
- *Setup script side*: After the `caddy` Docker network exists (step 3), the setup script detects the IPv4 subnet via `docker network inspect caddy --format '{{(index .IPAM.Config 0).Subnet}}'` (using index 0 to select only the first/IPv4 IPAM config, avoiding concatenation of IPv4+IPv6 subnets — this matches standard Docker behavior where IPv4 is first). It then replaces the `__CADDY_NETWORK_SUBNET__` placeholder in `.env.production` with the detected subnet using `sed` with the `|` delimiter (since subnets contain `/`, e.g. `172.18.0.0/16`): `sed -i "s|__CADDY_NETWORK_SUBNET__|$SUBNET|" .env.production`. This is a simple string replacement that doesn't require JSON parsing in bash. If subnet detection fails (e.g. due to a Docker issue), `set -e` halts the script before AgBlogger starts, so the placeholder is never consumed by the application.

For bundled Caddy mode and no-Caddy mode, the existing behavior (hardcoded `COMPOSE_SUBNET`) is unchanged — those modes use a compose-defined network with a known subnet.

**`docker-compose.yml` missing `ADMIN_DISPLAY_NAME`**: Add `- ADMIN_DISPLAY_NAME=${ADMIN_DISPLAY_NAME:-}` to the environment section in the base `docker-compose.yml`. This is the only compose file affected — all generated compose files already include it.

**`--caddy-external` without `--caddy-domain`**: In `config_from_args`, raise `DeployError("--caddy-external requires --caddy-domain")` when `--caddy-external` is set without `--caddy-domain`. Currently, this combination silently falls through to no-Caddy mode. The interactive flow is not affected because it uses a menu prompt for Caddy mode selection.

**No `content/` directory for local deployments**: Add `(project_dir / "content").mkdir(exist_ok=True)` in `write_config_files()`. The bundle path (`write_bundle_files()`) already does this.

## Files changed

- `cli/deploy_production.py` — new `build_setup_script_content()` function; changes to `write_bundle_files()`, `_build_remote_readme_content()`, `collect_config()`, `config_from_args()`, `write_config_files()`; add `setup.sh` to `BUNDLE_CONFIG_FILES`
- `docker-compose.yml` — add `ADMIN_DISPLAY_NAME` env var to the environment section
- `tests/test_cli/test_deploy_production.py` — tests for setup script generation, proxy subnet handling, new error cases
- `docs/arch/deployment.md` — document setup script as part of bundle structure and remote deployment workflow

## Testing

- Test that `build_setup_script_content()` produces correct script content for each combination of deployment mode (tarball, registry) and Caddy mode (none, bundled, external)
- Test that the external Caddy script includes heredocs for shared Caddyfile and compose file, site snippet, network creation, subnet detection with placeholder replacement, and Caddy reload
- Test that `write_bundle_files()` writes `setup.sh` and marks it executable
- Test that `--caddy-external` without `--caddy-domain` raises `DeployError`
- Test that external Caddy mode uses `__CADDY_NETWORK_SUBNET__` placeholder instead of `COMPOSE_SUBNET` in proxy IPs for both `collect_config` and `config_from_args`
- Test that `write_config_files()` creates the `content/` directory
- Test that the base `docker-compose.yml` includes `ADMIN_DISPLAY_NAME`
