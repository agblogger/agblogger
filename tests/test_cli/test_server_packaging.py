"""Tests for server-only deployment packaging artifacts."""

from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_server_wheel_manifest_builds_backend_only() -> None:
    manifest_path = PROJECT_ROOT / "packaging" / "server" / "pyproject.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["project"]["name"] == "agblogger-server"
    assert manifest["project"]["scripts"] == {"agblogger-server": "backend.__main__:main"}
    assert manifest["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["backend"]


def test_server_wheel_manifest_does_not_export_cli_scripts() -> None:
    manifest_path = PROJECT_ROOT / "packaging" / "server" / "pyproject.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))

    scripts = manifest["project"]["scripts"]

    assert "agblogger" not in scripts
    assert "agblogger-deploy" not in scripts


def test_dockerfile_installs_server_wheel_without_copying_cli_sources() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY packaging/server/pyproject.toml /app/server-src/pyproject.toml" in dockerfile
    assert "COPY backend/ /app/server-src/backend/" in dockerfile
    assert "RUN uv build --wheel /app/server-src --out-dir /tmp/dist" in dockerfile
    assert "RUN uv pip install --system /tmp/dist/agblogger_server-*.whl" in dockerfile
    assert 'CMD ["agblogger-server"]' in dockerfile
    assert "COPY cli/ ./cli/" not in dockerfile
    assert "COPY backend/ ./backend/" not in dockerfile


def test_dockerfile_copies_version_and_optional_build_file() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY VERSION BUILD* ./" not in dockerfile
    assert "FROM alpine:3.21 AS version-metadata" in dockerfile
    assert "cp VERSION /out/VERSION" in dockerfile
    assert "if [ -f BUILD ]; then cp BUILD /out/BUILD; fi" in dockerfile
    assert "COPY --from=version-metadata /out/ ./" in dockerfile
