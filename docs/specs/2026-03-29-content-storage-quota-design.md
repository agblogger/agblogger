# Content Storage Quota

## Problem

The server has no limit on the total size of content files. A delegated admin (or anyone with admin credentials in a public demo deployment) can upload files until the disk fills up, potentially crashing the server or corrupting data. The operator needs a way to cap total content storage without exposing quota details to the admin.

## Design

### Configuration

A new `MAX_CONTENT_SIZE` environment variable controls the maximum total size of files under `content/`. Accepts human-readable values with SI-style suffixes: `500M` (megabytes), `2G` (gigabytes), or plain integers as bytes (e.g., `1073741824`). Case-insensitive. Defaults to unlimited (no enforcement), matching current behavior.

Parsed in `backend/config.py` as `max_content_size: int | None` (resolved to bytes). `None` means unlimited. Validation rejects zero, negative, and unparseable values at startup.

### Storage counter

A running counter of total bytes under `content/` is maintained in application state:

- **Startup**: computed by walking `content/` and summing file sizes during the existing lifespan initialization.
- **Writes**: updated incrementally inside the write lock after successful disk operations.
- **Sync**: recomputed from the filesystem after the cache rebuild (sync already walks the content directory).
- **Drift**: self-corrects on every restart and after every sync commit. No persistent storage needed.

The counter lives as application state alongside the existing `content_manager`, injected into handlers via dependency injection.

### Enforcement points

Three mutation paths write to the content directory. Each already holds the write lock:

1. **Post upload** (`POST /api/posts/upload`) -- checks `current_usage + incoming_bytes > max_content_size` before writing files.
2. **Asset upload** (`POST /api/posts/{file_path}/assets`) -- same check.
3. **Sync commit** (`POST /api/sync/commit`) -- same check against total incoming bytes before writing.

On quota exceeded: return **413 Payload Too Large** with body `"Storage limit reached"`. No details about current usage or configured limit are exposed.

### Counter updates by operation

| Operation | Counter update |
|---|---|
| Upload new post + assets | `+= total bytes written` |
| Upload new assets to existing post | `+= total bytes written` |
| Edit post (rewrite index.md) | `+= (new_size - old_size)` |
| Delete post (with directory) | `-= directory total size` |
| Delete single asset | `-= file size` |
| Sync commit | recompute from filesystem after cache rebuild |

All operations run inside the write lock, so there are no races between check and update.

### Deployment script

`cli/deploy_production.py` prompts for the content size limit during interactive configuration:

```
Max content storage size (e.g., 2G, 500M) [unlimited]:
```

Empty input means unlimited (no `MAX_CONTENT_SIZE` in `.env.production`). A value adds `MAX_CONTENT_SIZE=<value>` to the generated env file. The non-interactive path gets a corresponding `--max-content-size` CLI argument.

`DeployConfig` gets a new `max_content_size: str | None = None` field. `build_env_content` includes the variable when set.

### What this does NOT include

- No per-user quotas (single-admin model).
- No usage reporting endpoint or UI -- the admin does not see quota details.
- No separate limits for text vs. assets -- total `content/` size is the single metric.
- No free disk space check -- the quota is the enforcement mechanism.

## Threat model

The primary scenario is an operator who shares admin credentials with a delegated content author (or runs a public demo with open admin access). The author can create and upload content via the web UI but cannot modify deployment configuration or access the server. The quota prevents the author from exhausting disk space.
