# PR Review Fixes — Subprocess Error Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 code defects and 6 test gaps identified by the PR review of the last 7 commits (git subprocess error hardening).

**Architecture:** All changes are in `backend/services/git_service.py`, `backend/api/sync.py`, and `backend/services/sync_service.py`, with companion tests in `tests/test_services/test_git_service.py`, `tests/test_services/test_exception_hierarchy.py`, `tests/test_services/test_sync_merge_integration.py`, and `tests/test_api/test_error_handling.py`.

**Tech Stack:** Python, FastAPI, pytest, asyncio, subprocess, unittest.mock

---

## Files modified

- Modify: `backend/services/git_service.py` (lines 168, 209-210)
- Modify: `backend/api/sync.py` (lines 449, 511, 593-629 and both callers at 420, 444)
- Modify: `backend/services/sync_service.py` (caller of `merge_labels_toml` in sync.py is the fix site, not sync_service itself — see Task 6)
- Modify: `tests/test_services/test_exception_hierarchy.py`
- Modify: `tests/test_services/test_git_service.py`
- Modify: `tests/test_services/test_sync_merge_integration.py`
- Modify: `tests/test_api/test_error_handling.py`

---

## Task 1: Fix `init_repo` catching `FileNotFoundError` instead of `OSError`

**Files:**
- Modify: `backend/services/git_service.py:168`
- Modify: `tests/test_services/test_exception_hierarchy.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_exception_hierarchy.py` after `TestGitServiceInitRepoTimeoutExpired`:

```python
class TestGitServiceInitRepoOSError:
    """init_repo must catch OSError (superset of FileNotFoundError)."""

    async def test_init_repo_catches_permission_error(self, tmp_path: Path) -> None:
        from backend.services.git_service import GitService

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        gs = GitService(content_dir)

        with (
            patch.object(
                gs,
                "_run",
                side_effect=PermissionError(13, "permission denied"),
            ),
            pytest.raises(PermissionError),
        ):
            await gs.init_repo()

    async def test_init_repo_logs_permission_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from backend.services.git_service import GitService

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        gs = GitService(content_dir)

        with (
            patch.object(
                gs,
                "_run",
                side_effect=PermissionError(13, "permission denied"),
            ),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
            pytest.raises(PermissionError),
        ):
            await gs.init_repo()

        assert any("git" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_exception_hierarchy.py::TestGitServiceInitRepoOSError -v
```

Expected: FAIL — `PermissionError` is not caught by the `FileNotFoundError` handler, so it escapes without being logged by `init_repo`.

- [ ] **Step 3: Fix `init_repo` to catch `OSError`**

In `backend/services/git_service.py`, line 168:

```python
# Change from:
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
# To:
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_exception_hierarchy.py::TestGitServiceInitRepoOSError -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/git_service.py tests/test_services/test_exception_hierarchy.py
git commit -m "fix: init_repo catches OSError not just FileNotFoundError"
```

---

## Task 2: Fix `try_commit` timeout logging (add `exc_info` and timeout duration)

**Files:**
- Modify: `backend/services/git_service.py:209-210`
- Modify: `tests/test_services/test_git_service.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_git_service.py`, inside `class TestTryCommitErrorHandling`:

```python
    async def test_try_commit_timeout_includes_exc_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Timeout log record must include exc_info so Sentry can see the exception."""
        gs = GitService(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        await gs.init_repo()

        timeout_exc = subprocess.TimeoutExpired(cmd=["git", "commit"], timeout=30)
        with (
            patch.object(gs, "commit_all", new_callable=AsyncMock, side_effect=timeout_exc),
            caplog.at_level(logging.ERROR, logger="backend.services.git_service"),
        ):
            result = await gs.try_commit("test commit")

        assert result is None
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR and "timed out" in r.message.lower()]
        assert error_records, f"Expected ERROR log about timeout; got: {caplog.text}"
        assert error_records[0].exc_info is not None, "Timeout log must include exc_info"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest "tests/test_services/test_git_service.py::TestTryCommitErrorHandling::test_try_commit_timeout_includes_exc_info" -v
```

Expected: FAIL — current code at line 210 does not pass `exc_info=True`.

- [ ] **Step 3: Fix the timeout log in `try_commit`**

In `backend/services/git_service.py`, lines 209-210:

```python
# Change from:
            elif isinstance(exc, subprocess.TimeoutExpired):
                logger.error("Git commit timed out: %s", message)
# To:
            elif isinstance(exc, subprocess.TimeoutExpired):
                logger.error(
                    "Git commit timed out after %ss: %s",
                    GIT_TIMEOUT_SECONDS,
                    message,
                    exc_info=True,
                )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_git_service.py::TestTryCommitErrorHandling -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/git_service.py tests/test_services/test_git_service.py
git commit -m "fix: add exc_info and timeout duration to try_commit timeout log"
```

---

## Task 3: Guard `commit_exists` call in `_get_base_content` + change return type

**Files:**
- Modify: `backend/api/sync.py` (function `_get_base_content` and its two callers)
- Modify: `tests/test_services/test_sync_merge_integration.py`

Context: `_get_base_content` is at lines ~593-629 of `sync.py`. It calls `git_service.commit_exists(last_sync_commit)` at line 604 without a try/except. `commit_exists` can raise `OSError`, `subprocess.TimeoutExpired`, or `subprocess.CalledProcessError`. To let callers add `sync_warnings` when a git error occurred (vs a legitimately absent base), we change the return type from `str | None` to `tuple[str | None, bool]` where the bool is `True` when a git error occurred.

Callers are at:
- line ~420: labels.toml merge
- line ~444: post body merge

- [ ] **Step 1: Write failing tests**

Add new class to `tests/test_services/test_sync_merge_integration.py`:

```python
class TestGetBaseContentGitErrors:
    """_get_base_content handles git errors by returning (None, True) and logging."""

    async def test_commit_exists_oserror_returns_none_with_error_flag(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """OSError from commit_exists causes _get_base_content to return (None, True)."""
        import io
        import hashlib

        from backend.services.git_service import GitService

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Upload a post first so there is something to sync
        post_content = (
            "---\ntitle: Base Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nOriginal body.\n"
        )
        client_content = (
            "---\ntitle: Base Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nClient edited body.\n"
        )
        file_path = "posts/shared/index.md"
        checksum = hashlib.sha256(client_content.encode()).hexdigest()
        metadata = {
            "deleted_files": [],
            "last_sync_commit": "a" * 40,  # fake commit hash
            "files": [{"path": file_path, "checksum": checksum}],
        }

        with patch.object(
            GitService,
            "commit_exists",
            new_callable=AsyncMock,
            side_effect=OSError("permission denied"),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({**metadata, "files": []})},
                headers=headers,
            )

        # Should succeed (degraded, not failed)
        assert resp.status_code == 200

    async def test_commit_exists_oserror_adds_sync_warning(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When commit_exists raises OSError, a sync_warning is added to the response."""
        import hashlib
        import json

        from backend.services.git_service import GitService

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Simulate conflict scenario: client differs from server for the shared post
        client_content = (
            "---\ntitle: Shared Post\ncreated_at: 2026-02-01 00:00:00+00\nauthor: admin\n"
            "labels:\n- '#a'\n---\n\nClient edit.\n"
        )
        checksum = hashlib.sha256(client_content.encode()).hexdigest()
        metadata = {
            "deleted_files": [],
            "last_sync_commit": "a" * 40,
            "files": [{"path": "posts/shared/index.md", "checksum": checksum}],
        }

        with patch.object(
            GitService,
            "commit_exists",
            new_callable=AsyncMock,
            side_effect=OSError("permission denied"),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={
                    "metadata": json.dumps(metadata),
                    "posts/shared/index.md": (
                        io.BytesIO(client_content.encode()),
                        "posts/shared/index.md",
                        "text/plain",
                    ),
                },
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # A warning must be present explaining the base could not be retrieved
        assert any(
            "merge base" in w.lower() or "base commit" in w.lower()
            for w in data.get("warnings", [])
        ), f"Expected merge base warning; got warnings: {data.get('warnings')}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest "tests/test_services/test_sync_merge_integration.py::TestGetBaseContentGitErrors" -v
```

Expected: FAIL — currently `commit_exists` OSError propagates to the broad `except Exception` rollback handler, returning 500 rather than 200 with a warning.

- [ ] **Step 3: Update `_get_base_content` to guard `commit_exists` and return error flag**

In `backend/api/sync.py`, replace the `_get_base_content` function:

```python
async def _get_base_content(
    git_service: GitService,
    last_sync_commit: str | None,
    file_path: str,
) -> tuple[str | None, bool]:
    """Retrieve the base version of a file from git history.

    Returns (content, had_git_error). Content is None if no valid commit is available
    or the file didn't exist at that commit. had_git_error is True only when git itself
    failed (timeout, OSError, etc.) so callers can add a sync warning.
    """
    if last_sync_commit is None:
        return None, False
    try:
        if not await git_service.commit_exists(last_sync_commit):
            logger.warning(
                "Sync base commit %s not found in repo; falling back to no base for %s",
                last_sync_commit,
                file_path,
            )
            return None, False
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.error(
            "Git error checking commit existence for %s at %s: %s",
            file_path,
            last_sync_commit,
            exc,
            exc_info=True,
        )
        return None, True
    try:
        return await git_service.show_file_at_commit(last_sync_commit, file_path), False
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Git error retrieving base for %s at %s (exit %d): %s",
            file_path,
            last_sync_commit,
            exc.returncode,
            exc.stderr.strip() if exc.stderr else "no stderr",
        )
        return None, True
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.error(
            "Git error retrieving base for %s at %s: %s",
            file_path,
            last_sync_commit,
            exc,
        )
        return None, True
```

- [ ] **Step 4: Update both callers in `sync_commit` to unpack the tuple and add warnings**

In `backend/api/sync.py`, find the labels.toml merge block (around line 420):

```python
# Change from:
                base_content = await _get_base_content(git_service, last_sync_commit, target_path)
                labels_result = merge_labels_toml(base_content, server_content, client_text)
# To:
                base_content, base_git_error = await _get_base_content(
                    git_service, last_sync_commit, target_path
                )
                if base_git_error:
                    sync_warnings.append(
                        f"Could not retrieve merge base for {target_path}; "
                        "three-way merge was not possible."
                    )
                labels_result = merge_labels_toml(base_content, server_content, client_text)
```

Find the post body merge block (around line 444):

```python
# Change from:
                base_content = await _get_base_content(git_service, last_sync_commit, target_path)
                try:
                    merge_result = await merge_post_file(
# To:
                base_content, base_git_error = await _get_base_content(
                    git_service, last_sync_commit, target_path
                )
                if base_git_error:
                    sync_warnings.append(
                        f"Could not retrieve merge base for {target_path}; "
                        "three-way merge was not possible."
                    )
                try:
                    merge_result = await merge_post_file(
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest "tests/test_services/test_sync_merge_integration.py::TestGetBaseContentGitErrors" -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/sync.py tests/test_services/test_sync_merge_integration.py
git commit -m "fix: guard commit_exists in _get_base_content and surface git errors as warnings"
```

---

## Task 4: Quick contract fixes — add `TimeoutExpired` to merge catch, fix exception chain

**Files:**
- Modify: `backend/api/sync.py` (line ~449 and line ~511)

These are small defensive fixes. No new behavior, no new tests needed (existing behavior is unchanged; these prevent future regressions if inner code changes).

- [ ] **Step 1: Add `subprocess.TimeoutExpired` to `merge_post_file` catch clause**

In `backend/api/sync.py`, find the `except (subprocess.CalledProcessError, OSError) as exc:` that catches `merge_post_file` failures (around line 449):

```python
# Change from:
                except (subprocess.CalledProcessError, OSError) as exc:
# To:
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
```

- [ ] **Step 2: Fix exception chain in the mutation-phase catch-all**

In `backend/api/sync.py`, find the broad `except Exception:` rollback handler (around line 511):

```python
# Change from:
    except Exception:
        failures = _restore_original_files(content_dir=content_dir, original_files=original_files)
        if failures:
            logger.error("Sync rollback incomplete, failed to restore: %s", failures)
        logger.exception("Unexpected error during sync commit mutation phase")
        raise HTTPException(status_code=500, detail="Internal error during sync") from None
# To:
    except Exception as exc:
        failures = _restore_original_files(content_dir=content_dir, original_files=original_files)
        if failures:
            logger.error("Sync rollback incomplete, failed to restore: %s", failures)
        logger.exception("Unexpected error during sync commit mutation phase")
        raise HTTPException(status_code=500, detail="Internal error during sync") from exc
```

- [ ] **Step 3: Run the full sync test suite to verify nothing broke**

```bash
uv run pytest tests/test_services/test_sync_merge_integration.py tests/test_api/test_error_handling.py -v -k "sync"
```

Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/api/sync.py
git commit -m "fix: add TimeoutExpired to merge catch and preserve exception chain"
```

---

## Task 5: Fix `_parse_error` sentinel leaking into API response

**Files:**
- Modify: `backend/api/sync.py` (labels merge caller, around line 421-430)
- Modify: `tests/test_services/test_sync_merge_integration.py`

Context: When `merge_labels_toml` cannot parse the server or client labels.toml, it returns `LabelsMergeResult(field_conflicts=["_parse_error"])`. The caller in `sync.py` converts this to a `SyncConflictInfo` and puts it in the API response, exposing the internal sentinel to clients. Instead: filter the sentinel, add a human-readable `sync_warnings` entry.

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_sync_merge_integration.py`:

```python
class TestLabelsTomlParseErrorSentinel:
    """_parse_error sentinel must not appear in the API response field_conflicts."""

    async def test_parse_error_sentinel_not_in_api_response(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When labels.toml can't be parsed, _parse_error must not appear in conflicts."""
        import json

        from backend.services.sync_service import merge_labels_toml, LabelsMergeResult

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        # Patch merge_labels_toml to simulate a parse error result
        with patch(
            "backend.api.sync.merge_labels_toml",
            return_value=LabelsMergeResult(
                merged_content="[labels]\n", field_conflicts=["_parse_error"]
            ),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({"deleted_files": [], "last_sync_commit": None})},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        for conflict in data.get("conflicts", []):
            assert "_parse_error" not in conflict.get("field_conflicts", []), (
                "_parse_error is an internal sentinel and must not appear in API response"
            )

    async def test_parse_error_adds_sync_warning(
        self, merge_client: AsyncClient, merge_settings: Settings
    ) -> None:
        """When labels.toml can't be parsed, a human-readable warning appears in response."""
        import json

        from backend.services.sync_service import LabelsMergeResult

        token = await _login(merge_client)
        headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "backend.api.sync.merge_labels_toml",
            return_value=LabelsMergeResult(
                merged_content="[labels]\n", field_conflicts=["_parse_error"]
            ),
        ):
            resp = await merge_client.post(
                "/api/sync/commit",
                data={"metadata": json.dumps({"deleted_files": [], "last_sync_commit": None})},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert any(
            "labels" in w.lower() and ("parse" in w.lower() or "corrupt" in w.lower())
            for w in data.get("warnings", [])
        ), f"Expected labels parse warning; got warnings: {data.get('warnings')}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest "tests/test_services/test_sync_merge_integration.py::TestLabelsTomlParseErrorSentinel" -v
```

Expected: FAIL — currently `_parse_error` appears in `conflict.field_conflicts`.

- [ ] **Step 3: Filter `_parse_error` at the caller in `sync.py`**

In `backend/api/sync.py`, find the labels merge block that creates `SyncConflictInfo` (around lines 421-430). Replace it:

```python
# Change from:
                if labels_result.field_conflicts:
                    conflicts.append(
                        SyncConflictInfo(
                            file_path=target_path,
                            body_conflicted=False,
                            field_conflicts=labels_result.field_conflicts,
                        )
                    )
# To:
                real_field_conflicts = [
                    fc for fc in labels_result.field_conflicts if not fc.startswith("_")
                ]
                if "_parse_error" in labels_result.field_conflicts:
                    sync_warnings.append(
                        f"Could not parse labels.toml during merge; "
                        "your version was kept but the file may be corrupted."
                    )
                if real_field_conflicts:
                    conflicts.append(
                        SyncConflictInfo(
                            file_path=target_path,
                            body_conflicted=False,
                            field_conflicts=real_field_conflicts,
                        )
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest "tests/test_services/test_sync_merge_integration.py::TestLabelsTomlParseErrorSentinel" -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/sync.py tests/test_services/test_sync_merge_integration.py
git commit -m "fix: filter _parse_error sentinel from API response, surface as sync warning"
```

---

## Task 6: Missing API tests — `OSError` paths for `sync_commit` and `sync_status`

**Files:**
- Modify: `tests/test_api/test_error_handling.py`

- [ ] **Step 1: Write the two failing API tests**

Find the `TestSyncCommitGitFailure` class in `tests/test_api/test_error_handling.py` (it contains `test_sync_commit_git_missing_returns_warning`). Add after the existing test:

```python
    @pytest.mark.asyncio
    async def test_sync_commit_permission_error_returns_warning(
        self, client: AsyncClient
    ) -> None:
        """PermissionError (OSError subclass) from commit_all is caught and returns 200 with warning."""
        token = await login(client)
        with patch(
            "backend.api.sync.GitService.commit_all",
            new_callable=AsyncMock,
            side_effect=PermissionError(13, "read-only filesystem"),
        ):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert any("git commit failed" in warning.lower() for warning in data["warnings"])
```

Find `TestSyncStatusHeadCommitFailure` in the same file. Add after the existing test:

```python
    @pytest.mark.asyncio
    async def test_sync_status_returns_warning_on_oserror(
        self, client: AsyncClient
    ) -> None:
        """OSError from head_commit is caught and returns 200 with warning, not 500."""
        token = await login(client)
        headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "backend.api.sync.GitService.head_commit",
            new_callable=AsyncMock,
            side_effect=PermissionError(13, "permission denied"),
        ):
            resp = await client.post(
                "/api/sync/status",
                json={"client_manifest": []},
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_commit"] is None
        assert any(
            "git" in w.lower() or "history" in w.lower()
            for w in data.get("warnings", [])
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest "tests/test_api/test_error_handling.py::TestSyncCommitGitFailure::test_sync_commit_permission_error_returns_warning" "tests/test_api/test_error_handling.py::TestSyncStatusHeadCommitFailure::test_sync_status_returns_warning_on_oserror" -v
```

Expected: FAIL — the `sync_status` endpoint's `except` clause at `sync.py:237` already catches `OSError`, so it should pass. The `sync_commit` endpoint at line 531 also already catches `OSError`, so it should pass too. If both pass immediately, the tests are green regressions and can be committed as-is.

- [ ] **Step 3: Run and confirm (may already pass)**

These tests verify that existing behavior is preserved. If they pass at step 2, that is the expected outcome — the catch clauses were added in the last 7 commits and the tests confirm the contract.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api/test_error_handling.py
git commit -m "test: add regression tests for OSError from commit_all and head_commit"
```

---

## Task 7: Strengthen `_kill_and_wait_for_process_exit` and `merge_file_content` tests

**Files:**
- Modify: `tests/test_services/test_git_service.py`

- [ ] **Step 1: Strengthen `TestKillAndWaitOSErrorLogging` to assert `exc_info` on the warning record**

Find `class TestKillAndWaitOSErrorLogging` in `test_git_service.py`. After the existing `assert kill_warnings` assertion, add:

```python
        # The warning must include exc_info so structured logging / Sentry captures the exception
        assert kill_warnings[0].exc_info is not None, (
            "Kill failure WARNING must include exc_info=True"
        )
```

- [ ] **Step 2: Strengthen `TestWriteMergeInputsErrorLogging` to assert `exc_info` on the error record**

Find `class TestWriteMergeInputsErrorLogging` in `test_git_service.py`. After the existing `assert "Failed to write merge input files" in caplog.text` assertion, add:

```python
        error_records = [
            r for r in caplog.records
            if r.levelno == logging.ERROR and "Failed to write merge input files" in r.message
        ]
        assert error_records, "Expected ERROR log record for write failure"
        assert error_records[0].exc_info is not None, (
            "Write failure ERROR must include exc_info=True"
        )
```

- [ ] **Step 3: Run these tests to verify they pass (implementation already has `exc_info=True`)**

```bash
uv run pytest "tests/test_services/test_git_service.py::TestKillAndWaitOSErrorLogging" "tests/test_services/test_git_service.py::TestWriteMergeInputsErrorLogging" -v
```

Expected: PASS — both implementation sites already use `exc_info=True`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_services/test_git_service.py
git commit -m "test: assert exc_info on kill-failure and merge-input-write error logs"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full test suite**

```bash
just check
```

Expected: all static checks and tests PASS with no new failures.

- [ ] **Step 2: If any failures appear, fix them before proceeding**

Common issues to watch for:
- Type errors from `_get_base_content` return type change (mypy/basedpyright will catch any call sites that still expect `str | None` instead of `tuple[str | None, bool]`)
- Import of `LabelsMergeResult` needed in `test_sync_merge_integration.py` — add `from backend.services.sync_service import LabelsMergeResult` to imports

- [ ] **Step 3: Commit final verification pass if any fixups were needed**

```bash
git add -p
git commit -m "fix: address type errors from _get_base_content return type change"
```

---

## Self-review checklist

- [x] Spec coverage: all 8 code defects and 6 test gaps from the review have tasks
- [x] No placeholder steps — all code shown in full
- [x] `_get_base_content` return type change is consistent: both callers updated in Task 3
- [x] `LabelsMergeResult` is used in Task 5 test — must be importable from `backend.services.sync_service`
- [x] `merge_labels_toml` is patched at `backend.api.sync.merge_labels_toml` (the import path used by sync.py)
- [x] All tests follow TDD: failing test first, then fix
- [x] `just check` at the end catches any type issues
