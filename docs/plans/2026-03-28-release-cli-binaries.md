# Release CLI Binaries — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically build and attach platform-specific sync CLI binaries to GitHub releases when `just release` publishes a new version.

**Architecture:** A single GitHub Actions workflow triggered by `release: published` events. A matrix of two runners (Linux x86_64, macOS ARM64) each check out the release tag, build the CLI binary via `just build-cli`, package it in a platform-appropriate archive (tar.gz / zip), and upload the archive to the existing release.

**Tech Stack:** GitHub Actions, PyInstaller (via `just build-cli`), actions/checkout, actions/setup-python, astral-sh/setup-uv, extractions/setup-just, gh CLI

---

### Task 1: Create the GitHub Actions workflow file

**Files:**
- Create: `.github/workflows/release-cli.yml`

- [ ] **Step 1: Create `.github/workflows/` directory and workflow file**

```yaml
name: Build CLI binaries

on:
  release:
    types: [published]

permissions:
  contents: write

jobs:
  build-cli:
    strategy:
      matrix:
        include:
          - runner: ubuntu-latest
            os: linux
            arch: amd64
            archive: tar.gz
          - runner: macos-latest
            os: darwin
            arch: arm64
            archive: zip
    runs-on: ${{ matrix.runner }}

    steps:
      - name: Checkout release tag
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.release.tag_name }}

      - name: Install Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install uv
        uses: astral-sh/setup-uv@v6

      - name: Install just
        uses: extractions/setup-just@v3

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Build CLI binary
        run: just build-cli

      - name: Package binary
        run: |
          VERSION="${{ github.event.release.tag_name }}"
          VERSION="${VERSION#v}"
          BINARY_NAME="agblogger-${VERSION}"
          ARCHIVE_NAME="agblogger-${VERSION}-${{ matrix.os }}-${{ matrix.arch }}"

          mv dist/cli/agblogger "dist/cli/${BINARY_NAME}"

          if [ "${{ matrix.archive }}" = "tar.gz" ]; then
            tar czf "dist/cli/${ARCHIVE_NAME}.tar.gz" -C dist/cli "${BINARY_NAME}"
          else
            cd dist/cli && zip "${ARCHIVE_NAME}.zip" "${BINARY_NAME}"
          fi

      - name: Upload to release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          VERSION="${{ github.event.release.tag_name }}"
          VERSION="${VERSION#v}"
          ARCHIVE_NAME="agblogger-${VERSION}-${{ matrix.os }}-${{ matrix.arch }}.${{ matrix.archive }}"
          gh release upload "${{ github.event.release.tag_name }}" "dist/cli/${ARCHIVE_NAME}" --clobber
```

- [ ] **Step 2: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release-cli.yml'))"`
Expected: No errors (exits cleanly)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release-cli.yml
git commit -m "ci: add workflow to build and attach CLI binaries to releases"
```

### Task 2: Verify workflow by dry-reading

This is a manual review task — no code changes.

- [ ] **Step 1: Verify the workflow covers all spec requirements**

Check each point against the spec at `docs/specs/2026-03-28-release-cli-binaries-design.md`:
- Trigger: `release: published` — matches `just release` calling `gh release create`
- Checkout: uses `ref: ${{ github.event.release.tag_name }}` — builds from the tag, not HEAD of main
- Python version: `"3.14"` — pinned, resolves to latest patch
- Build: `just build-cli` — reuses the justfile recipe, no duplicated PyInstaller flags
- Naming: binary is `agblogger-<version>`, archive is `agblogger-<version>-<os>-<arch>.<ext>`
- Archive format: tar.gz for Linux, zip for macOS
- Upload: `gh release upload` with `GH_TOKEN` from `github.token`
- Permissions: `contents: write` for uploading assets
