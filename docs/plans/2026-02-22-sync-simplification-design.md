# Sync Simplification: Git-Based Merge

## Problem

The current sync protocol uses a custom three-way merge implementation (`merge3` library) layered on top of git history. This works but has issues:

1. **False conflicts from `modified_at`**: Every parallel edit produces a different timestamp, causing conflicts even when body edits don't overlap.
2. **False conflicts from `labels`**: Parallel label additions modify the same YAML line, conflicting even though they're semantically compatible (set union).
3. **Redundant merging**: Git already tracks content history on the server; reimplementing merge in Python duplicates what git does natively.
4. **Protocol complexity**: Four endpoints (init, upload, download, commit) with server-side temp state between upload and commit.
5. **CLI complexity**: Three sync modes (push, pull, sync) plus separate conflict-file upload step.

## Design

### Merge Strategy: Hybrid

**Body** (markdown content below front matter): Git merge via branch-and-merge on the server. Git's recursive merge strategy handles non-overlapping edits cleanly. When body edits conflict (overlapping changes), the server version wins.

**Front matter** (YAML metadata above `---`): Semantic field-level merge with custom logic, since line-based merging is wrong for structured metadata:

| Field | Merge rule |
|-------|------------|
| `modified_at` | Strip from both versions before merge. Set to server time after merge. |
| `labels` | Set-based merge: compute additions and removals relative to base from each side, apply both. |
| `title` | If both sides changed differently relative to base: conflict (server wins, reported to client). |
| `author` | Same as `title`. |
| `created_at` | Same as `title`. |
| `draft` | Same as `title`. |

### Server-Side Merge Flow

When `last_sync_commit` is provided and valid:

1. Parse front matter and body from the base version (at `last_sync_commit`), server version (on `main`), and client version (uploaded).
2. Merge front matter fields using semantic rules above. Record any field-level conflicts.
3. Write body-only temp files (no front matter) for base, server, and client.
4. Use `git merge-file` to three-way merge the body content. If it conflicts, keep the server body and record a body conflict.
5. Reassemble merged front matter + merged body. Write to disk.
6. Normalize front matter (set `modified_at` to server time, backfill defaults for new posts).
7. Git commit, update manifest, rebuild cache.

When `last_sync_commit` is `None` (first sync): no merge base available. Client-only files are uploaded to the server. If a file exists on both sides with different content, it's reported as a conflict (server version kept).

### Why `git merge-file` Instead of Branch-and-Merge

Full branch-and-merge (`git checkout -b`, commit, `git merge`) operates on the whole tree and would merge all files at once, including non-markdown files and files the client didn't change. `git merge-file` operates on individual files, giving us precise control: we merge only the files that both sides modified, and we can split front matter from body before merging. This avoids the front matter problem entirely for the body merge step.

### Conflict Reporting

The server returns a list of conflicted files in the sync response, each with details on what conflicted:

```json
{
  "conflicts": [
    {
      "file_path": "posts/2026-02-20-my-post/index.md",
      "body_conflicted": true,
      "field_conflicts": ["title"]
    }
  ]
}
```

The server version wins on all conflicts. The client is informed so the user knows their changes to those files/fields were dropped. The client still has their local version for reference.

### API Endpoints

**Before (4 sync endpoints):**
- `POST /api/sync/init` — exchange manifests, compute plan
- `POST /api/sync/upload` — upload a single file
- `GET /api/sync/download/{path}` — download a single file
- `POST /api/sync/commit` — finalize sync with merge

**After (2 sync endpoints + 1 utility):**

- **`POST /api/sync/status`** — Client sends manifest (list of `{file_path, content_hash}`). Server compares with its manifest and current filesystem state. Returns sync plan: `to_upload`, `to_download`, `to_delete_local`, `to_delete_remote`.

- **`POST /api/sync/commit`** — Single multipart request containing all changed files plus JSON metadata (`deleted_files`, `last_sync_commit`). Server applies changes, runs the hybrid merge for files modified on both sides, normalizes front matter, git commits, updates manifest, rebuilds cache. Returns: `commit_hash`, files to download (server-changed + merged), conflicted files with details.

- **`GET /api/sync/download/{path}`** — Unchanged. Client downloads server-changed and merged files after commit.

### CLI Commands

**Before:** `init`, `status`, `push`, `pull`, `sync`

**After:** `init`, `status`, `sync`

- `push` and `pull` removed. `sync` is always bidirectional.
- Authentication: PAT via `--pat` or `AGBLOGGER_PAT` env var, or interactive username/password prompt (no `--password` argument). No credentials are stored locally.
- `sync` flow: call `status` to get the plan, send all uploads + deletions in a single `commit` request, download server-changed files, update local manifest.

### What Gets Removed

- `merge3` Python dependency
- `merge_file()` function in sync service
- Separate "upload conflict files" protocol step
- `POST /api/sync/upload` endpoint
- `POST /api/sync/init` endpoint (replaced by `POST /api/sync/status`)
- `push` and `pull` CLI commands
- `.conflict-backup` file creation on the client (server wins, client keeps their local copy as-is)

### What Gets Added

- `git merge-file` invocation in `GitService`
- Front matter semantic merge logic (field-level merge with set-based labels)
- Multipart file handling in the `commit` endpoint

### What Changes

- `POST /api/sync/commit` accepts multipart form data (files + JSON metadata) instead of JSON-only
- `SyncClient.sync()` batches all uploads into a single request
- Conflict handling: server wins and reports conflicts, instead of returning conflict markers for client-side resolution
