# Remote Caddy Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate an idempotent `setup.sh` in remote deployment bundles so users can deploy with a single command, including shared Caddy bootstrapping for external Caddy mode.

**Architecture:** A new `build_setup_script_content()` function generates a bash script tailored to the deployment config (tarball/registry, none/bundled/external Caddy). The script handles image loading, Caddy bootstrapping, proxy subnet detection, container startup, and health checking. Bug fixes for proxy subnet, ADMIN_DISPLAY_NAME, --caddy-external validation, and content directory seeding are included.

**Tech Stack:** Python (cli/deploy_production.py), bash (generated setup.sh), pytest

**Spec:** `docs/specs/2026-03-14-remote-caddy-bootstrap-design.md`

---

## Chunk 1: Bug fixes and constants

### Task 1: Fix `docker-compose.yml` missing ADMIN_DISPLAY_NAME

**Files:**
- Modify: `docker-compose.yml:11-26`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_cli/test_deploy_production.py`, add a test that reads the base `docker-compose.yml` and checks for `ADMIN_DISPLAY_NAME`:

```python
class TestBaseComposeAdminDisplayName:
    def test_base_compose_includes_admin_display_name(self) -> None:
        compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
        content = compose_path.read_text(encoding="utf-8")
        assert "ADMIN_DISPLAY_NAME" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBaseComposeAdminDisplayName -v`
Expected: FAIL — `ADMIN_DISPLAY_NAME` not found in docker-compose.yml

- [ ] **Step 3: Add ADMIN_DISPLAY_NAME to docker-compose.yml**

In `docker-compose.yml`, add after the `ADMIN_PASSWORD` line (line 14):

```yaml
      - ADMIN_DISPLAY_NAME=${ADMIN_DISPLAY_NAME:-}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBaseComposeAdminDisplayName -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml tests/test_cli/test_deploy_production.py
git commit -m "fix: add ADMIN_DISPLAY_NAME to base docker-compose.yml"
```

### Task 2: Fix --caddy-external without --caddy-domain

**Files:**
- Modify: `cli/deploy_production.py:1768-1770`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

```python
def test_config_from_args_raises_on_caddy_external_without_domain() -> None:
    args = argparse.Namespace(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="password1234",
        admin_display_name="Admin",
        caddy_domain=None,
        caddy_email=None,
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        platform=None,
    )
    with pytest.raises(DeployError, match="--caddy-external requires --caddy-domain"):
        config_from_args(args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_config_from_args_raises_on_caddy_external_without_domain -v`
Expected: FAIL — no error is raised, falls through to CADDY_MODE_NONE

- [ ] **Step 3: Add validation in config_from_args**

In `cli/deploy_production.py`, before line 1768 (`else:`), add:

```python
    elif args.caddy_external:
        raise DeployError("--caddy-external requires --caddy-domain")
```

This changes the if/elif/else chain at lines 1754-1770 to: `if args.caddy_domain: ... elif args.caddy_external: raise ... else: ...`

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_config_from_args_raises_on_caddy_external_without_domain -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "fix: raise error when --caddy-external used without --caddy-domain"
```

### Task 3: Fix content directory seeding for local deployments

**Files:**
- Modify: `cli/deploy_production.py:819-856` (write_config_files)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

```python
def test_write_config_files_creates_content_directory(tmp_path: Path) -> None:
    config = _make_config()
    write_config_files(config, tmp_path)
    assert (tmp_path / "content").is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_write_config_files_creates_content_directory -v`
Expected: FAIL — `content/` directory not created

- [ ] **Step 3: Add content directory creation in write_config_files**

In `cli/deploy_production.py`, in `write_config_files()`, add after the `_write_env_file` call (line 821):

```python
    (project_dir / "content").mkdir(exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_write_config_files_creates_content_directory -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "fix: seed content directory for local deployments"
```

### Task 4: Fix proxy subnet for external Caddy mode — add placeholder constant

**Files:**
- Modify: `cli/deploy_production.py:56-59` (constants area)

- [ ] **Step 1: Add the placeholder constant**

After line 59 (`DEFAULT_SHARED_CADDYFILE = "Caddyfile"`), add:

```python
CADDY_NETWORK_SUBNET_PLACEHOLDER = "__CADDY_NETWORK_SUBNET__"
```

- [ ] **Step 2: Commit**

```bash
git add cli/deploy_production.py
git commit -m "refactor: add CADDY_NETWORK_SUBNET_PLACEHOLDER constant"
```

### Task 5: Fix proxy subnet in config_from_args

**Files:**
- Modify: `cli/deploy_production.py:1776-1778` (config_from_args proxy IP section)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Add import and write the failing test**

Add `CADDY_NETWORK_SUBNET_PLACEHOLDER` to the import block in `tests/test_cli/test_deploy_production.py` (lines 13-76).

```python
def test_config_from_args_external_caddy_uses_placeholder_not_compose_subnet() -> None:
    args = argparse.Namespace(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="password1234",
        admin_display_name="Admin",
        caddy_domain="blog.example.com",
        caddy_email="admin@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
        trusted_hosts="example.com",
        trusted_proxy_ips=None,
        host_port=8000,
        bind_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        platform=None,
    )
    config = config_from_args(args)
    assert CADDY_NETWORK_SUBNET_PLACEHOLDER in config.trusted_proxy_ips
    assert COMPOSE_SUBNET not in config.trusted_proxy_ips
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_config_from_args_external_caddy_uses_placeholder_not_compose_subnet -v`
Expected: FAIL — `COMPOSE_SUBNET` is present instead of placeholder

- [ ] **Step 3: Change config_from_args to use placeholder for external Caddy**

In `cli/deploy_production.py`, replace lines 1777-1778:

```python
    if caddy_config is not None and COMPOSE_SUBNET not in trusted_proxy_ips:
        trusted_proxy_ips.insert(0, COMPOSE_SUBNET)
```

with:

```python
    if caddy_mode == CADDY_MODE_EXTERNAL:
        if CADDY_NETWORK_SUBNET_PLACEHOLDER not in trusted_proxy_ips:
            trusted_proxy_ips.insert(0, CADDY_NETWORK_SUBNET_PLACEHOLDER)
    elif caddy_config is not None and COMPOSE_SUBNET not in trusted_proxy_ips:
        trusted_proxy_ips.insert(0, COMPOSE_SUBNET)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_config_from_args_external_caddy_uses_placeholder_not_compose_subnet -v`
Expected: PASS

- [ ] **Step 5: Verify existing proxy subnet tests still pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_config_from_args_auto_adds_caddy_proxy_subnet tests/test_cli/test_deploy_production.py::test_config_from_args_no_caddy_does_not_add_proxy_subnet -v`
Expected: PASS (these test bundled and no-Caddy modes which are unchanged)

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "fix: use subnet placeholder for external Caddy proxy IPs"
```

### Task 6: Fix proxy subnet in collect_config (interactive)

**Files:**
- Modify: `cli/deploy_production.py:1691-1699` (collect_config proxy section)

- [ ] **Step 1: Update collect_config proxy IP logic**

Replace lines 1691-1699:

```python
    if caddy_mode != CADDY_MODE_NONE:
        proxy_ips = [COMPOSE_SUBNET]
        print(f"Caddy proxy subnet ({COMPOSE_SUBNET}) auto-configured as a trusted proxy.")
        extra_proxy_ips = parse_csv_list(
            input("Additional trusted proxy IPs (comma-separated, optional): ").strip()
        )
        for ip in extra_proxy_ips:
            if ip not in proxy_ips:
                proxy_ips.append(ip)
```

with:

```python
    if caddy_mode == CADDY_MODE_EXTERNAL:
        proxy_ips = [CADDY_NETWORK_SUBNET_PLACEHOLDER]
        print("Caddy proxy subnet will be auto-detected from the Docker network at deploy time.")
        extra_proxy_ips = parse_csv_list(
            input("Additional trusted proxy IPs (comma-separated, optional): ").strip()
        )
        for ip in extra_proxy_ips:
            if ip not in proxy_ips:
                proxy_ips.append(ip)
    elif caddy_mode != CADDY_MODE_NONE:
        proxy_ips = [COMPOSE_SUBNET]
        print(f"Caddy proxy subnet ({COMPOSE_SUBNET}) auto-configured as a trusted proxy.")
        extra_proxy_ips = parse_csv_list(
            input("Additional trusted proxy IPs (comma-separated, optional): ").strip()
        )
        for ip in extra_proxy_ips:
            if ip not in proxy_ips:
                proxy_ips.append(ip)
```

- [ ] **Step 2: Run full test suite to check for regressions**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: all existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add cli/deploy_production.py
git commit -m "fix: use subnet placeholder in interactive mode for external Caddy"
```

## Chunk 2: Setup script generation

### Task 7: Add DEFAULT_SETUP_SCRIPT constant and update BUNDLE_CONFIG_FILES

**Files:**
- Modify: `cli/deploy_production.py:30-101`

- [ ] **Step 1: Add constant and update list**

After `DEFAULT_REMOTE_README = "DEPLOY-REMOTE.md"` (line 32), add:

```python
DEFAULT_SETUP_SCRIPT = "setup.sh"
```

Add `DEFAULT_SETUP_SCRIPT` to the `BUNDLE_CONFIG_FILES` list (after `DEFAULT_REMOTE_README` at line 100).

- [ ] **Step 2: Commit**

```bash
git add cli/deploy_production.py
git commit -m "refactor: add DEFAULT_SETUP_SCRIPT constant"
```

### Task 8: Implement build_setup_script_content for tarball + no Caddy

**Files:**
- Create test and function for the simplest case first
- Modify: `cli/deploy_production.py` (new function after `build_shared_caddy_compose_content`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

```python
class TestBuildSetupScript:
    def test_tarball_no_caddy_loads_image_and_starts(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert script.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in script
        # Preflight
        assert "docker info" in script
        # Load image
        assert "docker load -i" in script
        assert DEFAULT_IMAGE_TARBALL in script
        # Start
        assert "docker compose" in script
        assert "up -d" in script
        # Health check
        assert "(healthy)" in script
        # No Caddy bootstrapping
        assert "caddy reload" not in script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBuildSetupScript::test_tarball_no_caddy_loads_image_and_starts -v`
Expected: FAIL — `build_setup_script_content` doesn't exist

- [ ] **Step 3: Implement build_setup_script_content**

Add `build_setup_script_content` to `cli/deploy_production.py`. Place it after `build_shared_caddy_compose_content` (after line 365). The function builds the script as a list of strings and joins them.

```python
def build_setup_script_content(config: DeployConfig) -> str:
    """Build an idempotent setup script for remote deployment bundles."""
    compose_flags = _compose_filenames(
        config.deployment_mode,
        use_caddy=config.caddy_config is not None and config.caddy_mode != CADDY_MODE_EXTERNAL,
        caddy_public=config.caddy_public,
        caddy_mode=config.caddy_mode,
    )
    compose_cmd = "docker compose --env-file .env.production"
    if compose_flags:
        compose_cmd += " " + " ".join(f"-f {f}" for f in compose_flags)

    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by cli/deploy_production.py — safe to re-run (idempotent).",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        "",
        "# ── Preflight checks ────────────────────────────────────────────────",
        'if ! command -v docker &>/dev/null; then',
        '    echo "Error: Docker is not installed." >&2',
        "    exit 1",
        "fi",
        'if ! docker info &>/dev/null; then',
        '    echo "Error: Docker daemon is not running." >&2',
        "    exit 1",
        "fi",
        "",
    ]

    # Step 2: Load/pull image
    if config.deployment_mode == DEPLOY_MODE_TARBALL:
        lines.extend([
            "# ── Load image ───────────────────────────────────────────────────────",
            f'echo "Loading Docker image from {config.tarball_filename}..."',
            f"docker load -i {config.tarball_filename}",
            "",
        ])
    elif config.deployment_mode == DEPLOY_MODE_REGISTRY:
        lines.extend([
            "# ── Pull image ───────────────────────────────────────────────────────",
            f'echo "Pulling Docker image..."',
            f"{compose_cmd} pull",
            "",
        ])

    # Step 4: Start/restart AgBlogger
    lines.extend([
        "# ── Start services ───────────────────────────────────────────────────",
        'echo "Starting AgBlogger..."',
        f"{compose_cmd} up -d",
        "",
    ])

    # Step 5: Health check
    lines.extend([
        "# ── Health check ─────────────────────────────────────────────────────",
        'echo "Waiting for services to become healthy..."',
        "TIMEOUT=60",
        "INTERVAL=5",
        "ELAPSED=0",
        "while [ $ELAPSED -lt $TIMEOUT ]; do",
        "    sleep $INTERVAL",
        "    ELAPSED=$((ELAPSED + INTERVAL))",
        f'    STATUS=$({compose_cmd} ps --format "{{{{.Service}}}}: {{{{.Status}}}}" 2>/dev/null || echo "query failed")',
        '    echo "  [${ELAPSED}s] $STATUS"',
        '    if echo "$STATUS" | grep -q "agblogger:" && echo "$STATUS" | grep -q "(healthy)"; then',
        '        echo "All services healthy."',
        "        exit 0",
        "    fi",
        "done",
        'echo "Error: Health check timed out after ${TIMEOUT}s." >&2',
        f'echo "Check logs: {compose_cmd} logs" >&2',
        "exit 1",
    ])

    return "\n".join(lines) + "\n"
```

Also add `build_setup_script_content` to the test file's import block.

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBuildSetupScript::test_tarball_no_caddy_loads_image_and_starts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add build_setup_script_content for tarball + no-Caddy"
```

### Task 9: Add setup script tests for registry mode and bundled Caddy

**Files:**
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write tests for registry mode and bundled Caddy**

Add to `TestBuildSetupScript`:

```python
    def test_registry_no_caddy_pulls_image(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        script = build_setup_script_content(config)
        assert "pull" in script
        assert "docker load" not in script
        assert "caddy reload" not in script

    def test_tarball_bundled_caddy_has_no_caddy_bootstrap(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_BUNDLED,
            caddy_public=True,
        )
        script = build_setup_script_content(config)
        assert "docker load -i" in script
        # Bundled Caddy starts via compose, no separate bootstrap
        assert "/opt/caddy" not in script
        assert "caddy reload" not in script
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBuildSetupScript -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli/test_deploy_production.py
git commit -m "test: add setup script tests for registry and bundled Caddy modes"
```

### Task 10: Add external Caddy bootstrapping to setup script

**Files:**
- Modify: `cli/deploy_production.py` (build_setup_script_content)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

Add to `TestBuildSetupScript`:

```python
    def test_external_caddy_bootstraps_shared_caddy(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email="admin@example.com"),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"),
                acme_email="admin@example.com",
            ),
        )
        script = build_setup_script_content(config)
        # Directory creation
        assert "mkdir -p" in script
        assert "/opt/caddy/sites" in script
        # Shared Caddyfile heredoc
        assert "import /etc/caddy/sites/*.caddy" in script
        # Shared compose heredoc
        assert "image: caddy:2" in script
        # Network creation
        assert "docker network create" in script
        assert EXTERNAL_CADDY_NETWORK_NAME in script
        # Start shared Caddy
        assert "docker compose up -d" in script
        # Subnet detection
        assert "docker network inspect" in script
        assert CADDY_NETWORK_SUBNET_PLACEHOLDER in script
        # Site snippet
        assert "blog.example.com" in script
        assert "reverse_proxy agblogger:8000" in script
        # Caddy reload
        assert "caddy reload" in script

    def test_external_caddy_uses_custom_caddy_dir(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_REGISTRY,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/srv/caddy"),
                acme_email=None,
            ),
        )
        script = build_setup_script_content(config)
        assert "/srv/caddy" in script
        assert "/opt/caddy" not in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBuildSetupScript::test_external_caddy_bootstraps_shared_caddy tests/test_cli/test_deploy_production.py::TestBuildSetupScript::test_external_caddy_uses_custom_caddy_dir -v`
Expected: FAIL — external Caddy steps not present in script output

- [ ] **Step 3: Add external Caddy bootstrap block to build_setup_script_content**

In `build_setup_script_content`, insert between the image load/pull section and the "Start services" section a conditional block for `config.caddy_mode == CADDY_MODE_EXTERNAL`. This block should:

1. Create shared Caddy directory + sites/
2. Write Caddyfile if not exists (heredoc using `build_shared_caddyfile_content`)
3. Write docker-compose.yml if not exists (heredoc using `build_shared_caddy_compose_content`)
4. Create Docker network if not exists
5. Start shared Caddy if not running
6. Detect subnet and replace placeholder in .env.production
7. Write site snippet (heredoc using `build_caddy_site_snippet`)
8. Reload Caddy

Use the config's `shared_caddy_config.caddy_dir` for all paths and `shared_caddy_config.acme_email` for the Caddyfile content. Use `config.caddy_config.domain` for the site snippet.

```python
    # Step 3: External Caddy bootstrap (external mode only)
    if (
        config.caddy_mode == CADDY_MODE_EXTERNAL
        and config.caddy_config is not None
        and config.shared_caddy_config is not None
    ):
        caddy_dir = config.shared_caddy_config.caddy_dir
        domain = config.caddy_config.domain
        shared_caddyfile = build_shared_caddyfile_content(config.shared_caddy_config.acme_email)
        shared_compose = build_shared_caddy_compose_content()
        site_snippet = build_caddy_site_snippet(config.caddy_config)
        lines.extend([
            "# ── External Caddy bootstrap ─────────────────────────────────────────",
            f'echo "Setting up shared Caddy at {caddy_dir}..."',
            f"mkdir -p {caddy_dir}/sites",
            "",
            f"if [ ! -f {caddy_dir}/{DEFAULT_SHARED_CADDYFILE} ]; then",
            f'    cat > {caddy_dir}/{DEFAULT_SHARED_CADDYFILE} << \'CADDYFILE_EOF\'',
            shared_caddyfile.rstrip(),
            "CADDYFILE_EOF",
            "fi",
            "",
            f"if [ ! -f {caddy_dir}/{DEFAULT_SHARED_CADDY_COMPOSE_FILE} ]; then",
            f'    cat > {caddy_dir}/{DEFAULT_SHARED_CADDY_COMPOSE_FILE} << \'COMPOSE_EOF\'',
            shared_compose.rstrip(),
            "COMPOSE_EOF",
            "fi",
            "",
            f"# Create the {EXTERNAL_CADDY_NETWORK_NAME} Docker network if it does not exist",
            f'docker network create {EXTERNAL_CADDY_NETWORK_NAME} 2>/dev/null || true',
            "",
            "# Start shared Caddy if not running",
            f'if ! docker inspect --format "{{{{.State.Running}}}}" {SHARED_CADDY_CONTAINER_NAME} 2>/dev/null | grep -q "true"; then',
            f'    echo "Starting shared Caddy container..."',
            f"    docker compose -f {caddy_dir}/{DEFAULT_SHARED_CADDY_COMPOSE_FILE} up -d",
            "fi",
            "",
            "# Detect caddy network subnet and update trusted proxy IPs",
            f'CADDY_SUBNET=$(docker network inspect {EXTERNAL_CADDY_NETWORK_NAME}'
            ' --format \'{{(index .IPAM.Config 0).Subnet}}\')',
            f'echo "Detected Caddy network subnet: $CADDY_SUBNET"',
            f'sed -i "s|{CADDY_NETWORK_SUBNET_PLACEHOLDER}|$CADDY_SUBNET|" .env.production',
            "",
            f"# Write site snippet for {domain}",
            f"cat > {caddy_dir}/sites/{domain}.caddy << 'SNIPPET_EOF'",
            site_snippet.rstrip(),
            "SNIPPET_EOF",
            "",
            "# Reload Caddy to pick up the new site",
            f'echo "Reloading Caddy..."',
            f"docker exec {SHARED_CADDY_CONTAINER_NAME} caddy reload --config /etc/caddy/Caddyfile",
            "",
        ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestBuildSetupScript -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add external Caddy bootstrapping to setup script"
```

### Task 11: Write setup.sh in write_bundle_files

**Files:**
- Modify: `cli/deploy_production.py:1031-1093` (write_bundle_files)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

```python
class TestSetupScriptInBundle:
    def test_write_bundle_files_creates_executable_setup_script(self, tmp_path: Path) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        bundle_dir = tmp_path / "bundle"
        write_bundle_files(config, bundle_dir)
        setup_path = bundle_dir / DEFAULT_SETUP_SCRIPT
        assert setup_path.exists()
        assert setup_path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
        # Check executable permission
        assert setup_path.stat().st_mode & 0o111 != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptInBundle::test_write_bundle_files_creates_executable_setup_script -v`
Expected: FAIL — setup.sh not created

- [ ] **Step 3: Add setup.sh generation to write_bundle_files**

In `write_bundle_files()`, after the README write (around line 1092), add:

```python
    # Write idempotent setup script
    setup_path = bundle_dir / DEFAULT_SETUP_SCRIPT
    setup_path.write_text(build_setup_script_content(config), encoding="utf-8")
    try:
        setup_path.chmod(setup_path.stat().st_mode | 0o755)
    except OSError as exc:
        print(
            f"WARNING: Could not set executable permission on {DEFAULT_SETUP_SCRIPT}: {exc}",
            file=sys.stderr,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestSetupScriptInBundle -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: generate setup.sh in remote deployment bundles"
```

## Chunk 3: DEPLOY-REMOTE.md changes and final integration

### Task 12: Simplify DEPLOY-REMOTE.md content

**Files:**
- Modify: `cli/deploy_production.py:879-1028` (_build_remote_readme_content)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write the failing test**

```python
class TestRemoteReadmeSetupScript:
    def test_readme_references_setup_script(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "./setup.sh" in readme

    def test_readme_no_longer_has_manual_load_start_steps(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        # No numbered manual "Load the image" or "Start the services" steps
        assert "Load the image" not in readme
        assert "Start the services" not in readme
        assert "Pull the image" not in readme

    def test_readme_removes_shared_caddy_setup_section(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_mode=CADDY_MODE_EXTERNAL,
            shared_caddy_config=SharedCaddyConfig(
                caddy_dir=Path("/opt/caddy"), acme_email=None
            ),
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
            caddy_mode=CADDY_MODE_EXTERNAL,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "Shared Caddy Setup" not in readme
        assert "deployment script will bootstrap" not in readme

    def test_readme_includes_dns_notice_for_caddy(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
            caddy_config=CaddyConfig(domain="blog.example.com", email=None),
            caddy_mode=CADDY_MODE_BUNDLED,
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=True,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "DNS" in readme

    def test_readme_omits_dns_notice_for_no_caddy(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        assert "DNS" not in readme

    def test_readme_upgrade_references_setup_script(self) -> None:
        config = _make_config(
            deployment_mode=DEPLOY_MODE_TARBALL,
            image_ref="ghcr.io/example/agblogger:v1.0",
        )
        commands = build_lifecycle_commands(
            deployment_mode=config.deployment_mode,
            use_caddy=False,
            caddy_public=False,
            tarball_filename=config.tarball_filename,
        )
        readme = _build_remote_readme_content(config, commands)
        # Upgrade section should reference setup.sh
        upgrade_idx = readme.index("Upgrading")
        assert "./setup.sh" in readme[upgrade_idx:]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestRemoteReadmeSetupScript -v`
Expected: most FAIL — README still has manual steps

- [ ] **Step 3: Rewrite _build_remote_readme_content**

Replace the body of `_build_remote_readme_content` to:
1. Simplify getting-started to just "Run `./setup.sh`"
2. Add DNS prerequisite for Caddy-enabled configs
3. Remove "Shared Caddy Setup" section
4. Keep Management commands, Firewall, Data preservation, Upgrading, and Rollback sections
5. Simplify Upgrading to reference `./setup.sh`

```python
def _build_remote_readme_content(config: DeployConfig, commands: dict[str, str]) -> str:
    """Document how to use a generated remote deployment bundle."""
    lines = [
        "# Remote deployment bundle",
        "",
        "## Prerequisites",
        "",
        "- Docker Engine (20.10+)",
        "- Docker Compose V2 (`docker compose` subcommand)",
    ]
    if config.caddy_config is not None:
        lines.append(
            f"- DNS A/AAAA record pointing `{config.caddy_config.domain}`"
            " to this server (required for TLS certificate provisioning)"
        )
    if config.deployment_mode == DEPLOY_MODE_REGISTRY:
        lines.append(
            "- Container registry authentication (if using a private registry)"
        )
    lines.extend([
        "",
        "Blog content is stored in `./content/` (created automatically on first start).",
        "",
        "## Getting started",
        "",
        "```",
        "./setup.sh",
        "```",
        "",
        "## Management commands",
        "",
        f"- Stop: `{commands['stop']}`",
        f"- Status: `{commands['status']}`",
        f"- Logs: `{commands['logs']}`",
    ])
    if config.caddy_public:
        lines.extend([
            "",
            "## Firewall",
            "",
            "Caddy is configured to listen on ports 80 and 443 on all interfaces.",
            "Ensure your server firewall allows inbound traffic on these ports and",
            "blocks all other unnecessary ports. For example, with ufw:",
            "```",
            "ufw allow 80/tcp",
            "ufw allow 443/tcp",
            "ufw allow 22/tcp  # SSH",
            "ufw enable",
            "```",
        ])
    data_note = (
        "The database volume stores user accounts and settings alongside regenerable"
        " cache data. Both `./content/` and the `agblogger-db` Docker volume must be"
        " preserved during upgrades. Schema migrations run automatically on startup."
    )
    lines.extend([
        "",
        "## Upgrading",
        "",
        data_note,
        "",
        "To upgrade to a new version:",
        "",
        "1. Regenerate the bundle locally and replace all files in this directory"
        " (compose files and config may change between versions)."
        " Check the `VERSION` file to see what version generated the current bundle."
        " The `./content/` directory and `agblogger-db` Docker volume are not part"
        " of the bundle and will be preserved automatically.",
    ])
    if config.deployment_mode == DEPLOY_MODE_REGISTRY:
        lines.append(
            "2. Update the `AGBLOGGER_IMAGE` tag in `.env.production` if it changed."
        )
    elif config.deployment_mode == DEPLOY_MODE_TARBALL:
        lines.append(
            "2. If the image tag changed, update `AGBLOGGER_IMAGE` in `.env.production`."
        )
    lines.extend([
        "3. Run `./setup.sh` again.",
        "",
        "## Rollback",
        "",
        "If an upgrade causes problems, restore from the `.bak` backup files created",
        "during the previous deployment and restart with the previous image:",
        "```",
        "cp .env.production.bak .env.production",
        f"{commands['start']}",
        "```",
    ])
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::TestRemoteReadmeSetupScript -v`
Expected: PASS

- [ ] **Step 5: Update existing README tests that break with the new format**

The following existing tests reference the old README format and must be updated:

**`TestRemoteReadmeFormatting` (lines 1724-1758)**: Both methods assert manual step text that no longer exists.

- `test_registry_readme_uses_code_blocks`: Remove assertions for `"Pull the image:"`, `"Start the services:"`, `"Verify the services are running:"`. Keep `"```" in content` and `"## Management commands" in content`. Add `assert "./setup.sh" in content`.
- `test_tarball_readme_uses_code_blocks`: Remove assertion for `"Load the image:"`. Keep `"```" in content`. Add `assert "./setup.sh" in content`.

**`TestRemoteReadmeUpgradeGuidance` (lines 2210-2241)**:

- `test_registry_readme_includes_upgrade_section`: Keep `"## Upgrading"` assertion. Replace `assert "pull" in content.lower()` with `assert "./setup.sh" in content`.
- `test_tarball_readme_includes_upgrade_section`: Keep `"## Upgrading"` assertion. Replace `assert "load" in content.lower()` with `assert "./setup.sh" in content`.

**`test_remote_readme_external_caddy_mentions_shared_setup` (line 3192-3209)**: Replace body with:

```python
    content = _build_remote_readme_content(config, commands)
    assert "Shared Caddy Setup" not in content
    assert "deployment script will bootstrap" not in content
```

**Tests that should still pass without changes** (verify by running):
- `test_remote_readme_includes_logs_command` — asserts `"Logs:"` and `"logs -f"` which remain
- `TestRemoteReadmeFirewallGuidance` — asserts firewall content which remains
- `TestRemoteReadmePrerequisites` — asserts `"## Prerequisites"`, `"Docker"`, `"Docker Compose"` which remain
- `TestRemoteReadmeDataPreservation` — asserts data preservation text which remains in Upgrading section
- `TestRemoteReadmeRollback` — asserts rollback section which remains
- `TestRemoteReadmeBundleUpgradeNote` — asserts upgrade note text which remains

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: simplify DEPLOY-REMOTE.md to reference setup.sh"
```

### Task 13: Update docs/arch/deployment.md

**Files:**
- Modify: `docs/arch/deployment.md`

- [ ] **Step 1: Update the deployment architecture doc**

Add to the "Deployment Workflows" section:

```markdown
Remote deployment bundles include a `setup.sh` script that automates first-time setup and upgrades. The script handles image loading (tarball) or pulling (registry), external Caddy bootstrapping if configured, container startup, and health checking. It is idempotent — safe to run on both fresh installs and upgrades.
```

Update the "Code Entry Points" section to include `setup.sh`:

```markdown
- `cli/deploy_production.py` contains the deployment helper, configuration generation, and `setup.sh` script generation workflow.
```

- [ ] **Step 2: Commit**

```bash
git add docs/arch/deployment.md
git commit -m "docs: document setup script in deployment architecture"
```

### Task 14: Run full test suite

- [ ] **Step 1: Run all deployment tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: all PASS

- [ ] **Step 2: Run full check**

Run: `just check`
Expected: all PASS

- [ ] **Step 3: Commit any remaining fixes if needed**
