# Bidirectional Sync

Hash-based, three-way sync inspired by Unison. Both client and server maintain a **sync manifest** mapping `file_path → (SHA-256 hash, mtime, size)`.
All `/api/sync/*` endpoints require an authenticated admin user.

## Sync Protocol

```
Client                                   Server
  │                                         │
  │  1. POST /api/sync/status               │
  │     (client manifest) ──────────────►   │  Compare client manifest
  │   ◄──────── (sync plan:                 │  vs server manifest
  │       to_upload, to_download,           │  vs current filesystem
  │       to_delete_local,                  │
  │       to_delete_remote)                 │
  │                                         │
  │  2. POST /api/sync/commit               │
  │     (multipart: files +                 │  Write files, run hybrid
  │      JSON metadata with                 │  merge for conflicting
  │      deleted_files,                     │  posts, normalize front
  │      last_sync_commit) ─────────────►   │  matter, git commit, update
  │   ◄──────── (commit_hash,               │  manifest, rebuild cache
  │       to_download, conflicts)           │
  │                                         │
  │  3. GET /api/sync/download/{path}       │
  │   ◄──────────────── (file content)      │  Download server-changed
  │                                         │  and merged files
```

## Three-Way Conflict Detection

| Client vs Manifest | Server vs Manifest | Action |
|---|---|---|
| Same | Same | No change |
| Changed | Same | Upload to server |
| Same | Changed | Download to client |
| Changed | Changed (different) | Conflict |
| New | Not present | Upload |
| Not present | New | Download |
| Deleted | Same | Delete on server |
| Deleted | Changed | Conflict (delete/modify) |
| Same | Deleted | Delete on client |
| Changed | Deleted | Conflict (modify/delete) |

## Front Matter Normalization

During `sync_commit`, before scanning files and updating the manifest, the server applies `deleted_files` requested by the client and normalizes YAML front matter for uploaded `.md` files under `posts/`. Uploaded files are identified from the multipart form data in the commit request.

- **New posts** (not in old server manifest): missing fields are filled with defaults — `created_at` and `modified_at` set to now, `author` from site config `default_author`.
- **Edited posts** (in old server manifest): existing fields are preserved, except `modified_at` which is set to the current server time.
- **Malformed timestamps**: invalid `created_at` / `modified_at` values are treated as missing, replaced with server-time defaults, and reported as warnings in the sync response.
- **Unrecognized fields** in front matter are preserved in the file but generate warnings in the commit response.

Recognized front matter fields: `title`, `created_at`, `modified_at`, `author`, `labels`, `draft`.

## Write Serialization and Graceful Degradation

All content-mutating endpoints (`/api/posts`, `/api/labels`, `/api/admin`, and `/api/sync/commit`)
share a single application-level async write lock (`app.state.content_write_lock`). This serializes
filesystem + cache mutation windows across endpoints and prevents cross-endpoint check-then-act races.

`sync_status` and `sync_commit` also degrade gracefully when git metadata/commit operations fail:
they log the failure server-side and return a successful HTTP response with warning/error status fields
instead of crashing the request handler.

## Git Content Versioning

The server's `content/` directory is a git repository. Every file-modifying operation (post create/update/delete, label create/update/delete, sync commit) creates a git commit via `GitService`. This provides:

- A complete history of all content changes
- The merge base for three-way conflict resolution during sync
- The `server_commit` hash returned in sync status, used by clients to track their last sync point

`GitService` (`backend/services/git_service.py`) wraps the git CLI with async calls delegated through `asyncio.to_thread(subprocess.run, ...)`. Repository write operations (`init_repo()`, `commit_all()`) are serialized with a per-repository async lock so concurrent content mutations cannot interleave `git add`, `git diff --cached`, and `git commit`. The repo is initialized on application startup with `git init` if `.git/` doesn't exist.

## Hybrid Merge

When both client and server modify the same `.md` file under `posts/`, the sync protocol performs a hybrid merge that handles front matter and body separately:

1. **Client uploads all changed files** in a single multipart `POST /api/sync/commit` request
2. **Server reads the base version** from git history at `last_sync_commit`, plus the current server version on disk
3. **Front matter** is merged semantically via `merge_frontmatter()`:
   - `modified_at` is excluded from the semantic merge; the subsequent front matter normalization pass sets it to the current server time
   - `labels` are merged as sets: additions and removals from each side relative to the base are applied together
   - `title`, `author`, `created_at`, `draft`: if both sides changed differently, server wins and the field is reported as a conflict
4. **Body** (markdown below front matter) is merged via `git merge-file`. Non-overlapping edits merge cleanly. If body edits overlap, the server body wins and a body conflict is reported
5. **Reassembly**: merged front matter + merged body are written to disk
6. **Conflict reporting**: the response includes a `conflicts` list with per-file details (`body_conflicted`, `field_conflicts`)

The server version always wins on unresolvable conflicts. The client is informed so the user knows which changes were dropped. Non-post files that conflict are overwritten by the client version (last-writer-wins).

## CLI Sync Client (`cli/sync_client.py`)

A standalone Python script using httpx with subcommands: `init`, `status`, `sync`. Stores config in `.agblogger-sync.json` (including `last_sync_commit`) and the local manifest in `.agblogger-manifest.json`. The `sync` command calls `POST /api/sync/status` to get the sync plan, uploads all changed files plus deletion metadata in a single multipart `POST /api/sync/commit` request, downloads server-changed and merged files, and reports any conflicts. The returned `commit_hash` is saved for subsequent syncs.

CLI authentication supports either:
- Interactive username/password prompt (obtaining a JWT access token), or
- A pre-created PAT via `--pat` (recommended for automation).

For transport security, the CLI requires `https://` for non-localhost servers by default. Plain `http://` is only allowed for localhost, or when explicitly opted in with `--allow-insecure-http`.

## CLI Deployment Helper (`cli/deploy_production.py`)

An interactive deployment script (`agblogger-deploy`) that:

1. Validates Docker/Docker Compose availability.
2. Prompts for required production settings (`SECRET_KEY`, `ADMIN_*`, `TRUSTED_HOSTS`, optional `TRUSTED_PROXY_IPS`, `HOST_PORT`).
3. Optionally configures Caddy by asking for a public domain and optional ACME contact email.
4. Writes `.env.production` with hardened defaults (`DEBUG=false`, `EXPOSE_DOCS=false`, `AUTH_ENFORCE_LOGIN_ORIGIN=true`).
5. Uses checked-in `docker-compose.yml` as the default Caddy-based deployment and generates `Caddyfile.production` when Caddy is enabled.
6. For public Caddy exposure, generates `docker-compose.caddy-public.yml` and deploys with `-f docker-compose.yml -f docker-compose.caddy-public.yml`.
7. When Caddy is disabled, generates `docker-compose.nocaddy.yml` and deploys with `-f docker-compose.nocaddy.yml`.
8. Prints operational commands for start/stop/status and the correct login URL.
