# CI Workflow: Build and Attach Sync CLI Binaries to Releases

## Problem

`just release` creates a GitHub release with a source tarball, but users who want the sync CLI must build it themselves. We need a CI workflow that automatically builds platform-specific binaries and attaches them to the release.

## Design

### Trigger

The workflow triggers on `release` events with `types: [published]`, which fires automatically when `just release` calls `gh release create`.

### Build Matrix

| Runner           | Platform      | Archive name                              | Archive format |
|------------------|---------------|-------------------------------------------|----------------|
| `ubuntu-latest`  | Linux x86_64  | `agblogger-1.2.3-linux-amd64.tar.gz`     | tar.gz         |
| `macos-latest`   | macOS ARM64   | `agblogger-1.2.3-darwin-arm64.zip`        | zip            |

tar.gz for Linux (native convention), zip for macOS (Finder-native extraction).

### Steps per runner

1. Checkout the release tag explicitly (`actions/checkout` with `ref: ${{ github.event.release.tag_name }}`)
2. Install Python 3.14 (`actions/setup-python`, pin to `"3.14"`, resolve latest patch)
3. Install uv (`astral-sh/setup-uv`)
4. Install just (`extractions/setup-just`)
5. Install project dev dependencies (`uv sync`)
6. Extract version from release tag (`${{ github.event.release.tag_name }}`, strip `v` prefix)
7. Run `just build-cli` — produces `dist/cli/agblogger`
8. Rename binary to `agblogger-<version>` (e.g. `agblogger-1.2.3`)
9. Package: `tar czf` on Linux, `zip` on macOS
8. Upload the archive to the existing GitHub release (`gh release upload`)

### Naming

Version is extracted from the release tag (e.g. `v1.2.3` → `1.2.3`). Both the binary and the archive include the version:

- Binary: `agblogger-1.2.3`
- Archive: `agblogger-1.2.3-linux-amd64.tar.gz` / `agblogger-1.2.3-darwin-arm64.zip`

### Authentication

Uses the automatic `GITHUB_TOKEN` for `gh release upload`. No additional secrets required.

### Python version

Pinned to `"3.14"` — `actions/setup-python` resolves to the latest available 3.14.x patch.
