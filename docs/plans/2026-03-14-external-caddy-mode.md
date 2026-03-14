# External Caddy Mode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "external Caddy" deployment mode where AgBlogger joins a shared, host-level Caddy reverse proxy instead of bundling its own Caddy container — enabling multiple services on one server with distinct subdomains.

**Architecture:** The deployment script gains a third Caddy mode (`caddy_mode` enum: `bundled`, `external`, `none`) alongside the existing bundled/none binary. When `external` is chosen, the script: (1) bootstraps a shared Caddy compose stack at a configurable host directory (default `/opt/caddy/`) if it doesn't exist, (2) generates a site snippet for the AgBlogger domain and drops it into the shared `sites/` directory, (3) generates an AgBlogger compose file that joins the shared external `caddy` Docker network without bundling its own Caddy service, and (4) reloads Caddy via `docker exec`. On subsequent deploys of other services, step 1 detects the existing shared Caddy and skips bootstrapping.

**Tech Stack:** Python 3.14, pytest, Docker Compose, Caddy 2

---

## File Structure

### New files
- None — all changes are within existing files.

### Modified files
- `cli/deploy_production.py` — new constants, `CaddyMode` enum, `SharedCaddyConfig` dataclass, content builders for external-caddy compose/snippet, shared Caddy bootstrap logic, updated prompts and CLI args, updated validation/dry-run/summary/deploy/bundle flows.
- `tests/test_cli/test_deploy_production.py` — tests for all new functions and updated flows.
- `docs/arch/deployment.md` — document the external Caddy mode.

---

## Chunk 1: Data Model and Constants

### Task 1: Add CaddyMode enum and SharedCaddyConfig dataclass

**Files:**
- Modify: `cli/deploy_production.py:24-44` (constants section)
- Modify: `cli/deploy_production.py:94-131` (dataclass section)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests for CaddyMode and SharedCaddyConfig**

```python
# In tests/test_cli/test_deploy_production.py — add imports and tests

from cli.deploy_production import (
    # ... existing imports ...
    CADDY_MODE_BUNDLED,
    CADDY_MODE_EXTERNAL,
    CADDY_MODE_NONE,
    DEFAULT_SHARED_CADDY_DIR,
    EXTERNAL_CADDY_NETWORK_NAME,
    SharedCaddyConfig,
)


def test_shared_caddy_config_has_required_fields() -> None:
    config = SharedCaddyConfig(
        caddy_dir=Path("/opt/caddy"),
        acme_email="ops@example.com",
    )
    assert config.caddy_dir == Path("/opt/caddy")
    assert config.acme_email == "ops@example.com"


def test_shared_caddy_config_optional_email() -> None:
    config = SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None)
    assert config.acme_email is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_shared_caddy_config_has_required_fields -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement CaddyMode constants and SharedCaddyConfig**

Add to `cli/deploy_production.py` in the constants section (after line 44):

```python
CADDY_MODE_BUNDLED = "bundled"
CADDY_MODE_EXTERNAL = "external"
CADDY_MODE_NONE = "none"
CADDY_MODES = {CADDY_MODE_BUNDLED, CADDY_MODE_EXTERNAL, CADDY_MODE_NONE}
DEFAULT_SHARED_CADDY_DIR = "/opt/caddy"
EXTERNAL_CADDY_NETWORK_NAME = "caddy"
SHARED_CADDY_CONTAINER_NAME = "caddy"
DEFAULT_SHARED_CADDY_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_SHARED_CADDYFILE = "Caddyfile"
```

Add a new dataclass after `CaddyConfig`:

```python
@dataclass(frozen=True)
class SharedCaddyConfig:
    """Settings for a shared, host-level Caddy reverse proxy."""

    caddy_dir: Path
    acme_email: str | None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_shared_caddy_config_has_required_fields tests/test_cli/test_deploy_production.py::test_shared_caddy_config_optional_email -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add CaddyMode constants and SharedCaddyConfig dataclass"
```

### Task 2: Update DeployConfig to support external Caddy mode

**Files:**
- Modify: `cli/deploy_production.py:102-120` (DeployConfig)
- Test: `tests/test_cli/test_deploy_production.py`

The existing `DeployConfig` uses `caddy_config: CaddyConfig | None` and `caddy_public: bool` to represent the bundled/none binary. We need to add fields for the external Caddy mode without breaking the existing API.

- [ ] **Step 1: Write failing tests**

```python
def test_deploy_config_external_caddy_fields() -> None:
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["blog.example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        caddy_public=False,
        expose_docs=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=Path("/opt/caddy"), acme_email="ops@example.com"
        ),
    )
    assert config.caddy_mode == CADDY_MODE_EXTERNAL
    assert config.shared_caddy_config is not None
    assert config.shared_caddy_config.caddy_dir == Path("/opt/caddy")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_deploy_config_external_caddy_fields -v`
Expected: FAIL with TypeError (unexpected keyword argument)

- [ ] **Step 3: Add caddy_mode and shared_caddy_config fields to DeployConfig**

Add to `DeployConfig` (with defaults for backward compatibility):

```python
    caddy_mode: str = CADDY_MODE_NONE
    shared_caddy_config: SharedCaddyConfig | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_deploy_config_external_caddy_fields -v`
Expected: PASS

- [ ] **Step 5: Update `_make_config` test helper**

Add `caddy_mode` and `shared_caddy_config` parameters to `_make_config()`:

```python
def _make_config(
    *,
    caddy_config: CaddyConfig | None = None,
    caddy_public: bool = False,
    host_bind_ip: str = PUBLIC_BIND_IP,
    expose_docs: bool = False,
    deployment_mode: str = DEPLOY_MODE_LOCAL,
    image_ref: str | None = None,
    platform: str | None = None,
    caddy_mode: str = CADDY_MODE_NONE,
    shared_caddy_config: SharedCaddyConfig | None = None,
) -> DeployConfig:
    return DeployConfig(
        # ... existing fields ...
        caddy_mode=caddy_mode,
        shared_caddy_config=shared_caddy_config,
    )
```

- [ ] **Step 6: Run full test suite to check nothing is broken**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add caddy_mode and shared_caddy_config to DeployConfig"
```

### Task 3: Derive caddy_mode from existing config for backward compatibility

All existing code uses `config.caddy_config is not None` and `config.caddy_public` to decide between bundled/none. We need a helper that derives `caddy_mode` and add it to `DeployConfig` construction sites that don't explicitly set it. However, since we added defaults, existing call sites will just work — `caddy_mode` defaults to `CADDY_MODE_NONE` for no-caddy configs.

The better approach is to add a `caddy_mode` property or set it properly at construction. Since `DeployConfig` is frozen, we should derive it at construction time. Update the places that construct `DeployConfig` (there are three: `collect_config`, `config_from_args`, and `_make_config`).

- [ ] **Step 1: Write a failing test for caddy_mode derivation**

```python
def test_make_config_bundled_caddy_has_bundled_mode() -> None:
    config = _make_config(
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_mode=CADDY_MODE_BUNDLED,
    )
    assert config.caddy_mode == CADDY_MODE_BUNDLED


def test_make_config_no_caddy_has_none_mode() -> None:
    config = _make_config()
    assert config.caddy_mode == CADDY_MODE_NONE
```

- [ ] **Step 2: Run tests — these should pass immediately since we're using explicit args**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_make_config_bundled_caddy_has_bundled_mode tests/test_cli/test_deploy_production.py::test_make_config_no_caddy_has_none_mode -v`
Expected: PASS

- [ ] **Step 3: Update existing `collect_config` and `config_from_args`**

In `collect_config`, set `caddy_mode` based on the `use_caddy` decision:

```python
    caddy_mode = CADDY_MODE_BUNDLED if use_caddy else CADDY_MODE_NONE
```

And pass it into the `DeployConfig(...)` constructor.

Similarly in `config_from_args`:

```python
    caddy_mode = CADDY_MODE_BUNDLED if args.caddy_domain else CADDY_MODE_NONE
```

Note: External caddy prompts/args will be added in a later task. This step just ensures existing paths set `caddy_mode` correctly.

- [ ] **Step 4: Run full test suite**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: set caddy_mode in existing config construction paths"
```

---

## Chunk 2: Content Builders

### Task 4: Build site snippet for external Caddy

The site snippet is the per-domain Caddyfile block that goes into `sites/{domain}.caddy`. It's similar to what `build_caddyfile_content` produces but without the global email block (the shared Caddy owns the global config).

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
from cli.deploy_production import build_caddy_site_snippet


def test_build_caddy_site_snippet_contains_domain_block() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email="ops@example.com")
    content = build_caddy_site_snippet(caddy)
    assert "blog.example.com {" in content
    assert "reverse_proxy agblogger:8000" in content
    # No global email block — that belongs to the shared Caddyfile
    assert "email" not in content.split("{")[0]


def test_build_caddy_site_snippet_includes_request_body_limits() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddy_site_snippet(caddy)
    assert "@postUpload" in content
    assert "max_size 55MB" in content
    assert "@syncCommit" in content
    assert "max_size 100MB" in content


def test_build_caddy_site_snippet_includes_hsts() -> None:
    caddy = CaddyConfig(domain="blog.example.com", email=None)
    content = build_caddy_site_snippet(caddy)
    assert "Strict-Transport-Security" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_build_caddy_site_snippet_contains_domain_block -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `build_caddy_site_snippet`**

Add to `cli/deploy_production.py` after `build_caddyfile_content`:

```python
def build_caddy_site_snippet(config: CaddyConfig) -> str:
    """Build a Caddy site block for use as a snippet in a shared Caddy setup.

    Unlike build_caddyfile_content, this omits the global options block
    (email, etc.) since those belong to the shared root Caddyfile.
    """
    return (
        f"{config.domain} {{\n"
        "    @postUpload path /api/posts/upload\n"
        "    request_body @postUpload {\n"
        "        max_size 55MB\n"
        "    }\n\n"
        "    @postAssets path_regexp post_assets ^/api/posts/.+/assets$\n"
        "    request_body @postAssets {\n"
        "        max_size 55MB\n"
        "    }\n\n"
        "    @syncCommit path /api/sync/commit\n"
        "    request_body @syncCommit {\n"
        "        max_size 100MB\n"
        "    }\n\n"
        "    header {\n"
        '        Strict-Transport-Security "max-age=31536000"\n'
        "    }\n\n"
        "    reverse_proxy agblogger:8000\n\n"
        "    # Static asset caching\n"
        "    header /assets/* {\n"
        '        Cache-Control "public, max-age=31536000, immutable"\n'
        "    }\n\n"
        "    # HTML caching (short TTL for freshness)\n"
        "    @html path_regexp \\.html$\n"
        "    header @html {\n"
        '        Cache-Control "public, max-age=60"\n'
        "    }\n\n"
        "    # API caching\n"
        "    header /api/* {\n"
        '        Cache-Control "no-cache"\n'
        "    }\n\n"
        "    # Compression\n"
        "    encode gzip zstd\n"
        "}\n"
    )
```

Note: The site block content duplicates the body of `build_caddyfile_content`. Refactor both to share the common site block body via a private helper `_caddy_site_block_body(domain)` to avoid duplication.

```python
def _caddy_site_block_body(domain: str) -> str:
    """Return the inner body of a Caddy site block for AgBlogger."""
    return (
        f"{domain} {{\n"
        "    @postUpload path /api/posts/upload\n"
        "    request_body @postUpload {\n"
        "        max_size 55MB\n"
        "    }\n\n"
        "    @postAssets path_regexp post_assets ^/api/posts/.+/assets$\n"
        "    request_body @postAssets {\n"
        "        max_size 55MB\n"
        "    }\n\n"
        "    @syncCommit path /api/sync/commit\n"
        "    request_body @syncCommit {\n"
        "        max_size 100MB\n"
        "    }\n\n"
        "    header {\n"
        '        Strict-Transport-Security "max-age=31536000"\n'
        "    }\n\n"
        "    reverse_proxy agblogger:8000\n\n"
        "    # Static asset caching\n"
        "    header /assets/* {\n"
        '        Cache-Control "public, max-age=31536000, immutable"\n'
        "    }\n\n"
        "    # HTML caching (short TTL for freshness)\n"
        "    @html path_regexp \\.html$\n"
        "    header @html {\n"
        '        Cache-Control "public, max-age=60"\n'
        "    }\n\n"
        "    # API caching\n"
        "    header /api/* {\n"
        '        Cache-Control "no-cache"\n'
        "    }\n\n"
        "    # Compression\n"
        "    encode gzip zstd\n"
        "}\n"
    )


def build_caddyfile_content(config: CaddyConfig) -> str:
    """Build Caddyfile content for HTTPS reverse proxy with request body limits."""
    global_block = f"{{\n    email {config.email}\n}}\n\n" if config.email else ""
    return f"{global_block}{_caddy_site_block_body(config.domain)}"


def build_caddy_site_snippet(config: CaddyConfig) -> str:
    """Build a Caddy site block snippet for a shared Caddy setup."""
    return _caddy_site_block_body(config.domain)
```

- [ ] **Step 4: Run tests (both new and existing Caddyfile tests)**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "caddy" -v`
Expected: All PASS (existing `build_caddyfile_content` tests still pass; new snippet tests pass)

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add build_caddy_site_snippet with shared site block helper"
```

### Task 5: Build shared Caddy root Caddyfile content

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
from cli.deploy_production import build_shared_caddyfile_content


def test_build_shared_caddyfile_with_email() -> None:
    content = build_shared_caddyfile_content(acme_email="ops@example.com")
    assert "email ops@example.com" in content
    assert "import /etc/caddy/sites/*.caddy" in content


def test_build_shared_caddyfile_without_email() -> None:
    content = build_shared_caddyfile_content(acme_email=None)
    assert "email" not in content
    assert "import /etc/caddy/sites/*.caddy" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL with ImportError

- [ ] **Step 3: Implement `build_shared_caddyfile_content`**

```python
def build_shared_caddyfile_content(acme_email: str | None) -> str:
    """Build the root Caddyfile for a shared Caddy instance."""
    global_block = f"{{\n    email {acme_email}\n}}\n\n" if acme_email else ""
    return f"{global_block}import /etc/caddy/sites/*.caddy\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add build_shared_caddyfile_content for shared Caddy root config"
```

### Task 6: Build shared Caddy compose file content

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
from cli.deploy_production import build_shared_caddy_compose_content, EXTERNAL_CADDY_NETWORK_NAME


def test_build_shared_caddy_compose_has_caddy_service() -> None:
    content = build_shared_caddy_compose_content()
    assert "caddy:" in content
    assert "image: caddy:2" in content
    assert '"80:80"' in content
    assert '"443:443"' in content


def test_build_shared_caddy_compose_has_sites_volume() -> None:
    content = build_shared_caddy_compose_content()
    assert "./sites:/etc/caddy/sites:ro" in content
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in content


def test_build_shared_caddy_compose_defines_external_network() -> None:
    content = build_shared_caddy_compose_content()
    assert f"name: {EXTERNAL_CADDY_NETWORK_NAME}" in content


def test_build_shared_caddy_compose_has_restart_policy() -> None:
    content = build_shared_caddy_compose_content()
    assert "restart: unless-stopped" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL with ImportError

- [ ] **Step 3: Implement `build_shared_caddy_compose_content`**

```python
def build_shared_caddy_compose_content() -> str:
    """Build the compose file for a shared Caddy reverse proxy."""
    return (
        "services:\n"
        "  caddy:\n"
        "    image: caddy:2\n"
        "    container_name: caddy\n"
        "    ports:\n"
        '      - "80:80"\n'
        '      - "443:443"\n'
        "    volumes:\n"
        "      - ./Caddyfile:/etc/caddy/Caddyfile:ro\n"
        "      - ./sites:/etc/caddy/sites:ro\n"
        "      - caddy-data:/data\n"
        "      - caddy-config:/config\n"
        "    restart: unless-stopped\n"
        "    networks:\n"
        f"      - {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "\n"
        "volumes:\n"
        "  caddy-data:\n"
        "  caddy-config:\n"
        "\n"
        "networks:\n"
        f"  {EXTERNAL_CADDY_NETWORK_NAME}:\n"
        f"    name: {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "    driver: bridge\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add build_shared_caddy_compose_content"
```

### Task 7: Build external-caddy AgBlogger compose file content

This is the compose file for AgBlogger when using external Caddy — no bundled Caddy service, joins the external `caddy` network. Two variants: local (with `build: .`) and image-based (for remote deployment).

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
from cli.deploy_production import (
    build_external_caddy_compose_content,
    build_image_external_caddy_compose_content,
    EXTERNAL_CADDY_NETWORK_NAME,
)


def test_build_external_caddy_compose_joins_external_network() -> None:
    content = build_external_caddy_compose_content()
    assert f"name: {EXTERNAL_CADDY_NETWORK_NAME}" in content
    assert "external: true" in content
    assert "caddy:" not in content.split("networks:")[0]  # No caddy service


def test_build_external_caddy_compose_exposes_port_internally() -> None:
    content = build_external_caddy_compose_content()
    assert 'expose:' in content
    assert '"8000"' in content
    # No host port binding
    assert "ports:" not in content


def test_build_external_caddy_compose_has_build_directive() -> None:
    content = build_external_caddy_compose_content()
    assert "build: ." in content


def test_build_image_external_caddy_compose_uses_image_ref() -> None:
    content = build_image_external_caddy_compose_content()
    assert "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}" in content
    assert "build:" not in content


def test_build_image_external_caddy_compose_joins_external_network() -> None:
    content = build_image_external_caddy_compose_content()
    assert f"name: {EXTERNAL_CADDY_NETWORK_NAME}" in content
    assert "external: true" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL with ImportError

- [ ] **Step 3: Implement both compose builders**

```python
def _external_caddy_network_block() -> str:
    """Return the network YAML block for joining an external Caddy network."""
    return (
        "networks:\n"
        f"  {EXTERNAL_CADDY_NETWORK_NAME}:\n"
        f"    name: {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "    external: true\n"
    )


def build_external_caddy_compose_content() -> str:
    """Build compose file for AgBlogger behind an external shared Caddy."""
    return (
        "services:\n"
        "  agblogger:\n"
        "    build: .\n"
        f"    image: {LOCAL_IMAGE_TAG}\n"
        "    user: root\n"
        "    expose:\n"
        '      - "8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + "    restart: unless-stopped\n"
        "    healthcheck:\n"
        '      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]\n'
        "      interval: 30s\n"
        "      timeout: 5s\n"
        "      start_period: 10s\n"
        "      retries: 3\n"
        f"    networks:\n"
        f"      - {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "\n"
        "volumes:\n"
        "  agblogger-db:\n"
        "\n"
        + _external_caddy_network_block()
    )


def build_image_external_caddy_compose_content() -> str:
    """Build image-only compose file for AgBlogger behind an external shared Caddy."""
    return (
        "services:\n"
        "  agblogger:\n"
        '    image: "${AGBLOGGER_IMAGE?Set AGBLOGGER_IMAGE}"\n'
        "    user: root\n"
        "    expose:\n"
        '      - "8000"\n'
        "    volumes:\n"
        "      - ./content:/data/content\n"
        "      - agblogger-db:/data/db\n"
        + _agblogger_env_section()
        + "    restart: unless-stopped\n"
        "    healthcheck:\n"
        '      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]\n'
        "      interval: 30s\n"
        "      timeout: 5s\n"
        "      start_period: 10s\n"
        "      retries: 3\n"
        f"    networks:\n"
        f"      - {EXTERNAL_CADDY_NETWORK_NAME}\n"
        "\n"
        "volumes:\n"
        "  agblogger-db:\n"
        "\n"
        + _external_caddy_network_block()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add compose builders for external Caddy mode"
```

---

## Chunk 3: Shared Caddy Bootstrap and Reload

### Task 8: Bootstrap shared Caddy infrastructure

This function creates the shared Caddy directory, writes the root Caddyfile and compose file, creates the `sites/` directory, and starts the Caddy container — but only if it doesn't already exist.

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
from cli.deploy_production import (
    ensure_shared_caddy,
    DEFAULT_SHARED_CADDY_DIR,
    SHARED_CADDY_CONTAINER_NAME,
)


def test_ensure_shared_caddy_creates_directory_structure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bootstrap creates caddy dir, sites dir, Caddyfile, and compose file."""
    commands = _stub_subprocess(monkeypatch)
    # Stub docker inspect to indicate container does not exist (non-zero exit)
    _stub_docker_inspect_missing(monkeypatch)

    caddy_dir = tmp_path / "caddy"
    ensure_shared_caddy(
        caddy_dir=caddy_dir,
        acme_email="ops@example.com",
    )

    assert (caddy_dir / "sites").is_dir()
    assert (caddy_dir / "Caddyfile").exists()
    assert "import /etc/caddy/sites/*.caddy" in (caddy_dir / "Caddyfile").read_text("utf-8")
    assert "email ops@example.com" in (caddy_dir / "Caddyfile").read_text("utf-8")
    assert (caddy_dir / "docker-compose.yml").exists()


def test_ensure_shared_caddy_starts_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _stub_subprocess(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)

    caddy_dir = tmp_path / "caddy"
    ensure_shared_caddy(caddy_dir=caddy_dir, acme_email=None)

    # Should have run docker compose up -d in the caddy dir
    compose_up_calls = [
        (cmd, cwd) for cmd, cwd, _ in commands
        if "compose" in cmd and "up" in cmd
    ]
    assert len(compose_up_calls) == 1
    assert compose_up_calls[0][1] == caddy_dir


def test_ensure_shared_caddy_skips_if_already_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = _stub_subprocess(monkeypatch)
    _stub_docker_inspect_running(monkeypatch)

    caddy_dir = tmp_path / "caddy"
    caddy_dir.mkdir()
    (caddy_dir / "sites").mkdir()
    (caddy_dir / "Caddyfile").write_text("existing", encoding="utf-8")
    (caddy_dir / "docker-compose.yml").write_text("existing", encoding="utf-8")

    ensure_shared_caddy(caddy_dir=caddy_dir, acme_email=None)

    # Should NOT have run compose up since container is already running
    compose_up_calls = [
        cmd for cmd, _, _ in commands
        if "up" in cmd
    ]
    assert len(compose_up_calls) == 0
```

Note: We'll need test helpers `_stub_docker_inspect_missing` and `_stub_docker_inspect_running` that patch `subprocess.run` to simulate the `docker inspect` command returning non-zero (container missing) or zero (container running).

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL with ImportError

- [ ] **Step 3: Implement `ensure_shared_caddy`**

```python
def _is_container_running(container_name: str) -> bool:
    """Check if a Docker container exists and is running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and "true" in result.stdout.strip().lower()


def ensure_shared_caddy(caddy_dir: Path, acme_email: str | None) -> None:
    """Bootstrap or verify a shared Caddy reverse proxy at the given directory.

    If the shared Caddy container is already running, this is a no-op.
    Otherwise, creates the directory structure, writes config files, and
    starts the Caddy container via docker compose.
    """
    caddy_path = caddy_dir

    if _is_container_running(SHARED_CADDY_CONTAINER_NAME):
        print(f"Shared Caddy container '{SHARED_CADDY_CONTAINER_NAME}' is already running.")
        return

    print(f"Bootstrapping shared Caddy at {caddy_path}...")
    caddy_path.mkdir(parents=True, exist_ok=True)
    (caddy_path / "sites").mkdir(exist_ok=True)

    caddyfile_path = caddy_path / DEFAULT_SHARED_CADDYFILE
    if not caddyfile_path.exists():
        caddyfile_path.write_text(
            build_shared_caddyfile_content(acme_email), encoding="utf-8"
        )

    compose_path = caddy_path / DEFAULT_SHARED_CADDY_COMPOSE_FILE
    if not compose_path.exists():
        compose_path.write_text(
            build_shared_caddy_compose_content(), encoding="utf-8"
        )

    print("Starting shared Caddy container...")
    _run_command(
        ["docker", "compose", "up", "-d"],
        caddy_path,
    )
    print("Shared Caddy container started.")
```

- [ ] **Step 4: Implement test helpers and run tests**

```python
def _stub_docker_inspect_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _is_container_running to return False."""
    monkeypatch.setattr(
        "cli.deploy_production._is_container_running", lambda _name: False
    )


def _stub_docker_inspect_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub _is_container_running to return True."""
    monkeypatch.setattr(
        "cli.deploy_production._is_container_running", lambda _name: True
    )
```

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "ensure_shared_caddy" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add ensure_shared_caddy bootstrap function"
```

### Task 9: Write site snippet and reload Caddy

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
from cli.deploy_production import write_caddy_site_snippet, reload_shared_caddy


def test_write_caddy_site_snippet_creates_file(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    caddy_config = CaddyConfig(domain="blog.example.com", email=None)

    write_caddy_site_snippet(caddy_config, tmp_path)

    snippet_path = sites_dir / "blog.example.com.caddy"
    assert snippet_path.exists()
    content = snippet_path.read_text(encoding="utf-8")
    assert "blog.example.com {" in content
    assert "reverse_proxy agblogger:8000" in content


def test_write_caddy_site_snippet_overwrites_existing(tmp_path: Path) -> None:
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    snippet_path = sites_dir / "blog.example.com.caddy"
    snippet_path.write_text("old content", encoding="utf-8")

    caddy_config = CaddyConfig(domain="blog.example.com", email=None)
    write_caddy_site_snippet(caddy_config, tmp_path)

    assert "old content" not in snippet_path.read_text(encoding="utf-8")
    assert "blog.example.com {" in snippet_path.read_text(encoding="utf-8")


def test_reload_shared_caddy_runs_docker_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)

    reload_shared_caddy()

    assert calls == [
        ["docker", "exec", SHARED_CADDY_CONTAINER_NAME, "caddy", "reload",
         "--config", "/etc/caddy/Caddyfile"],
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL with ImportError

- [ ] **Step 3: Implement `write_caddy_site_snippet` and `reload_shared_caddy`**

```python
def write_caddy_site_snippet(caddy_config: CaddyConfig, caddy_dir: Path) -> None:
    """Write a Caddy site snippet for AgBlogger into the shared sites directory."""
    sites_dir = caddy_dir / "sites"
    snippet_path = sites_dir / f"{caddy_config.domain}.caddy"
    snippet_path.write_text(build_caddy_site_snippet(caddy_config), encoding="utf-8")
    print(f"Wrote Caddy site snippet: {snippet_path}")


def reload_shared_caddy() -> None:
    """Reload the shared Caddy container to pick up config changes."""
    print("Reloading shared Caddy configuration...")
    subprocess.run(
        [
            "docker", "exec", SHARED_CADDY_CONTAINER_NAME,
            "caddy", "reload", "--config", "/etc/caddy/Caddyfile",
        ],
        check=True,
        timeout=30,
    )
    print("Shared Caddy reloaded.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "site_snippet or reload_shared" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add write_caddy_site_snippet and reload_shared_caddy"
```

---

## Chunk 4: Validation, Compose Helpers, Lifecycle Commands

### Task 10: Update validation for external Caddy mode

**Files:**
- Modify: `cli/deploy_production.py` (`_validate_config`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
def test_validate_config_external_caddy_requires_caddy_config() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=None,
    )
    with pytest.raises(DeployError, match="requires a domain"):
        _validate_config(config)


def test_validate_config_external_caddy_requires_shared_caddy_config() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=None,
    )
    with pytest.raises(DeployError, match="shared Caddy configuration"):
        _validate_config(config)


def test_validate_config_external_caddy_valid() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
    )
    # Should not raise
    _validate_config(config)


def test_validate_config_rejects_invalid_caddy_mode() -> None:
    config = _make_config(caddy_mode="invalid")
    with pytest.raises(DeployError, match="caddy_mode"):
        _validate_config(config)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL (validation doesn't check these yet)

- [ ] **Step 3: Add validation rules to `_validate_config`**

Add after the existing `caddy_public` validation (around line 540):

```python
    if config.caddy_mode not in CADDY_MODES:
        raise DeployError(
            f"caddy_mode must be one of: {', '.join(sorted(CADDY_MODES))}"
        )
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        if config.caddy_config is None:
            raise DeployError("External Caddy mode requires a domain (caddy_config)")
        if config.shared_caddy_config is None:
            raise DeployError(
                "External Caddy mode requires shared Caddy configuration"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "validate_config" -v`
Expected: PASS (including all existing validation tests)

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add validation rules for external Caddy mode"
```

### Task 11: Update compose filename helpers and lifecycle commands

**Files:**
- Modify: `cli/deploy_production.py` (`_compose_filenames`, `build_lifecycle_commands`)
- Test: `tests/test_cli/test_deploy_production.py`

The compose helpers currently use `use_caddy: bool` and `caddy_public: bool`. We need to extend them to handle `caddy_mode`. The cleanest approach: add a `caddy_mode: str` parameter and derive the old booleans internally, or switch the logic to use `caddy_mode` directly.

Since `_compose_filenames` and `_compose_base_command` and `build_lifecycle_commands` are all used by both internal code and tests, we need to update their signatures. We'll add `caddy_mode` as an optional parameter with backward compatibility.

- [ ] **Step 1: Write failing tests**

```python
DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE = "docker-compose.external-caddy.yml"
DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE = "docker-compose.image.external-caddy.yml"

# Import these from the module once implemented
from cli.deploy_production import (
    DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE,
    DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE,
)


def test_build_lifecycle_commands_for_external_caddy_local() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_LOCAL,
        use_caddy=False,
        caddy_public=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
    )
    assert DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE in commands["start"]


def test_build_lifecycle_commands_for_external_caddy_registry() -> None:
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        use_caddy=False,
        caddy_public=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
    )
    assert DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE in commands["start"]
    assert "pull" in commands
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL

- [ ] **Step 3: Add constants and update `_compose_filenames` and `build_lifecycle_commands`**

Add constants:

```python
DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE = "docker-compose.external-caddy.yml"
DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE = "docker-compose.image.external-caddy.yml"
```

Update `_compose_filenames` signature to accept optional `caddy_mode`:

```python
def _compose_filenames(
    deployment_mode: str,
    use_caddy: bool,
    caddy_public: bool,
    caddy_mode: str = CADDY_MODE_NONE,
) -> list[str]:
    if caddy_mode == CADDY_MODE_EXTERNAL:
        if deployment_mode == DEPLOY_MODE_LOCAL:
            return [DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE]
        return [DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE]
    # ... existing logic unchanged ...
```

Update `_compose_base_command` and `build_lifecycle_commands` to pass through `caddy_mode`.

- [ ] **Step 4: Run tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "lifecycle" -v`
Expected: PASS (both new and existing)

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: extend compose helpers for external Caddy mode"
```

### Task 12: Add GENERATED_CONFIG_FILES and BUNDLE_CONFIG_FILES entries

The `GENERATED_CONFIG_FILES` and `BUNDLE_CONFIG_FILES` lists control backup and stale-file cleanup. Add the new compose file names.

**Files:**
- Modify: `cli/deploy_production.py`
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Add new filenames to the config file lists**

Locate `GENERATED_CONFIG_FILES` and `BUNDLE_CONFIG_FILES` in `deploy_production.py` and add the new compose filenames to each.

- [ ] **Step 2: Run existing backup tests to verify nothing is broken**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "backup" -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add cli/deploy_production.py
git commit -m "feat: register external Caddy compose files in config file lists"
```

---

## Chunk 5: Deploy Orchestration

### Task 13: Update `write_config_files` for external Caddy mode (local deploy)

**Files:**
- Modify: `cli/deploy_production.py` (`write_config_files`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
def test_write_config_files_external_caddy(tmp_path: Path) -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=tmp_path / "caddy", acme_email=None),
    )
    write_config_files(config, tmp_path)

    assert (tmp_path / ".env.production").exists()
    assert (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).exists()
    # Should NOT have bundled Caddy files
    assert not (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / DEFAULT_NO_CADDY_COMPOSE_FILE).exists()
    assert not (tmp_path / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL

- [ ] **Step 3: Update `write_config_files` to handle external Caddy**

Add a branch for `caddy_mode == CADDY_MODE_EXTERNAL` and update existing branches to clean up external Caddy files when switching modes:

```python
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        compose_path = project_dir / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE
        compose_path.write_text(
            build_external_caddy_compose_content(), encoding="utf-8"
        )
        stale_files.extend([
            DEFAULT_NO_CADDY_COMPOSE_FILE,
            DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
            "Caddyfile.production",
        ])
    elif config.caddy_config is not None:
        # ... existing bundled Caddy logic ...
        # ADD to existing stale_files lists:
        stale_files.append(DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE)
    else:
        # ... existing no-caddy logic ...
        # ADD to existing stale_files lists:
        stale_files.append(DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE)
```

**Important:** Also update existing mode branches to clean up `DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE` so switching from external to bundled/none mode removes the stale file.

- [ ] **Step 4: Run tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "write_config" -v`
Expected: PASS (new and existing)

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: update write_config_files for external Caddy mode"
```

### Task 14: Update `write_bundle_files` for external Caddy mode (remote deploy)

**Files:**
- Modify: `cli/deploy_production.py` (`write_bundle_files`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
def test_write_bundle_files_external_caddy(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.0",
    )
    write_bundle_files(config, bundle_dir)

    assert (bundle_dir / DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE).exists()
    assert not (bundle_dir / DEFAULT_IMAGE_COMPOSE_FILE).exists()
    assert not (bundle_dir / DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE).exists()
    assert not (bundle_dir / DEFAULT_CADDYFILE).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL

- [ ] **Step 3: Update `write_bundle_files` to handle external Caddy**

Add a branch for `caddy_mode == CADDY_MODE_EXTERNAL` and update existing branches to clean up external Caddy files:

```python
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        (bundle_dir / DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE).write_text(
            build_image_external_caddy_compose_content(), encoding="utf-8"
        )
        stale_files.extend([
            DEFAULT_CADDYFILE,
            DEFAULT_CADDY_PUBLIC_COMPOSE_FILE,
            DEFAULT_IMAGE_COMPOSE_FILE,
            DEFAULT_IMAGE_NO_CADDY_COMPOSE_FILE,
        ])
    elif config.caddy_config is not None:
        # ... existing bundled Caddy logic ...
        # ADD: stale_files.append(DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE)
    else:
        # ... existing no-caddy logic ...
        # ADD: DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE to the stale_files.extend list
```

**Important:** Also update existing mode branches to clean up `DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE` so switching modes removes stale files.

- [ ] **Step 4: Run tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "bundle" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: update write_bundle_files for external Caddy mode"
```

### Task 15: Update `deploy` to bootstrap shared Caddy and write snippet

**Files:**
- Modify: `cli/deploy_production.py` (`deploy`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
def test_deploy_external_caddy_local_bootstraps_and_writes_snippet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)

    caddy_dir = tmp_path / "shared-caddy"
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=caddy_dir, acme_email="ops@example.com"
        ),
    )

    # Stub reload_shared_caddy so it doesn't actually exec
    monkeypatch.setattr("cli.deploy_production.reload_shared_caddy", lambda: None)

    result = deploy(config=config, project_dir=tmp_path)

    # Shared Caddy bootstrapped
    assert (caddy_dir / "sites").is_dir()
    assert (caddy_dir / "Caddyfile").exists()

    # Site snippet written
    assert (caddy_dir / "sites" / "blog.example.com.caddy").exists()

    # AgBlogger compose file written
    assert (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).exists()

    # Lifecycle commands use external caddy compose
    assert DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE in result.commands["start"]
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL

- [ ] **Step 3: Update `deploy` function**

In the `deploy` function, after `write_config_files` (for local mode) or `write_bundle_files` (for remote mode), add external Caddy handling:

```python
    # After write_config_files or write_bundle_files:
    if config.caddy_mode == CADDY_MODE_EXTERNAL and config.shared_caddy_config is not None:
        ensure_shared_caddy(
            caddy_dir=config.shared_caddy_config.caddy_dir,
            acme_email=config.shared_caddy_config.acme_email,
        )
        if config.caddy_config is not None:
            write_caddy_site_snippet(
                config.caddy_config,
                config.shared_caddy_config.caddy_dir,
            )
            reload_shared_caddy()
```

**Important:** Also update ALL `build_lifecycle_commands` call sites in `deploy()` to pass `caddy_mode=config.caddy_mode`. There are two call sites:
1. The `DeployResult` return for local mode (around line 1007): add `caddy_mode=config.caddy_mode`
2. `_remote_bundle_commands` (line 650): update to pass `caddy_mode` through to `build_lifecycle_commands`

Similarly, update the `dry_run` function's `build_lifecycle_commands` call (around line 1102) to pass `caddy_mode`.

- [ ] **Step 4: Run tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "deploy" -v`
Expected: PASS (all deploy tests including existing ones)

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: integrate external Caddy bootstrap into deploy flow"
```

---

## Chunk 6: Prompts, CLI Args, Dry Run, Summary

### Task 16: Update interactive prompts (`collect_config`)

**Files:**
- Modify: `cli/deploy_production.py` (`collect_config`)
- Test: `tests/test_cli/test_deploy_production.py`

The Caddy prompt currently asks a binary yes/no. We need to replace it with a three-way choice: bundled, external, or none.

- [ ] **Step 1: Write failing tests for the new prompt flow**

Since `collect_config` is interactive and hard to unit test, we'll test the non-interactive path (`config_from_args`) instead. The interactive prompts mirror the same logic.

```python
def test_config_from_args_external_caddy() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email="ops@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir="/opt/caddy",
        shared_caddy_email=None,  # reuse per-service email
        trusted_hosts="blog.example.com",
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

    assert config.caddy_mode == CADDY_MODE_EXTERNAL
    assert config.caddy_config is not None
    assert config.caddy_config.domain == "blog.example.com"
    assert config.shared_caddy_config is not None
    assert config.shared_caddy_config.caddy_dir == Path("/opt/caddy")
    # Reuses per-service email when shared_caddy_email is None
    assert config.shared_caddy_config.acme_email == "ops@example.com"


def test_config_from_args_external_caddy_with_explicit_shared_email() -> None:
    args = argparse.Namespace(
        secret_key="s" * 64,
        admin_username="admin",
        admin_password="strong-password!",
        admin_display_name=None,
        caddy_domain="blog.example.com",
        caddy_email="site@example.com",
        caddy_public=False,
        caddy_external=True,
        shared_caddy_dir="/srv/caddy",
        shared_caddy_email="global@example.com",
        trusted_hosts="blog.example.com",
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

    assert config.shared_caddy_config is not None
    assert config.shared_caddy_config.caddy_dir == Path("/srv/caddy")
    assert config.shared_caddy_config.acme_email == "global@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL (args missing `caddy_external` etc.)

- [ ] **Step 3: Update `config_from_args`**

```python
def config_from_args(args: argparse.Namespace) -> DeployConfig:
    # ... existing setup ...

    caddy_config: CaddyConfig | None = None
    caddy_public = False
    caddy_mode = CADDY_MODE_NONE
    shared_caddy_config: SharedCaddyConfig | None = None

    if args.caddy_domain:
        caddy_config = CaddyConfig(domain=args.caddy_domain, email=args.caddy_email)
        if args.caddy_external:
            caddy_mode = CADDY_MODE_EXTERNAL
            shared_email = args.shared_caddy_email or args.caddy_email
            shared_caddy_config = SharedCaddyConfig(
                caddy_dir=Path(args.shared_caddy_dir),
                acme_email=shared_email,
            )
            host_bind_ip = LOCALHOST_BIND_IP
        else:
            caddy_mode = CADDY_MODE_BUNDLED
            caddy_public = args.caddy_public
            host_bind_ip = LOCALHOST_BIND_IP
    else:
        host_bind_ip = PUBLIC_BIND_IP if args.bind_public else LOCALHOST_BIND_IP

    # ... rest of function, add caddy_mode and shared_caddy_config to DeployConfig ...
```

- [ ] **Step 4: Update `collect_config` interactive prompts**

Replace the binary `use_caddy` yes/no with a three-way prompt:

```python
    caddy_choice = _prompt_caddy_mode()  # new helper: returns "bundled"/"external"/"none"
```

Add `_prompt_caddy_mode()`:

```python
def _prompt_caddy_mode() -> str:
    """Prompt for Caddy reverse proxy mode."""
    print("\nCaddy reverse proxy configuration:")
    print("  bundled  - Deploy a Caddy container alongside AgBlogger (default)")
    print("  external - Use a shared Caddy instance for multiple services")
    print("  none     - No Caddy; expose AgBlogger directly")
    while True:
        value = input("Caddy mode [bundled/external/none] [bundled]: ").strip().lower()
        if not value:
            return CADDY_MODE_BUNDLED
        if value in CADDY_MODES:
            return value
        print("Please choose bundled, external, or none.")
```

When `external` is chosen, prompt for:
1. Domain (reuse existing `_prompt_caddy_domain`)
2. Per-service email (reuse existing prompt)
3. Shared Caddy directory (new prompt with default `/opt/caddy`)
4. Shared Caddy ACME email (new prompt, defaults to per-service email)

- [ ] **Step 5: Add CLI arguments**

Add to `_parse_args`:

```python
    config_group.add_argument(
        "--caddy-external",
        action="store_true",
        default=False,
        help="Use a shared external Caddy instance instead of a bundled one.",
    )
    config_group.add_argument(
        "--shared-caddy-dir",
        default=DEFAULT_SHARED_CADDY_DIR,
        help=f"Directory for the shared Caddy instance (default: {DEFAULT_SHARED_CADDY_DIR}).",
    )
    config_group.add_argument(
        "--shared-caddy-email",
        help="ACME email for the shared Caddy instance (defaults to --caddy-email).",
    )
```

- [ ] **Step 6: Update ALL existing `config_from_args` test Namespaces**

**Critical:** The updated `config_from_args` now accesses `args.caddy_external`, `args.shared_caddy_dir`, and `args.shared_caddy_email`. All existing tests that construct `argparse.Namespace` for `config_from_args` MUST add these attributes to avoid `AttributeError`. Add these defaults to every existing Namespace that doesn't already have them:

```python
        caddy_external=False,
        shared_caddy_dir=DEFAULT_SHARED_CADDY_DIR,
        shared_caddy_email=None,
```

Affected tests (search for `argparse.Namespace` in the test file):
- `test_config_from_args_builds_config_without_caddy`
- `test_config_from_args_builds_config_with_caddy`
- `test_config_from_args_auto_generates_secret_key`
- `test_config_from_args_auto_appends_caddy_domain_to_trusted_hosts`
- `test_config_from_args_raises_on_missing_admin_username`
- `test_config_from_args_raises_on_missing_admin_password`
- `test_config_from_args_raises_on_missing_trusted_hosts`
- All other tests that use `argparse.Namespace` with `config_from_args`

- [ ] **Step 7: Run tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "config_from_args" -v`
Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: add external Caddy prompts, CLI args, and config_from_args support"
```

### Task 17: Update dry run, config summary, and _mask_secrets

**Files:**
- Modify: `cli/deploy_production.py` (`dry_run`, `print_config_summary`, `_mask_secrets`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing tests**

```python
def test_dry_run_external_caddy(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
    )
    dry_run(config)

    captured = capsys.readouterr().out
    assert f"=== {DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE} ===" in captured
    assert "blog.example.com" in captured
    # Should NOT show bundled Caddy compose
    assert "=== Caddyfile.production ===" not in captured


def test_print_config_summary_external_caddy(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email="ops@example.com"),
    )
    print_config_summary(config)

    captured = capsys.readouterr().out
    assert "external" in captured.lower()
    assert "/opt/caddy" in captured
    assert "blog.example.com" in captured
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL

- [ ] **Step 3: Update `dry_run`**

Add a branch for external Caddy in the dry-run output:

```python
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        if config.caddy_config:
            print("=== Site snippet ===")
            print(build_caddy_site_snippet(config.caddy_config))
        if config.deployment_mode == DEPLOY_MODE_LOCAL:
            print(f"=== {DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE} ===")
            print(build_external_caddy_compose_content())
        else:
            print(f"=== {DEFAULT_IMAGE_EXTERNAL_CADDY_COMPOSE_FILE} ===")
            print(build_image_external_caddy_compose_content())
```

- [ ] **Step 4: Update `print_config_summary`**

Add an `elif` for external Caddy:

```python
    if config.caddy_mode == CADDY_MODE_EXTERNAL:
        print(f"  Caddy mode:      external (shared)")
        print(f"  Caddy domain:    {config.caddy_config.domain if config.caddy_config else '(none)'}")
        if config.shared_caddy_config:
            print(f"  Shared Caddy:    {config.shared_caddy_config.caddy_dir}")
            print(f"  ACME email:      {config.shared_caddy_config.acme_email or '(none)'}")
    elif config.caddy_config is not None:
        # ... existing bundled summary ...
```

- [ ] **Step 5: Update `_mask_secrets` to pass through new fields**

Add `caddy_mode` and `shared_caddy_config` to the `DeployConfig` construction in `_mask_secrets`.

- [ ] **Step 6: Run tests**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -k "dry_run or summary" -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: update dry run and config summary for external Caddy mode"
```

### Task 18: Update remote README generation

**Files:**
- Modify: `cli/deploy_production.py` (`_build_remote_readme_content`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write failing test**

```python
def test_remote_readme_external_caddy_mentions_shared_setup() -> None:
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
        deployment_mode=DEPLOY_MODE_REGISTRY,
        image_ref="ghcr.io/example/agblogger:1.0",
    )
    commands = build_lifecycle_commands(
        deployment_mode=DEPLOY_MODE_REGISTRY,
        use_caddy=False,
        caddy_public=False,
        caddy_mode=CADDY_MODE_EXTERNAL,
    )
    content = _build_remote_readme_content(config, commands)
    assert "shared Caddy" in content.lower() or "external Caddy" in content.lower()
    assert "/opt/caddy" in content
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Add external Caddy section to README**

In `_build_remote_readme_content`, add a section when `config.caddy_mode == CADDY_MODE_EXTERNAL`:

```python
    if config.caddy_mode == CADDY_MODE_EXTERNAL and config.shared_caddy_config:
        lines.extend([
            "",
            "## Shared Caddy Setup",
            "",
            "This deployment uses an external shared Caddy reverse proxy.",
            f"Shared Caddy directory: `{config.shared_caddy_config.caddy_dir}`",
            "",
            "The deployment script will bootstrap the shared Caddy instance if it",
            "is not already running. To manage the shared Caddy separately:",
            f"  cd {config.shared_caddy_config.caddy_dir}",
            "  docker compose up -d    # start",
            "  docker compose down     # stop",
            "  docker compose logs -f  # logs",
        ])
```

- [ ] **Step 4: Run tests**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/deploy_production.py tests/test_cli/test_deploy_production.py
git commit -m "feat: update remote README for external Caddy mode"
```

---

## Chunk 7: Final Integration and Cleanup

### Task 19: Update `_wait_for_healthy` for external Caddy

When using external Caddy, the health check should only wait for the AgBlogger container, not a bundled Caddy container (since there isn't one in the compose stack).

**Files:**
- Modify: `cli/deploy_production.py` (`_wait_for_healthy`)
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Verify existing behavior**

The current code checks `use_caddy` to decide whether to also wait for the `caddy` container. When `caddy_mode == CADDY_MODE_EXTERNAL`, `use_caddy` (derived from `caddy_config is not None`) would be `True`, but there's no caddy container in the compose stack — it would incorrectly wait for a missing container.

- [ ] **Step 2: Write a failing test for external mode behavior**

```python
def test_wait_for_healthy_skips_caddy_check_in_external_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """In external Caddy mode, _wait_for_healthy should only check agblogger, not caddy."""
    config = _make_config(
        caddy_mode=CADDY_MODE_EXTERNAL,
        caddy_config=CaddyConfig(domain="blog.example.com", email=None),
        host_bind_ip=LOCALHOST_BIND_IP,
        shared_caddy_config=SharedCaddyConfig(caddy_dir=Path("/opt/caddy"), acme_email=None),
    )
    # Simulate: agblogger is healthy but no caddy container in compose output
    call_count = 0

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if "ps" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="agblogger: Up (healthy)\n",
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.deploy_production.subprocess.run", fake_run)
    monkeypatch.setattr("cli.deploy_production.time.sleep", lambda _: None)

    # Should NOT raise even though there's no caddy container in output
    _wait_for_healthy(config, tmp_path, timeout=10, interval=1)
```

- [ ] **Step 3: Run test to verify it fails**

Expected: FAIL (current code would look for caddy container since `caddy_config is not None`)

- [ ] **Step 4: Update `_wait_for_healthy`**

The `_wait_for_healthy` function currently takes a `config: DeployConfig` and derives `use_caddy = config.caddy_config is not None`. Update this to also check `caddy_mode`:

```python
    use_caddy = config.caddy_config is not None and config.caddy_mode != CADDY_MODE_EXTERNAL
```

- [ ] **Step 5: Run test to verify it passes**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_wait_for_healthy_skips_caddy_check_in_external_mode -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add cli/deploy_production.py
git commit -m "fix: skip bundled Caddy health check in external Caddy mode"
```

### Task 20: Update `_compose_base_args` for external Caddy

The `_compose_base_args` helper (used by `_compose_up_command`, `_compose_build_command`, `_wait_for_healthy`) calls `_compose_filenames` with `use_caddy` and `caddy_public`. It also needs to pass `caddy_mode`.

**Files:**
- Modify: `cli/deploy_production.py` (`_compose_base_args`)

- [ ] **Step 1: Update `_compose_base_args` to pass `caddy_mode`**

```python
def _compose_base_args(config: DeployConfig) -> list[str]:
    args = ["compose", "--env-file", ".env.production"]
    for filename in _compose_filenames(
        DEPLOY_MODE_LOCAL,
        use_caddy=config.caddy_config is not None and config.caddy_mode != CADDY_MODE_EXTERNAL,
        caddy_public=config.caddy_public,
        caddy_mode=config.caddy_mode,
    ):
        args.extend(["-f", filename])
    return args
```

- [ ] **Step 2: Run full test suite**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add cli/deploy_production.py
git commit -m "fix: pass caddy_mode through _compose_base_args"
```

### Task 21: End-to-end deploy test for external Caddy

**Files:**
- Test: `tests/test_cli/test_deploy_production.py`

- [ ] **Step 1: Write comprehensive integration test**

```python
def test_deploy_external_caddy_full_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Full local deploy with external Caddy: bootstrap, snippet, compose, start."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    commands = _stub_subprocess(monkeypatch)
    _stub_no_trivy(monkeypatch)
    _stub_docker_inspect_missing(monkeypatch)
    monkeypatch.setattr("cli.deploy_production.reload_shared_caddy", lambda: None)

    caddy_dir = tmp_path / "shared-caddy"
    config = DeployConfig(
        secret_key="x" * 64,
        admin_username="admin",
        admin_password="very-strong-password",
        trusted_hosts=["blog.example.com"],
        trusted_proxy_ips=[],
        host_port=8000,
        host_bind_ip=LOCALHOST_BIND_IP,
        caddy_config=CaddyConfig(domain="blog.example.com", email="ops@example.com"),
        caddy_public=False,
        expose_docs=False,
        deployment_mode=DEPLOY_MODE_LOCAL,
        image_ref=None,
        bundle_dir=DEFAULT_BUNDLE_DIR,
        tarball_filename=DEFAULT_IMAGE_TARBALL,
        caddy_mode=CADDY_MODE_EXTERNAL,
        shared_caddy_config=SharedCaddyConfig(
            caddy_dir=caddy_dir,
            acme_email="ops@example.com",
        ),
    )

    result = deploy(config=config, project_dir=tmp_path)

    # Shared Caddy bootstrapped
    assert (caddy_dir / "sites").is_dir()
    caddyfile = (caddy_dir / "Caddyfile").read_text("utf-8")
    assert "import /etc/caddy/sites/*.caddy" in caddyfile
    assert "email ops@example.com" in caddyfile

    # Site snippet written
    snippet = (caddy_dir / "sites" / "blog.example.com.caddy").read_text("utf-8")
    assert "blog.example.com {" in snippet
    assert "reverse_proxy agblogger:8000" in snippet

    # AgBlogger compose file written (external caddy variant)
    assert (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).exists()
    compose = (tmp_path / DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE).read_text("utf-8")
    assert "external: true" in compose

    # No bundled Caddy files
    assert not (tmp_path / "Caddyfile.production").exists()
    assert not (tmp_path / DEFAULT_CADDY_PUBLIC_COMPOSE_FILE).exists()

    # Lifecycle commands reference external caddy compose
    assert DEFAULT_EXTERNAL_CADDY_COMPOSE_FILE in result.commands["start"]

    # Docker commands: shared caddy compose up + agblogger compose up
    compose_up_calls = [
        (cmd, cwd) for cmd, cwd, _ in commands if "up" in cmd
    ]
    assert len(compose_up_calls) == 2  # shared caddy + agblogger
```

- [ ] **Step 2: Run test**

Run: `just test-backend -- tests/test_cli/test_deploy_production.py::test_deploy_external_caddy_full_flow -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli/test_deploy_production.py
git commit -m "test: add end-to-end deploy test for external Caddy mode"
```

### Task 22: Run full check gate

- [ ] **Step 1: Run `just check`**

Run: `just check`
Expected: All static checks and tests pass

- [ ] **Step 2: Fix any failures**

If any check fails, fix the issue and re-run.

- [ ] **Step 3: Commit any fixes**

### Task 23: Update architecture documentation

**Files:**
- Modify: `docs/arch/deployment.md`

- [ ] **Step 1: Update `docs/arch/deployment.md`**

Add a section after "Deployment Workflows":

```markdown
## Caddy Reverse Proxy Modes

The deployment helper supports three Caddy configurations:

- **Bundled** (default): a dedicated Caddy container is deployed alongside AgBlogger in the same compose stack. Suitable for single-service servers.
- **External**: AgBlogger joins a shared Caddy instance that lives in a separate compose stack at a configurable host directory (default `/opt/caddy/`). Each service drops a site snippet into the shared `sites/` directory. The deployment script bootstraps the shared Caddy if it doesn't exist. Suitable for multi-service servers with distinct subdomains.
- **None**: no Caddy; AgBlogger is exposed directly. Suitable when another reverse proxy is already in place.

The external Caddy mode uses `docker exec caddy caddy reload` to apply configuration changes without restarting the container.
```

- [ ] **Step 2: Commit**

```bash
git add docs/arch/deployment.md
git commit -m "docs: document external Caddy reverse proxy mode"
```
