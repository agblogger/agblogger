# setup.sh Redesign: Smart Bundle Deployment

## Problem

The current remote deployment bundle has several design flaws:

1. **`.env.production` footgun**: The local deploy script generates `.env.production` in the bundle, then the README tells users to "copy everything except `.env.production`". If the user copies it anyway, they overwrite their live secrets (`SECRET_KEY`, which is used for JWT signing and social account credential encryption — changing it causes permanent data loss of encrypted OAuth tokens).

2. **Useless local backups**: `_backup_bundle_configs` creates `.bak` files in `dist/deploy/` for generated files that are about to be regenerated from scratch. No user state lives in the local bundle directory. Worse, `backup_existing_configs` runs unconditionally — even for remote bundle generation — creating `.bak` files in the project root that could be accidentally copied to the remote server and override real backups there.

3. **No old-stack teardown on mode switch**: When switching Caddy modes (bundled to external, external to none, etc.), `setup.sh` runs `docker compose up -d` with the new compose files but never stops containers from the old compose files. The operator must manually tear down the old stack.

4. **setup.sh backup is misleading**: `setup.sh` backs up `.env.production` at the start, but since setup.sh itself is part of the bundle that was just copied over, this backup only captures whatever `.env.production` was present *after* the copy — not the previous version. The backup is only meaningful for the `sed` subnet replacement in external Caddy mode.

## Design

### 1. The `.generated` file pattern

#### Local bundle generation

The deploy script generates all bundle files with a `.generated` suffix:

- `.env.production.generated`
- `docker-compose.image.yml.generated` (or whichever compose variant applies)
- `Caddyfile.production.generated` (when Caddy is configured)

Non-config files that don't need the backup/override pattern are written directly without the `.generated` suffix: `setup.sh`, `DEPLOY-REMOTE.md`, `VERSION`, `content/` directory, image tarball.

#### setup.sh file placement

setup.sh handles two categories of `.generated` files differently:

**Config files** (compose files, Caddyfile): Back up the existing file to `.bak` if present, then move `.generated` into place. These must always match the current version — the backup is purely for rollback.

**`.env.production`**: Seed-only behavior.
- If `.env.production` does not exist (first install): move `.env.production.generated` into place.
- If `.env.production` already exists (upgrade): leave it alone. Print an informational message:
  ```
  Existing .env.production found — keeping it (not overwriting with generated version).
  To use the newly generated config instead, run:
    cp .env.production.generated .env.production
  ```
  Leave `.env.production.generated` in place as a reference.

#### Caddy subnet patching (external mode only)

In external Caddy mode, the `.env.production` contains a `__CADDY_NETWORK_SUBNET__` placeholder in `TRUSTED_PROXY_IPS` that must be resolved to the live Docker network subnet. setup.sh patches **both** files:

- `.env.production.generated` — so it's ready to copy if the user wants to use it.
- `.env.production` — because the subnet can change between Docker restarts.

The `sed` replacement targets the placeholder string, so it's safe to run on files that have already been patched (no match, no change) or that don't contain the placeholder (non-external modes).

### 2. Old-stack teardown

setup.sh writes a `.last-teardown` marker file after each successful deploy. This file stores enough information to detect a mode change and correctly tear down the old stack:

- The compose command prefix (with `-f` flags for the old compose files)
- Enough to run `<old-command> down` before starting the new stack

On each run, setup.sh:

1. Reads `.last-teardown` if it exists.
2. Compares the stored compose command with the current one.
3. If they differ (mode switch), runs the old teardown command (`docker compose ... down`).
4. If they match (same mode upgrade), skips teardown — `--force-recreate` handles container replacement.
5. After successful startup, writes the current compose command to `.last-teardown`.

On first install, no `.last-teardown` exists, so no teardown is attempted.

### 3. Local backup cleanup

- **Remove `_backup_bundle_configs`** entirely. It backs up generated files in `dist/deploy/` that are about to be overwritten — no user state lives there.
- **Guard `backup_existing_configs`** so it only runs for `DEPLOY_MODE_LOCAL`. Currently it runs unconditionally in `deploy()`, creating `.bak` files in the project root even during remote bundle generation. These stray `.bak` files could be copied to the remote server and override real backups.

### 4. Stale file cleanup

The current `write_bundle_files` deletes stale compose files from other Caddy modes (e.g., deleting the bundled Caddyfile when generating an external Caddy bundle). This logic needs to be updated to account for the `.generated` suffix — stale `.generated` files from a previous bundle generation for a different mode should be cleaned up.

### 5. README updates

`DEPLOY-REMOTE.md` upgrade instructions simplify from:

> 1. Regenerate the bundle locally and replace all files **except `.env.production`**

To:

> 1. Regenerate the bundle locally and copy all files to the server
> 2. Run `bash setup.sh`

The README should also document:
- That `.env.production` is preserved automatically on upgrades
- The `.env.production.generated` reference file and how to override with it
- That Caddy mode switches are handled automatically (old stack is torn down)

## Files changed

- `cli/deploy_production.py` — bundle generation (`.generated` suffix), remove `_backup_bundle_configs`, guard `backup_existing_configs` for local-only, update README generation, update setup.sh generation (file placement logic, old-stack teardown, `.last-teardown` marker, subnet patching for both files)
- `tests/test_cli/test_deploy_production.py` — update existing tests, add new tests for: `.generated` file placement, seed-only `.env.production` behavior, old-stack teardown with mode switching, `.last-teardown` marker, dual subnet patching, local backup guarding
- `docs/arch/deployment.md` — update to reflect new bundle deployment workflow
