# Version + Commit Hash Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report version with commit hash (e.g., `0.1.0+a1b2c3d`) in server health endpoint, CLI `--version`, and all deployed artifacts.

**Architecture:** A `just stamp-build` recipe writes `git rev-parse --short HEAD` to a `BUILD` file (silently no-op without git). `backend/version.py` and a new `cli/version.py` append `+{hash}` to the version when BUILD exists, otherwise return bare version. BUILD is gitignored, bundled into PyInstaller binaries and Docker images.

**Tech Stack:** Python, just, PyInstaller, Docker

**Spec:** `docs/specs/2026-03-28-version-commit-hash-design.md`

---

### Task 1: Add BUILD to .gitignore and create `stamp-build` recipe

**Files:**
- Modify: `.gitignore`
- Modify: `justfile:447` (add recipe before `build-cli`, make `build-cli`/`deploy`/`release` depend on it)

- [ ] **Step 1: Add BUILD to .gitignore**

In `.gitignore`, add `BUILD` under the "Local dev state" section:

```gitignore
# ── Local dev state ──────────────────────────────────────────────────
.local/
BUILD
```

- [ ] **Step 2: Add `stamp-build` recipe to justfile**

Insert before the `build-cli` recipe (around line 446):

```just
# Write the current git commit hash to BUILD (writes empty file if git is unavailable)
stamp-build:
    @git rev-parse --short HEAD > BUILD 2>/dev/null || touch BUILD
```

- [ ] **Step 3: Make `build-cli` depend on `stamp-build`**

Change:
```just
build-cli:
```
to:
```just
build-cli: stamp-build
```

- [ ] **Step 4: Make `deploy` depend on `stamp-build`**

Change:
```just
deploy:
```
to:
```just
deploy: stamp-build
```

- [ ] **Step 5: Make `release` depend on `stamp-build`**

Change:
```just
release level:
```
to:
```just
release level: stamp-build
```

- [ ] **Step 6: Test stamp-build**

Run: `just stamp-build && cat BUILD`

Expected: a short hex hash like `7fb9662`

- [ ] **Step 7: Commit**

```bash
git add .gitignore justfile
git commit -m "build: add stamp-build recipe for commit hash stamping"
```

---

### Task 2: Enrich `backend/version.py` with BUILD file support (TDD)

**Files:**
- Create: `tests/test_backend/test_version.py`
- Modify: `backend/version.py`

- [ ] **Step 1: Write failing tests for version with and without BUILD**

Create `tests/test_backend/test_version.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.version import _resolve_version


def test_resolve_version_with_build_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "BUILD").write_text("abc1234\n")
    assert _resolve_version(tmp_path) == "1.2.3+abc1234"


def test_resolve_version_without_build_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    assert _resolve_version(tmp_path) == "1.2.3"


def test_resolve_version_empty_build_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "BUILD").write_text("\n")
    assert _resolve_version(tmp_path) == "1.2.3"


def test_get_version_returns_string() -> None:
    from backend.version import get_version

    version = get_version()
    assert isinstance(version, str)
    assert len(version) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_backend/test_version.py -v`

Expected: FAIL — `_resolve_version` does not exist.

- [ ] **Step 3: Implement `_resolve_version` and update `get_version`**

Replace the full contents of `backend/version.py` with:

```python
from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path


def _resolve_version(base_dir: Path) -> str:
    """Build version string from VERSION and optional BUILD file under *base_dir*."""
    version = (base_dir / "VERSION").read_text(encoding="utf-8").strip()
    build_path = base_dir / "BUILD"
    if build_path.exists():
        commit = build_path.read_text(encoding="utf-8").strip()
        if commit:
            return f"{version}+{commit}"
    return version


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return the application version (cached for process lifetime)."""
    repo_root = Path(__file__).resolve().parents[1]
    if (repo_root / "VERSION").exists():
        return _resolve_version(repo_root)

    for dist_name in ("agblogger-server", "agblogger"):
        with suppress(PackageNotFoundError):
            return package_version(dist_name)

    raise RuntimeError("Could not determine AgBlogger version")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_backend/test_version.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/version.py tests/test_backend/test_version.py
git commit -m "feat: enrich backend version with commit hash from BUILD file"
```

---

### Task 3: Create `cli/version.py` with PyInstaller support (TDD)

**Files:**
- Create: `cli/version.py`
- Create: `tests/test_cli/test_cli_version.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli/test_cli_version.py`:

```python
from __future__ import annotations

from pathlib import Path

from cli.version import get_cli_version


def test_cli_version_with_build_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n")
    (tmp_path / "BUILD").write_text("def5678\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    # Clear the lru_cache so the monkeypatch takes effect
    get_cli_version.cache_clear()
    assert get_cli_version() == "2.0.0+def5678"
    get_cli_version.cache_clear()


def test_cli_version_without_build_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    assert get_cli_version() == "2.0.0"
    get_cli_version.cache_clear()


def test_cli_version_empty_build_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n")
    (tmp_path / "BUILD").write_text("\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    assert get_cli_version() == "2.0.0"
    get_cli_version.cache_clear()


def test_cli_version_no_version_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()
    assert get_cli_version() == "unknown"
    get_cli_version.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_cli_version.py -v`

Expected: FAIL — `cli.version` does not exist.

- [ ] **Step 3: Implement `cli/version.py`**

Create `cli/version.py`:

```python
"""Version resolution for the AgBlogger CLI."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


def _base_dir() -> Path:
    """Return the directory containing VERSION and BUILD files.

    In a PyInstaller bundle, data files are extracted to ``sys._MEIPASS``.
    Otherwise, resolve relative to this file (cli/ -> repo root).
    """
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)  # type: ignore[union-attr]
    return Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def get_cli_version() -> str:
    """Return the CLI version string, cached for process lifetime."""
    base = _base_dir()
    version_path = base / "VERSION"
    if not version_path.exists():
        return "unknown"
    version = version_path.read_text(encoding="utf-8").strip()
    build_path = base / "BUILD"
    if build_path.exists():
        commit = build_path.read_text(encoding="utf-8").strip()
        if commit:
            return f"{version}+{commit}"
    return version
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_cli_version.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/version.py tests/test_cli/test_cli_version.py
git commit -m "feat: add cli/version.py with PyInstaller support"
```

---

### Task 4: Add `--version` flag to CLI sync client (TDD)

**Files:**
- Modify: `cli/sync_client.py:554-557` (argument parser)
- Modify: `tests/test_cli/test_cli_version.py` (add `--version` output test)

- [ ] **Step 1: Write failing test for `--version` output**

Append to `tests/test_cli/test_cli_version.py`:

```python
import subprocess
import sys


def test_cli_version_flag_output(tmp_path: Path, monkeypatch) -> None:
    """The --version flag prints 'agblogger <version>' and exits."""
    (tmp_path / "VERSION").write_text("3.0.0\n")
    (tmp_path / "BUILD").write_text("cafe123\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()

    from cli.sync_client import main

    monkeypatch.setattr(sys, "argv", ["agblogger", "--version"])
    try:
        main()
    except SystemExit:
        pass
    get_cli_version.cache_clear()


def test_cli_version_flag_prints_version(capsys, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "VERSION").write_text("3.0.0\n")
    (tmp_path / "BUILD").write_text("cafe123\n")
    monkeypatch.setattr("cli.version._base_dir", lambda: tmp_path)
    get_cli_version.cache_clear()

    from cli.sync_client import main

    monkeypatch.setattr(sys, "argv", ["agblogger", "--version"])
    try:
        main()
    except SystemExit:
        pass
    captured = capsys.readouterr()
    assert "3.0.0+cafe123" in captured.out
    get_cli_version.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_cli/test_cli_version.py::test_cli_version_flag_prints_version -v`

Expected: FAIL — `--version` not recognized or output doesn't contain version+hash.

- [ ] **Step 3: Add `--version` to sync client parser**

In `cli/sync_client.py`, add an import at the top (after the existing imports, before the `try: import httpx` block):

```python
from cli.version import get_cli_version
```

In the `main()` function, after the `parser = argparse.ArgumentParser(...)` line (line 554), add:

```python
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_cli_version()}",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend -- tests/test_cli/test_cli_version.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/sync_client.py tests/test_cli/test_cli_version.py
git commit -m "feat: add --version flag to CLI sync client"
```

---

### Task 5: Bundle VERSION and BUILD into PyInstaller binary

**Files:**
- Modify: `justfile:448` (`build-cli` recipe — add `--add-data` flags)

- [ ] **Step 1: Add `--add-data` flags to PyInstaller command**

In the `justfile`, modify the `build-cli` recipe. After the `--exclude-module sqlite3 \` line, add two `--add-data` lines before `cli/sync_client.py`:

```just
build-cli: stamp-build
    uv run pyinstaller \
        --onefile \
        --name agblogger \
        --strip \
        --distpath dist/cli \
        --workpath build/cli \
        --specpath build/cli \
        --clean \
        --noconfirm \
        --exclude-module tkinter \
        --exclude-module test \
        --exclude-module unittest \
        --exclude-module pydoc \
        --exclude-module multiprocessing \
        --exclude-module sqlite3 \
        --add-data "VERSION:." \
        --add-data "BUILD:." \
        cli/sync_client.py
```

Note: `build-cli` depends on `stamp-build`, which always creates a BUILD file (empty if git is unavailable). PyInstaller bundles it either way. The CLI version resolution ignores empty BUILD content and returns the bare version.

- [ ] **Step 2: Verify build still works**

Run: `just stamp-build` (creates BUILD), then verify the justfile syntax is valid by checking `just --list` includes `build-cli`.

Run: `just --list | grep build-cli`

Expected: `build-cli` appears in the output.

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "build: bundle VERSION and BUILD into PyInstaller CLI binary"
```

---

### Task 6: Update Dockerfile to copy BUILD file

**Files:**
- Modify: `Dockerfile:58`

- [ ] **Step 1: Update COPY to include BUILD**

In the `Dockerfile`, change line 58 from:

```dockerfile
COPY VERSION ./
```

to:

```dockerfile
COPY VERSION BUILD* ./
```

The `BUILD*` glob copies BUILD if present and is a no-op if absent, so Docker builds succeed with or without a stamped BUILD file.

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "build: copy BUILD file into Docker image when available"
```

---

### Task 7: Run full check and verify

- [ ] **Step 1: Run `just check`**

Run: `just check`

Expected: all static checks and tests pass.

- [ ] **Step 2: Verify end-to-end behavior**

Run: `just stamp-build && cat BUILD`

Verify BUILD contains a short commit hash.

Run: `python -c "from backend.version import get_version; print(get_version())"`

Expected output: version string like `0.1.0+<hash>`.

Run: `python -c "from cli.version import get_cli_version; print(get_cli_version())"`

Expected output: same version string.

- [ ] **Step 3: Verify bare version without BUILD**

Run: `rm BUILD && python -c "from backend.version import get_version; print(get_version())"`

Expected output: `0.1.0` (no hash suffix).

- [ ] **Step 4: Update architecture docs if needed**

Check `docs/arch/deployment.md` — if it describes the VERSION file or Docker build steps, add a note about the BUILD file. Otherwise, skip.
