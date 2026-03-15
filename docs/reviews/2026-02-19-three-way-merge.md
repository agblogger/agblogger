# Code Review: Three-Way Merge, Git Versioning & Incremental Cache

**Date:** 2026-02-19
**Branch:** main
**Scope:** Git content versioning, three-way merge for sync, incremental cache maintenance, CLI sync client updates, Dockerfile changes

**Files changed:** 14 modified, 6 new (+637, -79 lines)

---

## Critical

| # | Issue | Location |
|---|-------|----------|
| 1 | **No input validation on `commit_hash`** — client-supplied `last_sync_commit` is passed directly to `git show`/`git cat-file`. A value starting with `--` could be interpreted as a git flag. Validate against `^[0-9a-f]{4,40}$`. | `git_service.py:65-75` |
| 2 | **`git_service.commit_all()` unhandled across all 7 call sites** — called after `session.commit()` succeeds. If git fails, the request crashes with 500 even though the primary operation succeeded. Worse, missing git commits break future three-way merge bases. Wrap in try/except and log warning. | `posts.py`, `labels.py`, `sync.py` |
| 3 | **CLI silently drops failed merge downloads** — if `dl_resp.status_code != 200`, the local file is never updated but the manifest is still saved. Silent data loss. | `sync_client.py:290-295` |

## High

| # | Issue | Location |
|---|-------|----------|
| 4 | **Server `scan_content_files` doesn't filter dot-files** — `.env` or other sensitive files in content dir get exposed via sync download. CLI filters them but server doesn't. | `sync_service.py:82-97` |
| 5 | **Invalid conflict paths silently skipped** — `continue` instead of raising 400 (inconsistent with `deleted_files` which properly rejects). Could cause silent data loss for that conflict. | `sync.py:217-218` |
| 6 | **`show_file_at_commit` conflates "not found" with all git errors** — returns `None` for any failure. If git errors due to corruption/I/O, the merge logic treats it as "file deleted", making wrong merge decisions. | `git_service.py:70-75` |
| 7 | **`init_repo()` failure crashes startup** — no actionable error message if `git` is missing from PATH. | `main.py:79-81` |
| 8 | **No error handling for file I/O in merge loop** — `read_text`/`write_text` can raise `OSError`/`UnicodeDecodeError`, leaving sync in a partially-applied state. | `sync.py:226-254` |
| 9 | **No sync lock** — concurrent `sync_commit` calls can interleave file writes, corrupt merges, and race on manifest updates. | `sync.py:184` |
| 10 | **CLI conflict markers silently not written when content is falsy** — prints "markers written" even when `mr["content"]` is `None`/empty. | `sync_client.py:303-304` |

## Medium

| # | Issue | Location |
|---|-------|----------|
| 11 | **`head_commit()` crashes on empty repo** — if initial commit fails (empty content dir), HEAD is invalid and every sync init crashes. Should return `None` with `check=False`. | `git_service.py:60-63` |
| 12 | **Conflicted files added to `merged_uploaded`** — frontmatter normalization runs on restored server versions unnecessarily, updating `modified_at` for unchanged files. Move `merged_uploaded.append` inside the else branch. | `sync.py:256` |
| 13 | **Client-side path traversal in merge results** — merge result `file_path` values from server are not validated for `..` or leading `/`. | `sync_client.py:286-305` |
| 14 | **`_delete_post_fts` data mismatch risk** — FTS delete requires exact original content. If excerpt or content diverged, FTS entry becomes orphaned until next `rebuild_cache()`. | `posts.py:391-411` |
| 15 | **File deletions not logged in sync_commit** — no audit trail if something goes wrong later in the sync process. | `sync.py:197-203` |
| 16 | **Double iteration of merge state** — `merge_groups()` + `merge_lines()` compute the merge twice. Could check for conflict markers in the output instead. | `sync_service.py:244-271` |

## Low / Style

| # | Issue | Location |
|---|-------|----------|
| 17 | **`config_dir` is an unused alias for `content_dir`** — either use `content_dir` directly or document the separation intent. | `sync_client.py:82` |
| 18 | **`uploaded` counter is redundant** — can use `len(uploaded_files)`. | `sync_client.py:157-163` |

## Test Coverage Gaps

- No test for path traversal in `deleted_files` (only upload has a traversal test in `test_api_security.py`)
- No test for search-after-delete (FTS cleanup)
- No test for concurrent sync commits
- No dedicated test for `scan_content_files` excluding `.git` directory

## Positive

- Three-way merge logic is well-implemented with proper fallback when no base exists
- Incremental cache maintenance (labels + FTS) on post CRUD is solid — avoids stale search/filter data
- Good test coverage for merge scenarios (clean, conflict, no base, delete/modify, identical changes)
- `.git` directory properly excluded from content scanning
- Git content versioning design is sound — provides merge base at no extra infrastructure cost
- Architecture docs kept in sync with implementation changes
- All new files correctly include `from __future__ import annotations`

## Detailed Findings

### 1. No input validation on `commit_hash`

The `commit_exists` and `show_file_at_commit` methods pass user-provided `commit_hash` values directly into subprocess arguments. While `subprocess.run` with a list avoids shell injection, the git CLI itself can interpret certain argument patterns. For example, if `commit_hash` starts with `--`, it could be interpreted as a git flag rather than a commit reference. The `last_sync_commit` field comes directly from the client request body (`SyncCommitRequest.last_sync_commit`), which is attacker-controlled.

**Recommendation:**

```python
import re

_COMMIT_RE = re.compile(r"^[0-9a-f]{4,40}$")

def commit_exists(self, commit_hash: str) -> bool:
    if not _COMMIT_RE.match(commit_hash):
        return False
    result = self._run("cat-file", "-t", commit_hash, check=False)
    return result.returncode == 0 and result.stdout.strip() == "commit"
```

### 2. `git_service.commit_all()` failures unhandled

Every call to `git_service.commit_all()` is made without any error handling. The `_run` method uses `check=True` by default, so a failing `git commit` will raise `subprocess.CalledProcessError`. This propagates as an unhandled 500.

More critically, in post and label endpoints, `git_service.commit_all()` is called **after** `session.commit()` has already persisted database changes and `content_manager.write_post()` has already written to disk. The operation succeeded but the user sees failure. Missing git commits also break future three-way merge bases.

**Recommendation:**

```python
try:
    git_service.commit_all(f"Create post: {body.file_path}")
except subprocess.CalledProcessError:
    logger.warning(
        "Git commit failed after creating post %s; content saved but git history incomplete",
        body.file_path,
    )
```

Apply to all 7 call sites.

### 3. CLI silently drops failed merge downloads

When a cleanly merged file needs to be downloaded, the code checks `if dl_resp.status_code == 200` and only writes the file in that case. If the download fails, the code silently moves on. The local file is NOT updated but the manifest WILL be updated, recording the local (pre-merge) state as current.

**Recommendation:** Treat download failure as a fatal sync error:

```python
if mr["status"] == "merged":
    dl_resp = self.client.get(f"/api/sync/download/{fp}")
    if dl_resp.status_code != 200:
        print(f"  ERROR: Failed to download merged file {fp} (HTTP {dl_resp.status_code})")
        print("  Sync aborted. Local state may be inconsistent.")
        sys.exit(1)
```

### 4. Server `scan_content_files` doesn't filter dot-files

The function correctly filters out directories starting with `.` but does **not** filter out dot-files. Files like `.env`, `.agblogger.json`, or other hidden files in the content directory will be included in the server manifest and exposed via `sync_download`. The CLI client already filters hidden files.

**Recommendation:** Add to `scan_content_files`:

```python
for filename in files:
    if filename.startswith("."):
        continue
```

### 5. Invalid conflict paths silently skipped

When a conflict file path fails the path traversal check (`is_relative_to`), the code silently `continue`s. Compare this to the `deleted_files` loop which correctly raises `HTTPException(status_code=400)` for the same condition. A client that sends a path traversal attempt in `conflict_files` gets a successful response with no indication the file was skipped. The conflict is silently dropped.

**Recommendation:** Raise `HTTPException(status_code=400)` for consistency.

### 6. `show_file_at_commit` conflates "not found" with all git errors

Returns `None` for any non-zero exit code. This conflates "file does not exist at this commit" with "the commit hash is invalid", "the git repo is corrupted", "git encountered an I/O error". The callers use `None` to make merge decisions — if it returns `None` due to corruption, the logic decides "Server deleted, client modified → keep client", which is wrong.

**Recommendation:** Distinguish between "file not found at commit" and other errors:

```python
def show_file_at_commit(self, commit_hash: str, file_path: str) -> str | None:
    result = self._run("show", f"{commit_hash}:{file_path}", check=False)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 128 and "does not exist" in result.stderr:
        return None
    logger.error(
        "git show failed for %s:%s (exit %d): %s",
        commit_hash, file_path, result.returncode, result.stderr.strip(),
    )
    return None
```

### 7. `init_repo()` failure crashes startup

If `git` is not installed, not on PATH, or the content directory has permission issues, `subprocess.CalledProcessError` or `FileNotFoundError` will be raised and the application fails to start with a cryptic error.

**Recommendation:** Wrap in try-except with a clear, actionable error message.

### 8. No error handling for file I/O in merge loop

The merge loop performs `full_path.write_text()`, `full_path.read_text()`, `full_path.parent.mkdir()` with zero error handling. Any of these could raise `OSError`, `PermissionError`, or `UnicodeDecodeError`. An exception mid-loop leaves sync in a partially-applied state.

Compare to post CRUD endpoints which properly wrap `content_manager.write_post()` and `content_manager.delete_post()` in try-except blocks.

### 9. No sync lock

The `sync_commit` endpoint performs a multi-step process (delete files, merge conflicts, normalize frontmatter, git commit, scan files, update manifest, rebuild cache) without any locking. Concurrent sync commits can interleave file writes, corrupt merges, and race on manifest updates.

**Recommendation:** Add `asyncio.Lock` on `app.state`:

```python
async with app.state.sync_lock:
    # ... all sync_commit logic ...
```

### 10. CLI conflict markers silently not written when content is falsy

When `mr.get("content")` is `None` or `""`, conflict markers are never written but the code still prints "CONFLICT: file.md (markers written, backup saved)". The user opens the file to resolve conflicts that don't exist.

**Recommendation:** Make the print message accurately reflect what happened.

### 11. `head_commit()` crashes on empty repo

Uses `check=True`, so if `git rev-parse HEAD` fails (empty repository with no commits), it raises `CalledProcessError`. If `init_repo()` initial commit fails (empty content directory, nothing to commit), HEAD remains invalid.

**Recommendation:** Use `check=False` and return `None`.

### 12. Conflicted files added to `merged_uploaded`

`merged_uploaded.append(target_path)` is outside the if/else block so it runs for both merged and conflicted files. Frontmatter normalization then runs on restored server versions, updating `modified_at` unnecessarily.

**Recommendation:** Move `merged_uploaded.append` inside the `else` (clean merge) branch only.

### 13. Client-side path traversal in merge results

Merge result `file_path` values from server are used to construct paths without validation for `..` or leading `/`. The download loop validates paths but the merge result handler does not.

### 14. `_delete_post_fts` data mismatch risk

FTS5 "delete" command requires the exact content that was originally inserted. In `delete_post_endpoint`, the code reads content from filesystem and uses `existing.excerpt or generate_excerpt(old_content)`. If content diverged, the FTS delete silently fails, leaving orphaned entries until next `rebuild_cache()`.

### 15. File deletions not logged

Successful deletions have no audit trail. If the sync commit fails later, it's impossible to determine which files were actually deleted.

### 16. Double iteration of merge state

`merge_groups()` + `merge_lines()` compute the merge twice. Harmless for blog post sizes but technically wasteful. Could check for conflict markers in the output instead.
