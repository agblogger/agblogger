# Exception Handling Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all exception handling issues so the server NEVER crashes and never leaks internal error details to clients.

**Architecture:** Introduce typed exception subclasses (`PostNotFoundError`, `BuiltinPageError`, `ExternalServiceError`) to replace fragile string-based error dispatch. Fix all error detail leakage by logging server-side and returning generic messages. Harden the pandoc retry path and global exception handlers to guarantee no unhandled exceptions escape.

**Tech Stack:** Python, FastAPI, httpx, pytest (TDD)

---

### Task 1: Add typed exception classes

**Files:**
- Modify: `backend/exceptions.py`
- Test: `tests/test_services/test_error_handling.py`

**Step 1: Write failing tests**

Append to `tests/test_services/test_error_handling.py`:

```python
class TestTypedExceptions:
    """Typed exception subclasses exist and have correct hierarchy."""

    def test_post_not_found_error_is_value_error(self) -> None:
        from backend.exceptions import PostNotFoundError

        exc = PostNotFoundError("Post not found: posts/hello.md")
        assert isinstance(exc, ValueError)

    def test_builtin_page_error_is_value_error(self) -> None:
        from backend.exceptions import BuiltinPageError

        exc = BuiltinPageError("Cannot delete built-in page 'timeline'")
        assert isinstance(exc, ValueError)

    def test_external_service_error_is_runtime_error(self) -> None:
        from backend.exceptions import ExternalServiceError

        exc = ExternalServiceError("OAuth failed")
        assert isinstance(exc, RuntimeError)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_error_handling.py::TestTypedExceptions -v`
Expected: FAIL — ImportError

**Step 3: Write implementation**

Add to `backend/exceptions.py`:

```python
class PostNotFoundError(ValueError):
    """Raised when a post is not found by path or ID."""


class BuiltinPageError(ValueError):
    """Raised when attempting to modify a built-in page (timeline, labels)."""


class ExternalServiceError(RuntimeError):
    """Raised when an external service (OAuth, HTTP API) fails.

    The global handler logs the full message at ERROR and returns a generic
    "External service error" (502) to the client.
    """
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_error_handling.py::TestTypedExceptions -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/exceptions.py tests/test_services/test_error_handling.py
git commit -m "feat: add PostNotFoundError, BuiltinPageError, ExternalServiceError exception types"
```

---

### Task 2: Use PostNotFoundError in crosspost_service and fix error message leakage

**Files:**
- Modify: `backend/services/crosspost_service.py` (lines 116-118, 229-235)
- Modify: `backend/api/crosspost.py` (lines 130-139)
- Test: `tests/test_services/test_crosspost_error_handling.py` (or `tests/test_api/test_crosspost_api.py`)

**Step 1: Write failing tests**

Create or append to `tests/test_services/test_crosspost_error_handling.py`:

```python
class TestCrosspostPostNotFoundError:
    """crosspost() raises PostNotFoundError for missing posts."""

    @pytest.mark.asyncio
    async def test_missing_post_raises_post_not_found_error(self) -> None:
        from backend.exceptions import PostNotFoundError

        # (use existing test pattern — mock content_manager.read_post to return None)
        # Verify that PostNotFoundError is raised, not ValueError
        ...
```

And append to `tests/test_api/test_error_handling.py`:

```python
class TestCrosspostErrorLeakage:
    """Crosspost error messages must not leak internal details to clients."""

    @pytest.mark.asyncio
    async def test_crosspost_service_error_uses_generic_message(self, client: AsyncClient) -> None:
        """The error field in CrossPostResult should be generic, not str(exc)."""
        token = await login(client)
        with patch(
            "backend.services.crosspost_service.get_poster",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Internal connection to redis://secret:6379 failed"),
        ):
            resp = await client.post(
                "/api/crosspost/post",
                json={"post_path": "posts/hello.md", "platforms": ["bluesky"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        # The error should NOT contain internal details
        if resp.status_code == 200:
            data = resp.json()
            for result in data:
                if result.get("error"):
                    assert "redis" not in result["error"].lower()
                    assert "secret" not in result["error"].lower()
```

**Step 2: Run tests to verify they fail**

**Step 3: Implementation**

In `backend/services/crosspost_service.py`:
- Line 117: Change `raise ValueError(msg)` to `raise PostNotFoundError(msg)` (import from `backend.exceptions`)
- Line 229-235: Change `error=str(exc)` to `error="Cross-posting failed"` (keep `logger.exception`)

In `backend/api/crosspost.py`:
- Lines 130-139: Replace string-based dispatch with typed exception:
```python
    except PostNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add backend/services/crosspost_service.py backend/api/crosspost.py tests/
git commit -m "fix: use PostNotFoundError in crosspost, stop leaking error details"
```

---

### Task 3: Use BuiltinPageError in admin_service and fix admin.py dispatch

**Files:**
- Modify: `backend/services/admin_service.py` (lines 138-140)
- Modify: `backend/api/admin.py` (lines 184-189)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing tests**

Append to `tests/test_api/test_error_handling.py`:

```python
class TestDeleteBuiltinPageError:
    """Delete built-in page returns 400 with BuiltinPageError."""

    @pytest.mark.asyncio
    async def test_delete_builtin_page_returns_400(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.delete(
            "/api/admin/pages/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "built-in" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_page_returns_404(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.delete(
            "/api/admin/pages/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
```

**Step 2: Run tests to verify behavior (tests may already pass for some cases)**

**Step 3: Implementation**

In `backend/services/admin_service.py` line 138-140:
```python
from backend.exceptions import BuiltinPageError

# Change:
#     raise ValueError(msg)
# To:
    raise BuiltinPageError(msg)
```

In `backend/api/admin.py` lines 184-189:
```python
from backend.exceptions import BuiltinPageError

    try:
        delete_page(content_manager, page_id, delete_file=delete_file)
    except BuiltinPageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Failed to delete page %s: %s", page_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete page") from exc
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add backend/services/admin_service.py backend/api/admin.py tests/
git commit -m "fix: use BuiltinPageError for built-in page deletion dispatch"
```

---

### Task 4: Fix error detail leakage in crosspost OAuth endpoints

**Files:**
- Modify: `backend/api/crosspost.py` (lines 245-246, 314-318, 439-443, 520-529, 683-692, 843-852)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing tests**

Append to `tests/test_api/test_error_handling.py`:

```python
class TestOAuthErrorLeakage:
    """OAuth errors must not leak internal details to clients."""

    @pytest.mark.asyncio
    async def test_bluesky_authorize_error_is_generic(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.crosspost.resolve_handle_to_did",
            new_callable=AsyncMock,
            side_effect=__import__("backend.crosspost.atproto_oauth", fromlist=["ATProtoOAuthError"]).ATProtoOAuthError(
                "Internal: PDS at https://secret-pds.internal:8443 returned 500"
            ),
        ):
            resp = await client.post(
                "/api/crosspost/bluesky/authorize",
                json={"handle": "test.bsky.social"},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code == 502:
            detail = resp.json()["detail"]
            assert "secret-pds" not in detail
            assert "8443" not in detail
```

**Step 2: Run tests**

**Step 3: Implementation**

For each leaking location in `backend/api/crosspost.py`, apply the pattern:

```python
# Bluesky authorize (line 245-246):
except ATProtoOAuthError as exc:
    logger.error("Bluesky OAuth error during authorize: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Bluesky authentication failed") from exc

# Bluesky callback (line 314-318):
except ATProtoOAuthError as exc:
    logger.error("Bluesky token exchange error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Bluesky token exchange failed") from exc

# Mastodon authorize (line 439-443):
except httpx.HTTPError as exc:
    logger.error("Mastodon connection error during authorize: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not connect to Mastodon instance") from exc

# Mastodon callback - MastodonOAuthTokenError (line 520-524):
except MastodonOAuthTokenError as exc:
    logger.error("Mastodon token exchange error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Mastodon token exchange failed") from exc

# Mastodon callback - httpx.HTTPError (line 525-529):
except httpx.HTTPError as exc:
    logger.error("Mastodon OAuth HTTP error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Mastodon authentication failed") from exc

# X callback - XOAuthTokenError (line 683-687):
except XOAuthTokenError as exc:
    logger.error("X token exchange error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="X token exchange failed") from exc

# X callback - httpx.HTTPError (line 688-692):
except httpx.HTTPError as exc:
    logger.error("X OAuth HTTP error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="X authentication failed") from exc

# Facebook callback - FacebookOAuthTokenError (line 843-847):
except FacebookOAuthTokenError as exc:
    logger.error("Facebook token exchange error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Facebook token exchange failed") from exc

# Facebook callback - httpx.HTTPError (line 848-852):
except httpx_client.HTTPError as exc:
    logger.error("Facebook OAuth HTTP error: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Facebook authentication failed") from exc
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add backend/api/crosspost.py tests/
git commit -m "fix: stop leaking OAuth error details to clients in crosspost endpoints"
```

---

### Task 5: Fix error detail leakage in sync.py

**Files:**
- Modify: `backend/api/sync.py` (line 210)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing test**

```python
class TestSyncMetadataJsonLeakage:
    """Sync metadata JSON error must not leak parse details."""

    @pytest.mark.asyncio
    async def test_invalid_metadata_returns_generic_message(self, client: AsyncClient) -> None:
        token = await login(client)
        resp = await client.post(
            "/api/sync/commit",
            data={"metadata": "{invalid json here"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail == "Invalid metadata JSON"
        # Must NOT contain json.JSONDecodeError details like line/column numbers
        assert "line" not in detail.lower()
        assert "column" not in detail.lower()
```

**Step 2: Run test — should fail (currently leaks exc detail)**

**Step 3: Implementation**

In `backend/api/sync.py` line 210:
```python
    except json.JSONDecodeError as exc:
        logger.warning("Invalid metadata JSON in sync commit: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from exc
```

**Step 4: Run test — should pass**

**Step 5: Commit**

```bash
git add backend/api/sync.py tests/
git commit -m "fix: stop leaking JSON parse details in sync metadata error"
```

---

### Task 6: Fix pandoc renderer retry exception gap

**Files:**
- Modify: `backend/pandoc/renderer.py` (lines 322-325)
- Test: `tests/test_services/test_error_handling.py`

**Step 1: Write failing test**

```python
class TestPandocRendererRetryExceptionGap:
    """Pandoc retry path must catch all exceptions, not just httpx.HTTPError."""

    @pytest.mark.asyncio
    async def test_retry_catches_non_http_error(self) -> None:
        from unittest.mock import AsyncMock, patch

        import httpx

        from backend.pandoc.renderer import RenderError, _render_markdown, _sanitize_html

        mock_server = AsyncMock()
        mock_server.base_url = "http://localhost:9999"
        mock_server.ensure_running = AsyncMock()

        mock_client = AsyncMock()
        # First call: NetworkError triggers restart
        # Second call: OSError (not httpx.HTTPError) — must not escape
        mock_client.post = AsyncMock(
            side_effect=[httpx.NetworkError("connection reset"), OSError("broken pipe")]
        )

        with (
            patch("backend.pandoc.renderer._server", mock_server),
            patch("backend.pandoc.renderer._http_client", mock_client),
            pytest.raises(RenderError, match="unreachable after restart"),
        ):
            await _render_markdown("# test", from_format="markdown", sanitizer=_sanitize_html)
```

**Step 2: Run test — should fail (OSError escapes unhandled)**

**Step 3: Implementation**

In `backend/pandoc/renderer.py` lines 322-325, change:
```python
        except httpx.HTTPError as retry_exc:
```
to:
```python
        except Exception as retry_exc:
```

**Step 4: Run test — should pass**

**Step 5: Commit**

```bash
git add backend/pandoc/renderer.py tests/
git commit -m "fix: catch all exceptions on pandoc retry path to prevent crash"
```

---

### Task 7: Fix OSError handler re-raising ConnectionError/TimeoutError

**Files:**
- Modify: `backend/main.py` (lines 410-411)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing tests**

```python
class TestConnectionErrorHandler:
    """ConnectionError and TimeoutError return proper HTTP responses, not crash."""

    @pytest.mark.asyncio
    async def test_connection_error_returns_502(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "External service connection failed"

    @pytest.mark.asyncio
    async def test_timeout_error_returns_504(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 504
        assert resp.json()["detail"] == "Operation timed out"
```

**Step 2: Run tests — should fail (currently re-raises, returning 500 or crashing)**

**Step 3: Implementation**

In `backend/main.py` lines 408-416, change:
```python
    @app.exception_handler(OSError)
    async def os_error_handler(request: Request, exc: OSError) -> JSONResponse:
        if isinstance(exc, ConnectionError):
            logger.error(
                "ConnectionError in %s %s: %s",
                request.method, request.url.path, exc, exc_info=exc,
            )
            return JSONResponse(
                status_code=502,
                content={"detail": "External service connection failed"},
            )
        if isinstance(exc, TimeoutError):
            logger.error(
                "TimeoutError in %s %s: %s",
                request.method, request.url.path, exc, exc_info=exc,
            )
            return JSONResponse(
                status_code=504,
                content={"detail": "Operation timed out"},
            )
        logger.error("OSError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Storage operation failed"},
        )
```

**Step 4: Run tests — should pass**

**Step 5: Commit**

```bash
git add backend/main.py tests/
git commit -m "fix: handle ConnectionError/TimeoutError instead of re-raising in OSError handler"
```

---

### Task 8: Replace bare except Exception with OSError in labels.py

**Files:**
- Modify: `backend/api/labels.py` (lines 52, 62, 69)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing test**

```python
class TestLabelPersistNarrowedExceptions:
    """Labels persistence catches OSError specifically, not bare Exception."""

    @pytest.mark.asyncio
    async def test_label_toml_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.labels.write_labels_config",
            side_effect=OSError("disk full"),
        ):
            resp = await client.post(
                "/api/labels",
                json={"id": "test-oserror", "names": ["test"], "parents": []},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_label_toml_write_type_error_propagates(self, client: AsyncClient) -> None:
        """TypeError (programming bug) should NOT be caught by the narrowed handler."""
        token = await login(client)
        with patch(
            "backend.api.labels.write_labels_config",
            side_effect=TypeError("bad argument"),
        ):
            resp = await client.post(
                "/api/labels",
                json={"id": "test-typeerror", "names": ["test"], "parents": []},
                headers={"Authorization": f"Bearer {token}"},
            )
        # Should hit the global TypeError handler (500 "Internal server error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"
```

**Step 2: Run tests**

**Step 3: Implementation**

In `backend/api/labels.py`, change all three `except Exception` to `except OSError`:
- Line 52: `except Exception as exc:` → `except OSError as exc:`
- Line 62: `except Exception as exc:` → `except OSError as exc:`
- Line 69: `except Exception as restore_exc:` → `except OSError as restore_exc:`

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add backend/api/labels.py tests/
git commit -m "fix: narrow labels.py exception handlers from Exception to OSError"
```

---

### Task 9: Replace bare except Exception with OSError in posts.py

**Files:**
- Modify: `backend/api/posts.py` (lines 289, 472, 614)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing test**

```python
class TestPostWriteNarrowedExceptions:
    """Post write catches OSError specifically, not bare Exception."""

    @pytest.mark.asyncio
    async def test_create_post_write_oserror_returns_500(self, client: AsyncClient) -> None:
        token = await login(client)
        with patch(
            "backend.api.posts.ContentManager.write_post",
            side_effect=OSError("disk full"),
        ):
            resp = await client.post(
                "/api/posts",
                json={
                    "title": "Test Narrowed",
                    "body": "Content",
                    "labels": [],
                    "is_draft": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to write post file"
```

**Step 2: Run tests**

**Step 3: Implementation**

In `backend/api/posts.py`, change:
- Line 289: `except Exception as exc:` → `except OSError as exc:`
- Line 472: `except Exception as exc:` → `except OSError as exc:`
- Line 614: `except Exception as exc:` → `except OSError as exc:`

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add backend/api/posts.py tests/
git commit -m "fix: narrow posts.py write exception handlers from Exception to OSError"
```

---

### Task 10: Add local RenderError handling in pages.py

**Files:**
- Modify: `backend/api/pages.py` (line 36)
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Verify existing test**

The test `TestPagePandocFailure::test_page_pandoc_failure_returns_502` already exists and passes (via global handler). We add an explicit local handler so the endpoint controls its own error response rather than relying on the global safety net.

**Step 2: Implementation**

In `backend/api/pages.py`:
```python
import logging

from backend.pandoc.renderer import RenderError

logger = logging.getLogger(__name__)

# In get_page_endpoint:
    try:
        page = await get_page(content_manager, page_id)
    except RenderError as exc:
        logger.error("Pandoc rendering failed for page %s: %s", page_id, exc)
        raise HTTPException(status_code=502, detail="Markdown rendering failed") from exc
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page
```

**Step 3: Verify existing test still passes**

Run: `python -m pytest tests/test_api/test_error_handling.py::TestPagePandocFailure -v`

**Step 4: Commit**

```bash
git add backend/api/pages.py
git commit -m "fix: add local RenderError handling in pages endpoint"
```

---

### Task 11: Add ExternalServiceError global handler in main.py

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_api/test_error_handling.py`

**Step 1: Write failing test**

```python
class TestExternalServiceErrorHandler:
    """ExternalServiceError returns 502 with generic message."""

    @pytest.mark.asyncio
    async def test_external_service_error_returns_502(self, client: AsyncClient) -> None:
        from backend.exceptions import ExternalServiceError

        token = await login(client)
        with patch(
            "backend.api.render.render_markdown",
            new_callable=AsyncMock,
            side_effect=ExternalServiceError("secret internal details"),
        ):
            resp = await client.post(
                "/api/render/preview",
                json={"markdown": "# Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail == "External service error"
        assert "secret" not in detail
```

**Step 2: Run test — should fail**

**Step 3: Implementation**

In `backend/main.py`, add a global handler for `ExternalServiceError` (after the `InternalServerError` handler):

```python
    from backend.exceptions import ExternalServiceError

    @app.exception_handler(ExternalServiceError)
    async def external_service_error_handler(
        request: Request, exc: ExternalServiceError
    ) -> JSONResponse:
        logger.error(
            "ExternalServiceError in %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "External service error"},
        )
```

**Step 4: Run test — should pass**

**Step 5: Commit**

```bash
git add backend/main.py tests/
git commit -m "feat: add ExternalServiceError global handler returning 502"
```

---

### Task 12: Final verification

**Step 1: Run full test suite**

Run: `just check`

**Step 2: Fix any regressions**

**Step 3: Final commit if needed**
