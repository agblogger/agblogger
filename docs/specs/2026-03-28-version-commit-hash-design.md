# Version + Commit Hash Reporting

## Problem

The VERSION file contains only a semver string (`0.1.0`). At runtime there is no way to tell which commit a deployed server or installed CLI binary was built from. The CLI sync client has no `--version` flag at all.

## Design

### BUILD file

A generated file at repo root containing the short commit hash of HEAD at build time:

```
a1b2c3d
```

Single line, no prefix, no newline decoration beyond a trailing `\n`. Added to `.gitignore` — it is a build artifact, never committed.

### `just stamp-build` recipe

```just
stamp-build:
    git rev-parse --short HEAD > BUILD 2>/dev/null || true
```

If git is not available or the working directory is not a repo, the recipe silently does nothing — BUILD is not created. Declared as a dependency of `build-cli`, `deploy`, and `release`. This means all build and release paths automatically stamp the commit hash before producing artifacts. No other build path needs to invoke git or write the BUILD file independently.

### Version string format

When BUILD is present: `0.1.0+a1b2c3d`

When BUILD is absent (e.g., running from source in dev without stamping): `0.1.0`

No git fallback. No dirty flag. If BUILD doesn't exist, silently return the bare version from VERSION. Nothing in the version resolution path ever fails due to a missing BUILD file or missing git — graceful degradation to bare version is the only behavior.

### `backend/version.py` changes

Modify `get_version()` to:

1. Resolve the version string from VERSION file or package metadata (existing logic).
2. Look for a BUILD file next to VERSION. If it exists, append `+{hash}` to the version string.
3. If BUILD doesn't exist, return the bare version.

### `cli/version.py` (new file)

Same logic as `backend/version.py` but for the CLI package. Resolves VERSION and BUILD relative to the executable location. In a PyInstaller bundle, files are extracted to `sys._MEIPASS`, so the lookup path uses that when available, falling back to the normal repo-relative path.

### CLI `--version` flag

Add `--version` to `cli/sync_client.py` argument parser:

```
$ agblogger --version
agblogger 0.1.0+a1b2c3d
```

Uses `cli/version.py` for the version string.

### Build path changes

| Build path | Change |
|---|---|
| `just build-cli` | Depends on `stamp-build`. PyInstaller gets `--add-data BUILD:.` to bundle the BUILD file into the binary. |
| `just install` | Already depends on `build-cli`, no change needed. |
| `just deploy` | Depends on `stamp-build`. BUILD file is already in the Docker build context. |
| `just release` | Depends on `stamp-build`. BUILD is stamped before the release commit and archive. |
| `release-cli.yml` | No change — already calls `just build-cli` which now depends on `stamp-build`. |
| `deploy_production.py` | No change — BUILD is in the build context because `just deploy` stamps it first. |

### Dockerfile change

Change `COPY VERSION ./` to `COPY VERSION BUILD* ./` — the glob `BUILD*` copies BUILD if it exists and is a no-op if it doesn't, so Docker builds succeed with or without a stamped BUILD file.

### .gitignore change

Add `BUILD` entry.

## Files to create or modify

- `.gitignore` — add BUILD
- `justfile` — add `stamp-build` recipe; add dependency to `build-cli`, `deploy`, `release`
- `backend/version.py` — read BUILD file, append hash to version
- `cli/version.py` — new file, version resolution for CLI
- `cli/sync_client.py` — add `--version` flag
- `Dockerfile` — add `COPY BUILD ./`

## Testing

- Unit tests for `backend/version.py`: with BUILD file present → returns `version+hash`; without BUILD → returns bare version.
- Unit tests for `cli/version.py`: same cases, plus PyInstaller `_MEIPASS` path resolution.
- Unit test for CLI `--version` output format.
- Existing health endpoint test updated if it asserts exact version string.
