# PR Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 16 issues identified in the comprehensive PR review, using TDD.

**Architecture:** Targeted fixes across backend error handling, sync logic, DRY refactors, test improvements, and one frontend dependency fix. Each fix is self-contained with its own failing test first.

**Tech Stack:** Python/FastAPI (backend), Vitest (frontend), pytest (backend tests)

---

### Task 1: Issue #1 — Restore per-step startup logging in lifespan

**Files:**
- Modify: `backend/main.py:152-220`
- Test: `tests/test_services/test_startup_hardening.py`

**Context:** The lifespan consolidated all startup into one `try` block, losing per-step `logger.critical()` messages. Restore them so operators know which startup step failed.

**Step 1: Write the failing test**

Add to `tests/test_services/test_startup_hardening.py`:

```python
class TestStartupStepLogging:
    """Each startup step should log a critical message identifying the failing component."""

    @pytest.mark.asyncio
    async def test_schema_creation_failure_logs_critical_with_context(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
            database_url="sqlite+aiosqlite:///invalid/nested/deep/path/test.db",
            content_dir=tmp_path / "content",
        )
        app = create_app(settings)

        with caplog.at_level(logging.CRITICAL, logger="backend.main"), suppress(Exception):
            async with app.router.lifespan_context(app):
                pass

        critical_msgs = [r.message for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("database" in m.lower() or "schema" in m.lower() for m in critical_msgs), (
            f"Expected critical log about database/schema failure, got: {critical_msgs}"
        )

    @pytest.mark.asyncio
    async def test_pandoc_failure_logs_critical_with_context(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
            content_dir=tmp_path / "content",
        )
        app = create_app(settings)

        with (
            patch("backend.pandoc.server.PandocServer.start", side_effect=FileNotFoundError("pandoc")),
            caplog.at_level(logging.CRITICAL, logger="backend.main"),
            suppress(Exception),
        ):
            async with app.router.lifespan_context(app):
                pass

        critical_msgs = [r.message for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("pandoc" in m.lower() for m in critical_msgs), (
            f"Expected critical log about pandoc failure, got: {critical_msgs}"
        )

    @pytest.mark.asyncio
    async def test_git_init_failure_logs_critical_with_context(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
            content_dir=tmp_path / "content",
        )
        app = create_app(settings)

        with (
            patch(
                "backend.services.git_service.GitService.init_repo",
                side_effect=FileNotFoundError("git not found"),
            ),
            caplog.at_level(logging.CRITICAL, logger="backend.main"),
            suppress(Exception),
        ):
            async with app.router.lifespan_context(app):
                pass

        critical_msgs = [r.message for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("git" in m.lower() for m in critical_msgs), (
            f"Expected critical log about git failure, got: {critical_msgs}"
        )
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_services/test_startup_hardening.py::TestStartupStepLogging -x -v
```

Expected: FAIL — no critical log messages are emitted for individual steps.

**Step 3: Write minimal implementation**

In `backend/main.py`, wrap each startup step in its own try/except that logs and re-raises. The key is to add `logger.critical()` calls within the single try block using nested try/except:

```python
    try:
        try:
            async with engine.begin() as conn:
                # ... schema creation ...
                await conn.run_sync(Base.metadata.create_all)
            await _ensure_crosspost_user_id_column(app)

            async with session_factory() as session:
                await session.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS ..."))
                await session.commit()
        except Exception as exc:
            logger.critical("Failed to initialize database schema: %s", exc)
            raise

        try:
            ensure_content_dir(settings.content_dir)
        except Exception as exc:
            logger.critical("Failed to initialize content directory at %s: %s", settings.content_dir, exc)
            raise

        content_manager = ContentManager(content_dir=settings.content_dir)
        app.state.content_manager = content_manager

        from backend.services.git_service import GitService

        try:
            git_service = GitService(content_dir=settings.content_dir)
            await git_service.init_repo()
            app.state.git_service = git_service
        except Exception as exc:
            logger.critical("Failed to initialize git repository at %s: %s. Ensure git is installed.", settings.content_dir, exc)
            raise

        # ... OAuth setup (lightweight, unlikely to fail except keypair) ...
        from backend.crosspost.atproto_oauth import load_or_create_keypair
        from backend.crosspost.bluesky_oauth_state import OAuthStateStore

        oauth_key_path = settings.content_dir / ".atproto-oauth-key.json"
        try:
            atproto_key, atproto_jwk = load_or_create_keypair(oauth_key_path)
        except Exception as exc:
            logger.critical("Failed to load or create OAuth keypair at %s: %s", oauth_key_path, exc)
            raise
        app.state.atproto_oauth_key = atproto_key
        app.state.atproto_oauth_jwk = atproto_jwk

        app.state.bluesky_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.mastodon_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.x_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.facebook_oauth_state = OAuthStateStore(ttl_seconds=600)

        from backend.services.auth_service import ensure_admin_user

        try:
            async with session_factory() as session:
                await ensure_admin_user(session, settings)
        except Exception as exc:
            logger.critical("Failed to ensure admin user: %s", exc)
            raise

        try:
            await pandoc_server.start()
        except Exception as exc:
            logger.critical("Failed to start pandoc server: %s. Ensure pandoc is installed.", exc)
            raise
        pandoc_started = True
        app.state.pandoc_server = pandoc_server
        init_renderer(pandoc_server)

        from backend.services.cache_service import rebuild_cache

        try:
            async with session_factory() as session:
                post_count, warnings = await rebuild_cache(session, content_manager)
                logger.info("Indexed %d posts from filesystem", post_count)
                for warning in warnings:
                    logger.warning("Cache rebuild: %s", warning)
        except Exception as exc:
            logger.critical("Failed to rebuild cache from filesystem: %s", exc)
            raise

        yield
    finally:
        # ... cleanup unchanged ...
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_services/test_startup_hardening.py::TestStartupStepLogging -x -v
```

**Step 5: Commit**

```
fix: restore per-step critical logging during startup
```

---

### Task 2: Issue #2 — Add logging in `_DB_COMMIT_ERRORS` handler

**Files:**
- Modify: `backend/api/posts.py:720-736`
- Test: `tests/test_api/test_pr_review_fixes.py`

**Step 1: Write the failing test**

Replace `TestIssue1NarrowCommitExcept` with a behavioral test in `tests/test_api/test_pr_review_fixes.py`:

```python
class TestIssue1CommitFailureLogsError:
    """DB commit failure in update_post should log the error before re-raising."""

    async def test_commit_failure_is_logged_with_context(
        self, client: AsyncClient, app_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = await _login(client)

        # Create a post first
        create_resp = await client.post(
            "/api/posts",
            json={"title": "Commit Log Test", "body": "Content", "labels": [], "is_draft": False},
            headers=headers,
        )
        assert create_resp.status_code == 201
        file_path = create_resp.json()["file_path"]

        with (
            patch(
                "backend.api.posts.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=OperationalError("disk full", {}, Exception()),
            ),
            caplog.at_level(logging.ERROR, logger="backend.api.posts"),
        ):
            resp = await client.put(
                f"/api/posts/{file_path}",
                json={"title": "Commit Log Test", "body": "Updated", "labels": [], "is_draft": False},
                headers=headers,
            )

        assert resp.status_code >= 400
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("commit failed" in m.lower() or "db commit" in m.lower() for m in error_msgs)
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_api/test_pr_review_fixes.py::TestIssue1CommitFailureLogsError -x -v
```

**Step 3: Implement**

In `backend/api/posts.py`, change the `except _DB_COMMIT_ERRORS:` block (line 722) to:

```python
        except _DB_COMMIT_ERRORS as exc:
            logger.error("DB commit failed for post update %s: %s", file_path, exc)
            if needs_rename and new_dir is not None and old_dir is not None and new_dir.exists():
                try:
                    if old_dir.is_symlink():
                        old_dir.unlink()
                    shutil.move(str(new_dir), str(old_dir))
                except OSError as mv_exc:
                    logger.error(
                        "Failed to rollback directory rename %s -> %s: %s",
                        new_dir,
                        old_dir,
                        mv_exc,
                    )
            raise
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
fix: log DB commit errors before re-raising in update_post
```

---

### Task 3: Issue #3 — Remove file paths from sync error details

**Files:**
- Modify: `backend/api/sync.py:293-296, 332-334, 344-346`
- Test: `tests/test_api/test_global_exception_handlers.py` (or new test in `test_pr_review_fixes.py`)

**Step 1: Write the failing test**

```python
class TestIssue3SyncNoPathLeak:
    """Sync error responses should not leak internal file paths."""

    async def test_sync_write_error_does_not_leak_path(
        self, client: AsyncClient
    ) -> None:
        headers = await _login(client)

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            resp = await client.post(
                "/api/sync/commit",
                data={
                    "metadata": json.dumps({
                        "deleted_files": [],
                        "last_sync_commit": None,
                    })
                },
                files=[("files", ("posts/test.md", b"---\ntitle: T\n---\nBody", "text/plain"))],
                headers=headers,
            )

        if resp.status_code == 500:
            detail = resp.json().get("detail", "")
            assert "posts/" not in detail
            assert "test.md" not in detail
```

**Step 2: Run to verify failure**

**Step 3: Implement**

In `backend/api/sync.py`, change all three occurrences of:
```python
detail=f"File I/O error writing {target_path}"
```
to:
```python
detail="File I/O error during sync"
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
fix: remove internal file paths from sync error responses
```

---

### Task 4: Issue #6 — Fix `parse_json_object` inconsistent messages and add response snippet

**Files:**
- Modify: `backend/crosspost/http_utils.py`
- Test: `tests/test_services/test_crosspost.py` (or new dedicated test)

**Step 1: Write the failing test**

```python
class TestParseJsonObjectMessages:
    """parse_json_object error messages should be consistent and include response snippet."""

    def test_non_dict_message_consistent_with_and_without_error_cls(self) -> None:
        import httpx
        from backend.crosspost.http_utils import parse_json_object

        resp = httpx.Response(200, json=[1, 2, 3])

        # Without error_cls
        with pytest.raises(ValueError, match="returned non-object JSON") as exc_info:
            parse_json_object(resp, context="Test endpoint")
        msg_no_cls = str(exc_info.value)

        # With error_cls
        with pytest.raises(RuntimeError, match="returned non-object JSON") as exc_info2:
            parse_json_object(resp, error_cls=RuntimeError, context="Test endpoint")
        msg_with_cls = str(exc_info2.value)

        # Both should use the same phrasing
        assert "non-object JSON" in msg_no_cls
        assert "non-object JSON" in msg_with_cls

    def test_non_json_includes_response_snippet(self) -> None:
        import httpx
        from backend.crosspost.http_utils import parse_json_object

        resp = httpx.Response(200, text="<html>Error</html>")
        with pytest.raises(ValueError, match="<html>") as exc_info:
            parse_json_object(resp, context="Test endpoint")
        assert "<html>" in str(exc_info.value)
```

**Step 2: Run to verify failure**

**Step 3: Implement**

Rewrite `backend/crosspost/http_utils.py`:

```python
def parse_json_object(
    response: httpx.Response,
    *,
    error_cls: type[Exception] | None = None,
    context: str,
) -> dict[str, Any]:
    """Parse an HTTP response body as a JSON object (dict)."""
    cls = error_cls or ValueError
    try:
        body = response.json()
    except ValueError as exc:
        snippet = response.text[:200] if response.text else "(empty)"
        msg = f"{context} returned non-JSON response: {snippet}"
        raise cls(msg) from exc
    if not isinstance(body, dict):
        msg = f"{context} returned non-object JSON"
        raise cls(msg)
    return cast("dict[str, Any]", body)
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
fix: consistent parse_json_object messages with response snippet
```

---

### Task 5: Issue #7 — Downgrade KeyError handler from CRITICAL to ERROR

**Files:**
- Modify: `backend/main.py:592-604`
- Test: `tests/test_api/test_pr_review_fixes.py` (update `TestIssue5KeyErrorLogLevel`)

**Step 1: Write the failing test**

Update `TestIssue5KeyErrorLogLevel` to expect ERROR instead of CRITICAL:

```python
class TestIssue5KeyErrorLogLevel:
    """KeyError global handler should log at ERROR level, not CRITICAL."""

    async def test_key_error_logged_at_error_not_critical(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from httpx import ASGITransport, AsyncClient
        from backend.main import create_app

        settings = Settings(
            secret_key="test-secret-key-min-32-characters-long",
            admin_password="testpassword",
            debug=True,
            frontend_dir=tmp_path / "no-frontend",
        )
        app = create_app(settings)

        @app.get("/test-key-error-level")
        async def _raise_key_error() -> None:
            raise KeyError("secret_key_name")

        with caplog.at_level(logging.DEBUG, logger="backend.main"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/test-key-error-level")

        assert resp.status_code == 500
        # Should be ERROR, not CRITICAL
        key_error_records = [r for r in caplog.records if "KeyError" in r.message]
        assert all(r.levelno == logging.ERROR for r in key_error_records)
        assert not any(r.levelno == logging.CRITICAL for r in key_error_records)
```

**Step 2: Run to verify failure**

**Step 3: Implement**

In `backend/main.py`, change `logger.critical` to `logger.error` in the KeyError handler:

```python
    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
        logger.error(
            "[BUG] KeyError in %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
fix: downgrade KeyError handler from CRITICAL to ERROR
```

---

### Task 6: Issue #5 — Separate `head_commit_failed` from `git_failed` in sync

**Files:**
- Modify: `backend/api/sync.py:399-421`
- Test: `tests/test_api/test_pr_review_fixes.py`

**Step 1: Write the failing test**

```python
class TestIssue5SyncStatusAfterHeadCommitFailure:
    """When git commit succeeds but head_commit() fails, status should be 'ok'."""

    async def test_status_is_ok_when_commit_succeeds_but_head_read_fails(
        self, client: AsyncClient
    ) -> None:
        headers = await _login(client)

        call_count = 0
        original_head_commit = GitService.head_commit

        async def _fail_second_head_commit(self):
            nonlocal call_count
            call_count += 1
            # head_commit is called after commit_all — fail it
            raise subprocess.CalledProcessError(1, "git rev-parse")

        with patch.object(GitService, "head_commit", _fail_second_head_commit):
            resp = await client.post(
                "/api/sync/commit",
                data={"metadata": '{"deleted_files": [], "last_sync_commit": null}'},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # Commit succeeded, only head read failed — status should be "ok"
        assert data["status"] == "ok"
        assert data["commit_hash"] is None
        assert any("commit hash" in w.lower() or "head" in w.lower() for w in data["warnings"])
```

**Step 2: Run to verify failure** (currently returns `"error"`)

**Step 3: Implement**

In `backend/api/sync.py`, replace the `git_failed = True` on head_commit failure with a separate variable:

```python
    commit_hash: str | None = None
    if not git_failed:
        try:
            commit_hash = await git_service.head_commit()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error("Failed to read git HEAD after sync commit: %s", exc)
            sync_warnings.append(
                "Failed to read commit hash after sync; data was committed successfully "
                "but sync history tracking may be degraded."
            )
            # Do NOT set git_failed = True here — the commit itself succeeded

    files_changed = len(uploaded_paths) + len(deleted_files)
```

Remove the `git_failed = True` line that was in the `except` block after `head_commit()`.

**Step 4: Run to verify pass**

**Step 5: Commit**

```
fix: sync status 'ok' when commit succeeds but HEAD read fails
```

---

### Task 7: Issue #14 — Track failed sync deletions separately

**Files:**
- Modify: `backend/api/sync.py:243-253, 411`
- Test: `tests/test_api/test_pr_review_fixes.py` or `tests/test_services/test_remaining_error_fixes.py`

**Step 1: Write the failing test**

```python
class TestIssue14SyncDeletionFailureCount:
    """Failed deletions should not be counted in files_synced."""

    async def test_failed_deletion_not_counted(self, client: AsyncClient) -> None:
        headers = await _login(client)

        # Create a file to delete
        resp = await client.post(
            "/api/sync/commit",
            data={
                "metadata": json.dumps({"deleted_files": [], "last_sync_commit": None}),
            },
            files=[("files", ("posts/to-delete.md", b"---\ntitle: X\n---\nBody", "text/plain"))],
            headers=headers,
        )
        assert resp.status_code == 200

        # Now try to delete it but make unlink fail
        with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
            resp = await client.post(
                "/api/sync/commit",
                data={
                    "metadata": json.dumps({
                        "deleted_files": ["posts/to-delete.md"],
                        "last_sync_commit": None,
                    }),
                },
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        # Failed deletion should NOT count as synced
        assert data["files_synced"] == 0
```

**Step 2: Run to verify failure**

**Step 3: Implement**

In `backend/api/sync.py`, track successful deletions:

```python
    # ── Apply deletions ──
    successful_deletions = 0
    for file_path in deleted_files:
        full_path = _resolve_safe_path(content_dir, file_path)
        if full_path.exists() and full_path.is_file():
            try:
                full_path.unlink()
            except OSError as exc:
                logger.error("Sync: failed to delete %s: %s", file_path.lstrip("/"), exc)
                sync_warnings.append(f"Failed to delete {file_path.lstrip('/')}")
                continue
            logger.info("Sync: deleted file %s", file_path.lstrip("/"))
            successful_deletions += 1
```

And update the count:

```python
    files_changed = len(uploaded_paths) + successful_deletions
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
fix: exclude failed deletions from sync files_synced count
```

---

### Task 8: Issue #11 — Extract `_require_app_state` helper in deps.py

**Files:**
- Modify: `backend/api/deps.py`
- Test: `tests/test_api/test_error_handling.py` or new test

**Step 1: Write the failing test**

```python
class TestIssue11GetSettings503:
    """get_settings should return 503 when settings is missing, like other deps."""

    async def test_get_settings_returns_503_when_missing(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from backend.api.deps import get_settings

        app = FastAPI()

        @app.get("/test-settings")
        async def _endpoint(s=Depends(get_settings)):
            return {"ok": True}

        # Don't set app.state.settings
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/test-settings")
        assert resp.status_code == 503
```

**Step 2: Run to verify failure** (currently raises `AttributeError`)

**Step 3: Implement**

Add a helper and refactor all five dependency functions:

```python
def _require_app_state(request: Request, attr: str, detail: str) -> Any:
    """Get a required attribute from app state, raising 503 if missing."""
    value = getattr(request.app.state, attr, None)
    if value is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return value


def get_settings(request: Request) -> Settings:
    """Get application settings from app state."""
    return cast("Settings", _require_app_state(request, "settings", "Service temporarily unavailable"))


def get_git_service(request: Request) -> GitService:
    """Get git service from app state."""
    return cast("GitService", _require_app_state(request, "git_service", "Service temporarily unavailable"))


def get_content_manager(request: Request) -> ContentManager:
    """Get content manager from app state."""
    return cast("ContentManager", _require_app_state(request, "content_manager", "Service temporarily unavailable"))


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Get a database session."""
    session_factory = _require_app_state(request, "session_factory", "Database temporarily unavailable")
    async with session_factory() as session:
        yield session


def get_content_write_lock(request: Request) -> AsyncWriteLock:
    """Get the global content write lock used to serialize content mutations."""
    return cast("AsyncWriteLock", _require_app_state(request, "content_write_lock", "Service temporarily unavailable"))
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
refactor: extract _require_app_state helper in deps.py
```

---

### Task 9: Issue #12 — Add `SiteConfig.with_pages()` method

**Files:**
- Modify: `backend/filesystem/toml_manager.py:20-28`
- Modify: `backend/services/admin_service.py` (6 call sites)
- Test: `tests/test_services/test_remaining_error_fixes.py` or new unit test

**Step 1: Write the failing test**

```python
class TestSiteConfigWithPages:
    """SiteConfig.with_pages() should return a copy with replaced pages."""

    def test_with_pages_returns_new_config(self) -> None:
        from backend.filesystem.toml_manager import PageConfig, SiteConfig

        cfg = SiteConfig(
            title="Blog", description="Desc", default_author="Admin",
            timezone="UTC", pages=[PageConfig(id="p1", title="Page 1")],
        )
        new_pages = [PageConfig(id="p2", title="Page 2")]
        result = cfg.with_pages(new_pages)

        assert result.title == "Blog"
        assert result.description == "Desc"
        assert result.default_author == "Admin"
        assert result.timezone == "UTC"
        assert len(result.pages) == 1
        assert result.pages[0].id == "p2"
        # Original unchanged
        assert len(cfg.pages) == 1
        assert cfg.pages[0].id == "p1"
```

**Step 2: Run to verify failure**

**Step 3: Implement**

Add method to `SiteConfig` in `backend/filesystem/toml_manager.py`:

```python
@dataclass
class SiteConfig:
    """Parsed site configuration from index.toml."""

    title: str = "My Blog"
    description: str = ""
    default_author: str = ""
    timezone: str = "UTC"
    pages: list[PageConfig] = field(default_factory=list)

    def with_pages(self, pages: list[PageConfig]) -> SiteConfig:
        """Return a copy with the pages list replaced."""
        return SiteConfig(
            title=self.title,
            description=self.description,
            default_author=self.default_author,
            timezone=self.timezone,
            pages=pages,
        )
```

Then replace all 6 instances in `backend/services/admin_service.py` where `SiteConfig(title=cfg.title, ...)` is used, e.g.:

```python
# Before:
updated = SiteConfig(
    title=cfg.title, description=cfg.description,
    default_author=cfg.default_author, timezone=cfg.timezone,
    pages=[*cfg.pages, new_page],
)
# After:
updated = cfg.with_pages([*cfg.pages, new_page])
```

Do the same for `update_site_settings`:
```python
# Before:
updated = SiteConfig(title=title, description=description, default_author=default_author, timezone=timezone, pages=cfg.pages)
# After:
updated = SiteConfig(title=title, description=description, default_author=default_author, timezone=timezone, pages=cfg.pages)
```
Note: `update_site_settings` changes ALL fields, not just pages, so `with_pages` doesn't apply there. Only use it where only `pages` changes (5 of the 6 call sites).

**Step 4: Run to verify pass**

**Step 5: Commit**

```
refactor: add SiteConfig.with_pages() to reduce boilerplate
```

---

### Task 10: Issue #13 — Extract `require_str_field` helper for crosspost modules

**Files:**
- Modify: `backend/crosspost/http_utils.py`
- Modify: `backend/crosspost/mastodon.py`, `facebook.py`, `x.py`, `atproto_oauth.py`
- Test: new unit test for the helper

**Step 1: Write the failing test**

```python
class TestRequireStrField:
    """require_str_field extracts and validates string fields from dicts."""

    def test_returns_value_when_present_and_string(self) -> None:
        from backend.crosspost.http_utils import require_str_field
        assert require_str_field({"key": "val"}, "key", context="test") == "val"

    def test_raises_when_missing(self) -> None:
        from backend.crosspost.http_utils import require_str_field
        with pytest.raises(ValueError, match="test.*missing.*key"):
            require_str_field({}, "key", context="test")

    def test_raises_when_not_string(self) -> None:
        from backend.crosspost.http_utils import require_str_field
        with pytest.raises(ValueError, match="test.*missing.*key"):
            require_str_field({"key": 123}, "key", context="test")

    def test_raises_when_empty_string(self) -> None:
        from backend.crosspost.http_utils import require_str_field
        with pytest.raises(ValueError, match="test.*missing.*key"):
            require_str_field({"key": ""}, "key", context="test")

    def test_custom_error_cls(self) -> None:
        from backend.crosspost.http_utils import require_str_field
        with pytest.raises(RuntimeError, match="missing"):
            require_str_field({}, "key", context="test", error_cls=RuntimeError)
```

**Step 2: Run to verify failure**

**Step 3: Implement**

Add to `backend/crosspost/http_utils.py`:

```python
def require_str_field(
    data: dict[str, Any],
    field: str,
    *,
    context: str,
    error_cls: type[Exception] | None = None,
) -> str:
    """Extract a required non-empty string field from a dict."""
    value = data.get(field)
    if not isinstance(value, str) or not value:
        cls = error_cls or ValueError
        msg = f"{context} response missing {field}"
        raise cls(msg)
    return value
```

Then replace the 7 instances across crosspost modules, e.g. in `mastodon.py`:

```python
# Before:
access_token_value = token_data.get("access_token")
if not isinstance(access_token_value, str) or not access_token_value:
    msg = "Token response missing access_token"
    raise MastodonOAuthTokenError(msg)
access_token = access_token_value

# After:
access_token = require_str_field(
    token_data, "access_token",
    context="Mastodon token endpoint",
    error_cls=MastodonOAuthTokenError,
)
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```
refactor: extract require_str_field helper for crosspost modules
```

---

### Task 11: Issue #9 — Replace source-inspection tests with behavioral tests

**Files:**
- Modify: `tests/test_api/test_pr_review_fixes.py` (classes TestIssue1, TestIssue2, TestIssue7, TestIssue8, TestIssue9, TestIssue10)

**Step 1-3: Rewrite each test class**

Replace `TestIssue1NarrowCommitExcept` — already replaced by Task 2's behavioral test.

Replace `TestIssue2NarrowConfigWriteExcept` with:
```python
class TestIssue2ConfigWriteHandlesOSError:
    """create_page should handle OSError from config write gracefully."""

    def test_config_write_oserror_cleans_up_md_file(self, tmp_content_dir: Path) -> None:
        from backend.filesystem.content_manager import ContentManager
        from backend.services.admin_service import create_page

        cm = ContentManager(content_dir=tmp_content_dir)
        md_path = tmp_content_dir / "test-page.md"

        with patch("backend.services.admin_service.write_site_config", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                create_page(cm, page_id="test-page", title="Test Page")

        # The .md file should have been cleaned up
        assert not md_path.exists()
```

Replace `TestIssue7AccurateHeadCommitWarning` — already covered by Task 6's behavioral test.

Replace `TestIssue8SharedSetGitWarning` — keep the simple import test (it doesn't use `inspect.getsource`), remove the source-checking tests.

Replace `TestIssue9HoistedMergeWrite` and `TestIssue10MergedExceptBlocks` with behavioral integration tests that test actual sync behavior rather than source inspection.

**Step 4: Run all tests**

```bash
python -m pytest tests/test_api/test_pr_review_fixes.py -x -v
```

**Step 5: Commit**

```
test: replace source-inspection tests with behavioral tests
```

---

### Task 12: Issue #15 — Add concurrent write lock contention test

**Files:**
- Modify: `tests/test_api/test_write_locking.py`

**Step 1: Write the test**

```python
class TestWriteLockSerialization:
    """The content write lock should serialize concurrent write operations."""

    @pytest.mark.asyncio
    async def test_concurrent_creates_are_serialized(self, client: AsyncClient) -> None:
        """Two concurrent post creates should not overlap execution."""
        import asyncio

        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        execution_log: list[str] = []
        original_write_post = ContentManager.write_post

        def _slow_write_post(self, file_path, post_data):
            execution_log.append(f"start:{file_path}")
            result = original_write_post(self, file_path, post_data)
            execution_log.append(f"end:{file_path}")
            return result

        with patch.object(ContentManager, "write_post", _slow_write_post):
            results = await asyncio.gather(
                client.post(
                    "/api/posts",
                    json={"title": "Lock A", "body": "A", "labels": [], "is_draft": False},
                    headers=headers,
                ),
                client.post(
                    "/api/posts",
                    json={"title": "Lock B", "body": "B", "labels": [], "is_draft": False},
                    headers=headers,
                ),
            )

        assert all(r.status_code == 201 for r in results)
        # Under serialization, the two operations should NOT interleave:
        # [start:A, end:A, start:B, end:B] or [start:B, end:B, start:A, end:A]
        # NOT [start:A, start:B, ...]
        assert len(execution_log) == 4
        # First two entries should be start/end of the same file
        first_file = execution_log[0].split(":")[1]
        assert execution_log[1] == f"end:{first_file}"
```

**Step 2: Run to verify pass** (this test should already pass with current lock)

**Step 3: This is a coverage test — no implementation change needed**

**Step 4: Commit**

```
test: add concurrent write lock serialization test
```

---

### Task 13: Issue #16 — Add `get_content_write_lock` 503 test

**Files:**
- Modify: `tests/test_api/test_error_handling.py`

**Step 1: Write the failing test**

```python
class TestMissingContentWriteLock:
    """Endpoints should return 503 when content_write_lock is not set."""

    async def test_post_create_returns_503_without_lock(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from backend.api.deps import get_content_write_lock

        app = FastAPI()

        @app.get("/test-lock")
        async def _endpoint(lock=Depends(get_content_write_lock)):
            return {"ok": True}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/test-lock")
        assert resp.status_code == 503
```

**Step 2: Run to verify pass** (should pass with current code since `_require_app_state` returns 503)

**Step 3: No implementation needed — test only**

**Step 4: Commit**

```
test: add get_content_write_lock 503 coverage
```

---

### Task 14: Issue #4 — Revert DOMPurify to ^3.3.1

**Files:**
- Modify: `frontend/package.json`
- Run: `cd frontend && npm install`

**Step 1: No test needed** (dependency version, not behavioral)

**Step 2: Implement**

Change `"dompurify": "^3.1.2"` to `"dompurify": "^3.3.1"` in `frontend/package.json`.

Then run `cd frontend && npm install` to update the lock file.

**Step 3: Run frontend tests**

```bash
cd frontend && npm test
```

**Step 4: Commit**

```
fix: revert dompurify to ^3.3.1 (security-critical library)
```

---

### Task 15: Issue #10 — Document write lock scope in architecture docs

**Files:**
- Modify: `docs/arch/backend.md`

**Step 1: No test needed** (documentation)

**Step 2: Add a section about the content write lock**

Add after the "Application Lifecycle" section:

```markdown
## Content Write Lock

All content-mutating API endpoints (post create/update/delete, admin page CRUD, label CRUD, sync commit) acquire a shared `asyncio.Lock` (`app.state.content_write_lock`) for the full duration of the request. This serializes all content mutations to prevent filesystem race conditions (e.g., concurrent renames, overlapping git commits).

**Known limitation:** The lock is global — all write operations are serialized even when they affect different posts. This is acceptable for a single-user self-hosted blog but would need fine-grained locking (e.g., per-post) to scale to concurrent multi-user editing.
```

**Step 3: Commit**

```
docs: document content write lock scope and limitation
```

---

### Task 16: Issue #8 — Verify OAuth error messages are client-safe (audit-only)

**Files:** No changes needed.

**Analysis:** All OAuth error types (`ATProtoOAuthError`, `MastodonOAuthTokenError`, `XOAuthTokenError`, `FacebookOAuthTokenError`) are caught locally in `backend/api/crosspost.py` with explicit `HTTPException` responses containing controlled messages. `DuplicateAccountError` messages are also client-safe ("Account already exists for mastodon/user"). No code changes needed — the existing error handling is correct.

**Step 1: Write a verification test** (optional, for documentation)

```python
class TestIssue8OAuthErrorsHandledLocally:
    """OAuth errors should be caught locally, not leak to global handler."""

    def test_all_oauth_errors_have_local_handlers(self) -> None:
        import inspect
        from backend.api import crosspost
        source = inspect.getsource(crosspost)
        # All four error types should appear in except blocks
        assert "except ATProtoOAuthError" in source
        assert "except MastodonOAuthTokenError" in source
        assert "except XOAuthTokenError" in source
        assert "except FacebookOAuthTokenError" in source
```

Wait — this is itself a source-inspection test. Instead, the existing `test_global_exception_handlers.py` already tests the safety net behavior. No additional test needed.

**Step 1: No changes needed.**

**Step 2: Commit** — skip, nothing to commit.

---

## Execution Order

Tasks are ordered by dependency:

1. **Task 1** (Issue #1 — startup logging)
2. **Task 2** (Issue #2 — DB commit logging)
3. **Task 3** (Issue #3 — sync path leak)
4. **Task 4** (Issue #6 — parse_json_object)
5. **Task 5** (Issue #7 — KeyError log level)
6. **Task 6** (Issue #5 — sync git_failed flag)
7. **Task 7** (Issue #14 — sync deletion count)
8. **Task 8** (Issue #11 — deps.py DRY)
9. **Task 9** (Issue #12 — SiteConfig.with_pages)
10. **Task 10** (Issue #13 — require_str_field)
11. **Task 11** (Issue #9 — behavioral tests)
12. **Task 12** (Issue #15 — concurrent lock test)
13. **Task 13** (Issue #16 — lock 503 test)
14. **Task 14** (Issue #4 — DOMPurify)
15. **Task 15** (Issue #10 — docs)

Final: `just check` to verify everything passes.
