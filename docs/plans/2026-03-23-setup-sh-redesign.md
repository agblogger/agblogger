# setup.sh Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make setup.sh the smart deployment orchestrator — handling file placement, backups, old-stack teardown, and `.env.production` preservation — instead of relying on fragile manual instructions.

**Architecture:** Bundle files are generated with a `.generated` suffix locally. setup.sh on the remote server handles placement (backup + overwrite for config files, seed-only for `.env.production`), tears down old stacks on Caddy mode switches via a `.last-teardown` marker, and patches Caddy subnet in both env files. Local backup logic is removed for bundles and guarded for local-only deploys.

**Tech Stack:** Python (cli/deploy_production.py), Bash (generated setup.sh), pytest

**Spec:** `docs/specs/2026-03-23-setup-sh-redesign.md`

---

### Task 1: Add `.generated` suffix to bundle file generation

**Files:**
- Modify: `cli/deploy_production.py:1486-1555` (`write_bundle_files`)
- Modify: `cli/deploy_production.py:1307-1318` (`_write_env_file`)
- Modify: `cli/deploy_production.py:102-111` (`BUNDLE_CONFIG_FILES`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for `.generated` suffix in bundle files**

Add tests that verify `write_bundle_files` creates files with `.generated` suffix:

```python
class TestGeneratedSuffix:
    def test_bundled_caddy_creates_generated_files(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        write_bundle_files(config, tmp_path)
        assert (tmp_path / ".env.production.generated").exists()
        assert (tmp_path / "docker-compose.image.yml.generated").exists()
        assert (tmp_path / "Caddyfile.production.generated").exists()
        # Old un-suffixed versions should NOT exist
        assert not (tmp_path / ".env.production").exists()
        assert not (tmp_path / "docker-compose.image.yml").exists()
        assert not (tmp_path / "Caddyfile.production").exists()

    def test_external_caddy_creates_generated_files(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"), acme_email="admin@example.com",
            ),
        )
        write_bundle_files(config, tmp_path)
        assert (tmp_path / ".env.production.generated").exists()
        assert (tmp_path / "docker-compose.image.external-caddy.yml.generated").exists()
        assert not (tmp_path / ".env.production").exists()

    def test_no_caddy_creates_generated_files(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        assert (tmp_path / ".env.production.generated").exists()
        assert (tmp_path / "docker-compose.image.nocaddy.yml.generated").exists()
        assert not (tmp_path / ".env.production").exists()

    def test_env_generated_has_restrictive_permissions(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        env_path = tmp_path / ".env.production.generated"
        assert env_path.stat().st_mode & 0o777 == 0o600

    def test_non_config_files_have_no_generated_suffix(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        assert (tmp_path / "setup.sh").exists()
        assert (tmp_path / "DEPLOY-REMOTE.md").exists()
        assert (tmp_path / "VERSION").exists()
        assert (tmp_path / "content").is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestGeneratedSuffix -v`
Expected: FAIL — files still use old un-suffixed names.

- [ ] **Step 3: Implement `.generated` suffix in `write_bundle_files`**

In `cli/deploy_production.py`:

1. Add a new constant for the generated env filename:
```python
DEFAULT_ENV_GENERATED_FILE = ".env.production.generated"
```

2. Create a helper `_write_env_generated_file` that writes to `.env.production.generated` instead of `.env.production`:
```python
def _write_env_generated_file(config: DeployConfig, target_dir: Path) -> None:
    """Write the generated environment file with .generated suffix and restrictive permissions."""
    env_path = target_dir / DEFAULT_ENV_GENERATED_FILE
    env_path.write_text(build_env_content(config), encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError as exc:
        print(
            f"WARNING: Could not set restrictive permissions on {DEFAULT_ENV_GENERATED_FILE}: {exc}\n"
            f"This file contains sensitive secrets and may be readable by other users.",
            file=sys.stderr,
        )
```

3. Update `write_bundle_files` to:
   - Call `_write_env_generated_file` instead of `_write_env_file`
   - Write compose files with `.generated` suffix (e.g., `DEFAULT_IMAGE_COMPOSE_FILE + ".generated"`)
   - Write Caddyfile with `.generated` suffix
   - Update stale file cleanup to clean both old `.generated` and old un-suffixed files from other modes

4. Update `DeployResult.env_path` in `deploy()` for remote bundle paths to reference `DEFAULT_ENV_GENERATED_FILE` instead of `DEFAULT_ENV_FILE`, so the post-deploy message points to the correct filename.

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestGeneratedSuffix -v`
Expected: PASS

- [ ] **Step 5: Fix existing tests broken by suffix change**

Existing tests in `TestWriteBundleFiles`, `TestSetupScriptInBundle`, and `TestBuildSetupScript` will reference old filenames. Update them to use `.generated` suffix where they check for file existence in bundles.

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: generate bundle config files with .generated suffix"
```

---

### Task 2: Add file placement logic to setup.sh

**Files:**
- Modify: `cli/deploy_production.py:384-775` (`build_setup_script_content`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for file placement in setup.sh**

```python
class TestSetupScriptFilePlacement:
    def test_preflight_checks_for_generated_env_not_plain(self) -> None:
        """Preflight should check .env.production.generated, not .env.production."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Old check removed
        assert 'if [ ! -f .env.production ];' not in script
        # New check: requires at least one of the two
        assert '.env.production.generated' in script
        assert 'bundle is incomplete' in script.lower() or 'not found' in script.lower()

    def test_config_files_backed_up_and_moved(self) -> None:
        """Config .generated files should be backed up then moved into place."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        # Compose file: backup existing, move .generated into place
        assert "docker-compose.image.yml.generated" in script
        assert "mv " in script  # moves .generated to final name
        assert ".bak" in script  # creates backup

    def test_env_production_seed_only_on_first_install(self) -> None:
        """On first install, .env.production.generated is moved into place."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert 'if [ ! -f .env.production ]' in script
        assert 'mv .env.production.generated .env.production' in script

    def test_env_production_kept_on_upgrade(self) -> None:
        """On upgrade, existing .env.production is kept with informational message."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert 'Existing .env.production found' in script
        assert 'keeping it' in script.lower() or 'not overwriting' in script.lower()
        assert 'cp .env.production.generated .env.production' in script

    def test_chmod_600_applied_in_both_branches(self) -> None:
        """chmod 600 is applied to .env.production in both install and upgrade paths."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # chmod 600 must appear in both the if (first install) and else (upgrade) branches
        # Find the seed-only if/else block and verify chmod appears in each
        first_install_idx = script.index("mv .env.production.generated .env.production")
        upgrade_idx = script.index("Existing .env.production found")
        # chmod in first-install branch (between mv and the else)
        chmod_after_mv = script.index("chmod 600 .env.production", first_install_idx)
        assert chmod_after_mv < upgrade_idx
        # chmod in upgrade branch (after the "Existing" message)
        chmod_after_upgrade = script.index("chmod 600 .env.production", upgrade_idx)
        assert chmod_after_upgrade > upgrade_idx

    def test_file_placement_before_image_load(self) -> None:
        """File placement must happen before image load/pull."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Use the mv command for .generated files as the placement marker
        placement_idx = script.index("mv .env.production.generated")
        load_idx = script.index("docker load")
        assert placement_idx < load_idx

    def test_compose_commands_use_final_filenames(self) -> None:
        """Compose up/down commands should reference final (non-.generated) filenames."""
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        compose_up_line = [l for l in script.splitlines() if "up -d" in l and "compose" in l][0]
        assert "docker-compose.image.yml" in compose_up_line
        assert ".generated" not in compose_up_line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptFilePlacement -v`
Expected: FAIL

- [ ] **Step 3: Implement file placement in `build_setup_script_content`**

In `build_setup_script_content`, after the preflight checks section and before the image load/pull section:

1. Replace the `.env.production` existence check with a check for either file.
2. Remove the old `cp .env.production .env.production.bak` backup line.
3. Add a file placement section that:
   - For each config `.generated` file (compose, Caddyfile): `cp existing.bak` then `mv .generated final`
   - For `.env.production.generated`: seed-only logic (move if `.env.production` doesn't exist, keep existing otherwise)
   - Apply `chmod 600 .env.production`

The list of `.generated` config files to place is known at generation time from the config (compose filename and optionally Caddyfile), so the placement commands are hardcoded into the script per-mode.

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptFilePlacement -v`
Expected: PASS

- [ ] **Step 5: Fix existing setup.sh tests broken by the changes**

Update `TestBuildSetupScript` tests that check for the old `.env.production` preflight or backup behavior.

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBuildSetupScript -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add file placement logic to setup.sh for .generated files"
```

---

### Task 3: Add old-stack teardown to setup.sh

**Files:**
- Modify: `cli/deploy_production.py:384-775` (`build_setup_script_content`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for old-stack teardown**

```python
class TestSetupScriptTeardown:
    def test_writes_last_teardown_marker_on_success(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert ".last-teardown" in script
        # Marker is written after successful startup (near the end, after health check)
        health_idx = script.index("All services healthy")
        teardown_write_idx = script.index(".last-teardown", health_idx)
        assert teardown_write_idx > health_idx

    def test_reads_and_compares_last_teardown(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert 'if [ -f .last-teardown ]' in script

    def test_tears_down_old_stack_on_mode_change(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Teardown section reconstructs old command with .bak files and runs down
        assert "docker compose --env-file .env.production" in script
        # The teardown command uses .bak filenames
        assert '.bak" down' in script or ".bak down" in script or ".bak' down" in script

    def test_skips_teardown_when_flags_match(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Script reads old flags and compares to current before teardown
        assert "CURRENT_COMPOSE_FLAGS" in script
        # Teardown is conditional on flags differing
        assert '"$OLD_COMPOSE_FLAGS" != "$CURRENT_COMPOSE_FLAGS"' in script or \
               '"$OLD_COMPOSE_FLAGS" = "$CURRENT_COMPOSE_FLAGS"' in script

    def test_no_teardown_on_first_install(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Only tears down if marker exists
        assert 'if [ -f .last-teardown ]' in script

    def test_skips_teardown_with_warning_when_bak_missing(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        # Guard: check .bak file exists before attempting teardown
        assert '.bak ]' in script or '.bak"' in script
        # Warning when .bak is missing
        assert 'warning' in script.lower() or 'Warning' in script or 'cannot' in script.lower()

    def test_marker_contains_compose_flags(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        # Marker content should include the compose file used
        assert "docker-compose.image.yml" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptTeardown -v`
Expected: FAIL

- [ ] **Step 3: Implement old-stack teardown in `build_setup_script_content`**

Add a teardown section between file placement and image load/pull:

1. Define `CURRENT_COMPOSE_FLAGS` variable with the current mode's `-f` flag values (one per line in a heredoc or simple string).
2. Read `.last-teardown` if it exists into `OLD_COMPOSE_FLAGS`.
3. Compare old vs current. If different:
   - Reconstruct teardown command using `.bak` filenames: `docker compose --env-file .env.production -f <old-file>.bak down`
   - Guard with existence check on the `.bak` file; skip with warning if missing.
   - Run teardown with `|| true` to avoid aborting the script.
4. After the health check success block (near `exit 0`), write `CURRENT_COMPOSE_FLAGS` to `.last-teardown`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptTeardown -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add old-stack teardown to setup.sh on mode switch"
```

---

### Task 4: Update Caddy subnet patching to patch both files

**Files:**
- Modify: `cli/deploy_production.py:533-553` (subnet sed section in `build_setup_script_content`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for dual subnet patching**

```python
class TestSetupScriptDualSubnetPatch:
    def test_patches_env_production(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"), acme_email="admin@example.com",
            ),
            trusted_proxy_ips=[CADDY_NETWORK_SUBNET_PLACEHOLDER],
        )
        script = build_setup_script_content(config)
        # Must patch .env.production
        assert 'sed -i' in script
        assert CADDY_NETWORK_SUBNET_PLACEHOLDER in script
        assert '.env.production"' in script or ".env.production'" in script

    def test_patches_env_generated_with_existence_guard(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"), acme_email="admin@example.com",
            ),
            trusted_proxy_ips=[CADDY_NETWORK_SUBNET_PLACEHOLDER],
        )
        script = build_setup_script_content(config)
        # Must patch .env.production.generated with guard
        assert '.env.production.generated' in script
        # Guard: only patch if file exists
        assert 'if [ -f .env.production.generated ]' in script

    def test_no_subnet_patch_for_bundled_mode(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert CADDY_NETWORK_SUBNET_PLACEHOLDER not in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptDualSubnetPatch -v`
Expected: FAIL (the `.env.production.generated` patch and guard don't exist yet)

- [ ] **Step 3: Implement dual subnet patching**

Update the subnet patching section in `build_setup_script_content` to:

1. Keep the existing `sed` on `.env.production`.
2. Add a guarded `sed` on `.env.production.generated`:
```python
lines.extend([
    'if [ -f .env.production.generated ]; then',
    f'    sed -i "s|{CADDY_NETWORK_SUBNET_PLACEHOLDER}|$CADDY_SUBNET|" .env.production.generated',
    'fi',
])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptDualSubnetPatch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: patch caddy subnet in both .env.production and .env.production.generated"
```

---

### Task 5: Remove local bundle backups and guard local-deploy backups

**Files:**
- Modify: `cli/deploy_production.py:1361-1368` (`_backup_bundle_configs` — delete)
- Modify: `cli/deploy_production.py:1753-1810` (`deploy` — remove bundle backup call, guard local backup)
- Modify: `cli/deploy_production.py:102-111` (`BUNDLE_CONFIG_FILES` — remove or repurpose)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
class TestLocalBackupGuard:
    def test_no_backup_files_created_for_remote_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Remote bundle generation should NOT create .bak files in project root."""
        # Create existing config files that would be backed up
        (tmp_path / DEFAULT_ENV_FILE).write_text("old", encoding="utf-8")
        (tmp_path / DEFAULT_CADDYFILE).write_text("old", encoding="utf-8")
        commands = _stub_subprocess(monkeypatch)
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        deploy(config, tmp_path)
        # No .bak files in project root
        bak_files = list(tmp_path.glob("*.bak"))
        assert not bak_files, f"Unexpected .bak files in project root: {bak_files}"

    def test_no_backup_files_created_in_bundle_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Bundle dir should NOT have .bak files."""
        bundle_dir = tmp_path / DEFAULT_BUNDLE_DIR
        bundle_dir.mkdir(parents=True)
        (bundle_dir / DEFAULT_ENV_FILE).write_text("old", encoding="utf-8")
        commands = _stub_subprocess(monkeypatch)
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        deploy(config, tmp_path)
        bak_files = list(bundle_dir.glob("*.bak"))
        assert not bak_files, f"Unexpected .bak files in bundle dir: {bak_files}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestLocalBackupGuard -v`
Expected: FAIL

- [ ] **Step 3: Implement backup cleanup**

1. Delete `_backup_bundle_configs` function entirely.
2. Delete `BUNDLE_CONFIG_FILES` constant (only used by `_backup_bundle_configs`).
3. In `deploy()`, move the `backup_existing_configs` call inside the `if config.deployment_mode == DEPLOY_MODE_LOCAL:` block (around line 1766).
4. Remove the `_backup_bundle_configs` call from the remote bundle path (around line 1807).

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestLocalBackupGuard -v`
Expected: PASS

- [ ] **Step 5: Fix any existing tests that relied on backup behavior**

Tests like `test_backup_existing_configs_*` and any that called `_backup_bundle_configs` need updating. The `backup_existing_configs` tests themselves can stay (they test the function in isolation), but any deploy integration test that asserted `.bak` file creation for remote bundles needs updating.

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "fix: remove bundle backups and guard local backups for local-only deploys"
```

---

### Task 6: Update stale file cleanup for `.generated` suffix and transition

**Files:**
- Modify: `cli/deploy_production.py:1486-1555` (`write_bundle_files` stale file section)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for stale cleanup**

```python
class TestStaleGeneratedCleanup:
    def test_cleans_stale_generated_files_from_other_modes(self, tmp_path: Path) -> None:
        """Switching from bundled to no-caddy should clean bundled .generated files."""
        # Simulate leftover from previous bundled-caddy bundle generation
        (tmp_path / "docker-compose.image.yml.generated").write_text("old", encoding="utf-8")
        (tmp_path / "Caddyfile.production.generated").write_text("old", encoding="utf-8")
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        # Stale bundled files cleaned
        assert not (tmp_path / "docker-compose.image.yml.generated").exists()
        assert not (tmp_path / "Caddyfile.production.generated").exists()
        # New no-caddy file present
        assert (tmp_path / "docker-compose.image.nocaddy.yml.generated").exists()

    def test_cleans_old_unsuffixed_files_on_transition(self, tmp_path: Path) -> None:
        """First .generated bundle should clean up old un-suffixed files."""
        # Simulate leftover from pre-redesign bundle
        (tmp_path / ".env.production").write_text("old", encoding="utf-8")
        (tmp_path / "docker-compose.image.yml").write_text("old", encoding="utf-8")
        (tmp_path / "Caddyfile.production").write_text("old", encoding="utf-8")
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        write_bundle_files(config, tmp_path)
        # Old un-suffixed files cleaned
        assert not (tmp_path / ".env.production").exists()
        assert not (tmp_path / "docker-compose.image.yml").exists()
        assert not (tmp_path / "Caddyfile.production").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestStaleGeneratedCleanup -v`
Expected: FAIL

- [ ] **Step 3: Implement stale cleanup**

Update the stale file lists in `write_bundle_files` to include both `.generated` variants and old un-suffixed variants for all modes. For example, when generating external-caddy mode, the stale list includes:
- `docker-compose.image.yml.generated` (bundled mode leftover)
- `docker-compose.image.nocaddy.yml.generated` (no-caddy mode leftover)
- `Caddyfile.production.generated` (bundled mode leftover)
- `docker-compose.image.yml` (pre-redesign transition)
- `docker-compose.image.nocaddy.yml` (pre-redesign transition)
- `Caddyfile.production` (pre-redesign transition)
- `.env.production` (pre-redesign transition)
- All entries from the existing stale lists (which already handle mode-to-mode cleanup for un-suffixed files)

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestStaleGeneratedCleanup -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: clean up stale .generated and pre-redesign files in bundle generation"
```

---

### Task 7: Update README generation

**Files:**
- Modify: `cli/deploy_production.py:1382-1483` (`_build_remote_readme_content`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for updated README**

```python
class TestReadmeRedesign:
    def test_upgrade_no_longer_excludes_env_production(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False, caddy_public=False,
            caddy_mode=config.caddy_mode,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "except" not in readme.lower() or ".env.production" not in readme.split("except")[1]
        assert "copy all files" in readme.lower()

    def test_upgrade_mentions_env_preserved(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False, caddy_public=False,
            caddy_mode=config.caddy_mode,
        )
        readme = _build_remote_readme_content(config, commands)
        assert ".env.production" in readme
        assert "preserved" in readme.lower() or "automatically" in readme.lower()

    def test_upgrade_mentions_generated_reference(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False, caddy_public=False,
            caddy_mode=config.caddy_mode,
        )
        readme = _build_remote_readme_content(config, commands)
        assert ".env.production.generated" in readme

    def test_rollback_no_longer_references_env_bak(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False, caddy_public=False,
            caddy_mode=config.caddy_mode,
        )
        readme = _build_remote_readme_content(config, commands)
        assert ".env.production.bak" not in readme

    def test_no_longer_mentions_manual_env_backup(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False, caddy_public=False,
            caddy_mode=config.caddy_mode,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "backs up .env.production" not in readme.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestReadmeRedesign -v`
Expected: FAIL

- [ ] **Step 3: Implement README updates**

Rewrite the upgrade and rollback sections in `_build_remote_readme_content`:

**Upgrade section:**
- "Copy all files to the server" (no exclusion caveat)
- "Run `bash setup.sh`"
- Note that `.env.production` is preserved automatically
- Note `.env.production.generated` is available as a reference

**Rollback section:**
- Config files (compose, Caddyfile) have `.bak` backups
- `.env.production` is never overwritten, no rollback needed
- Restore config `.bak` files and restart with previous image

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestReadmeRedesign -v`
Expected: PASS

- [ ] **Step 5: Fix existing README tests**

Update `TestRemoteReadmeSetupScript` and other README tests that reference old wording.

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "docs: update remote README for .generated file pattern and simplified upgrade"
```

---

### Task 8: Update deployment architecture docs

**Files:**
- Modify: `docs/arch/deployment.md`

- [ ] **Step 1: Update deployment.md**

Update the following sections:

- **Deployment Workflows**: describe the `.generated` file pattern and setup.sh's role as the deployment orchestrator.
- **Caddy Reverse Proxy Modes**: note that mode switches are handled automatically by setup.sh via `.last-teardown`.
- Remove any references to "replace all files except `.env.production`".
- Note that `.env.production` is seeded on first install and preserved on upgrades.

- [ ] **Step 2: Commit**

```bash
git add docs/arch/deployment.md
git commit -m "docs: update deployment architecture for setup.sh redesign"
```

---

### Task 9: Full test suite verification

- [ ] **Step 1: Run full check**

Run: `just check`
Expected: All static checks and tests pass.

- [ ] **Step 2: Fix any remaining failures**

Address any test failures or static analysis issues.

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit -m "fix: address remaining issues from setup.sh redesign"
```
