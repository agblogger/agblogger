# Crash-Hunting Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all HIGH and MEDIUM severity crash-hunting issues identified in `docs/reviews/2026-03-10-crash-hunting-review.md`.

**Architecture:** Each task targets one or two files with focused, independent fixes. All follow TDD: write a failing test first, then implement the minimal fix. Tasks are grouped so independent ones can run in parallel.

**Tech Stack:** Python, FastAPI, pytest, SQLAlchemy, asyncio, httpx

---

## Chunk 1: Independent small fixes (parallelizable)

### Task 1: Add missing global exception handlers

**Files:**
- Modify: `backend/main.py:459-462` (RuntimeError handler) and add new handlers after line 662
- Test: `tests/test_api/test_global_exception_handlers.py`

- [ ] **Step 1: Write failing tests for AttributeError, IndexError, RecursionError**

Add to `tests/test_api/test_global_exception_handlers.py`:

```python
class TestAttributeErrorGlobalHandler:
    """AttributeError must return 500 JSON, not raw Starlette response."""

    async def test_attribute_error_returns_500_json(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=AttributeError("secret_attr"),
        ):
            resp = await client.get("/api/posts", headers=headers)
        assert resp.status_code == 500
        body = resp.json()
        assert "secret_attr" not in body["detail"]
        assert body["detail"] == "Internal server error"


class TestIndexErrorGlobalHandler:
    """IndexError must return 500 JSON, not raw Starlette response."""

    async def test_index_error_returns_500_json(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=IndexError("list index out of range"),
        ):
            resp = await client.get("/api/posts", headers=headers)
        assert resp.status_code == 500
        body = resp.json()
        assert "list index" not in body["detail"]
        assert body["detail"] == "Internal server error"


class TestRecursionErrorGlobalHandler:
    """RecursionError must return 500 JSON, not be re-raised."""

    async def test_recursion_error_returns_500_json(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=RecursionError("maximum recursion depth exceeded"),
        ):
            resp = await client.get("/api/posts", headers=headers)
        assert resp.status_code == 500
        body = resp.json()
        assert "recursion" not in body["detail"].lower()
        assert body["detail"] == "Internal server error"


class TestNotImplementedErrorGlobalHandler:
    """NotImplementedError must return 500 JSON, not be re-raised."""

    async def test_not_implemented_error_returns_500_json(self, client: AsyncClient) -> None:
        headers = await _login(client)
        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=NotImplementedError("not yet implemented"),
        ):
            resp = await client.get("/api/posts", headers=headers)
        assert resp.status_code == 500
        body = resp.json()
        assert "not yet" not in body["detail"]
        assert body["detail"] == "Internal server error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_global_exception_handlers.py::TestAttributeErrorGlobalHandler -v && pytest tests/test_api/test_global_exception_handlers.py::TestIndexErrorGlobalHandler -v && pytest tests/test_api/test_global_exception_handlers.py::TestRecursionErrorGlobalHandler -v && pytest tests/test_api/test_global_exception_handlers.py::TestNotImplementedErrorGlobalHandler -v`
Expected: FAIL

- [ ] **Step 3: Fix RuntimeError handler and add new handlers**

In `backend/main.py`, remove the re-raise of `RecursionError`/`NotImplementedError` from the `RuntimeError` handler (lines 460-462), and add handlers for `AttributeError` and `IndexError`:

1. Change the RuntimeError handler (line 460-462) — remove the `if isinstance(exc, (NotImplementedError, RecursionError)): raise exc` block entirely. The handler should catch ALL RuntimeError subclasses including RecursionError and NotImplementedError.

2. Add after the `OperationalError` handler (after line 662):
```python
@app.exception_handler(AttributeError)
async def attribute_error_handler(request: Request, exc: AttributeError) -> JSONResponse:
    logger.error(
        "[BUG] AttributeError in %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

@app.exception_handler(IndexError)
async def index_error_handler(request: Request, exc: IndexError) -> JSONResponse:
    logger.error(
        "[BUG] IndexError in %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api/test_global_exception_handlers.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api/test_global_exception_handlers.py
git commit -m "fix: add global handlers for AttributeError, IndexError, RecursionError"
```

---

### Task 2: Cap slug generation loop

**Files:**
- Modify: `backend/services/slug_service.py:72-77`
- Modify: `backend/api/posts.py:804-812`
- Test: `tests/test_services/test_slug_service.py`

- [ ] **Step 1: Write failing test for slug collision cap**

Add to `tests/test_services/test_slug_service.py`:

```python
class TestSlugCollisionCap:
    def test_cap_at_1000_collisions(self, tmp_path: Path) -> None:
        """generate_post_path must raise ValueError after 1000 collisions."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        slug = generate_post_slug("My Post")
        today = __import__("datetime").date.today().isoformat()
        # Create dirs for base + -2 through -1000
        (posts_dir / f"{today}-{slug}").mkdir()
        for i in range(2, 1001):
            (posts_dir / f"{today}-{slug}-{i}").mkdir()
        with pytest.raises(ValueError, match="Too many slug collisions"):
            generate_post_path("My Post", posts_dir)

    def test_finds_slot_just_before_cap(self, tmp_path: Path) -> None:
        """generate_post_path finds a slot at counter=999 (just under cap)."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        slug = generate_post_slug("My Post")
        today = __import__("datetime").date.today().isoformat()
        (posts_dir / f"{today}-{slug}").mkdir()
        for i in range(2, 1000):
            (posts_dir / f"{today}-{slug}-{i}").mkdir()
        result = generate_post_path("My Post", posts_dir)
        assert result.parent.name == f"{today}-{slug}-1000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_slug_service.py::TestSlugCollisionCap -v`
Expected: FAIL (infinite loop / no ValueError)

- [ ] **Step 3: Add cap to generate_post_path**

In `backend/services/slug_service.py`, add `_MAX_SLUG_COLLISION = 1000` constant after `_UNTITLED_COLLISION_SLUG`, then modify the while loop:

```python
_MAX_SLUG_COLLISION = 1000

# In generate_post_path:
    counter = 2
    while counter <= _MAX_SLUG_COLLISION:
        candidate = posts_dir / f"{base_name}-{counter}"
        if not candidate.exists():
            return candidate / "index.md"
        counter += 1
    raise ValueError(f"Too many slug collisions for '{base_name}' (>{_MAX_SLUG_COLLISION})")
```

- [ ] **Step 4: Apply same cap in posts.py rename collision loop**

In `backend/api/posts.py` lines 804-812, add the same bounded loop:

```python
                    if new_dir.exists():
                        counter = 2
                        while counter <= 1000:
                            candidate = posts_parent / f"{new_dir_name}-{counter}"
                            if not candidate.exists():
                                new_dir = candidate
                                break
                            counter += 1
                        else:
                            raise HTTPException(
                                status_code=500,
                                detail="Too many directory name collisions",
                            )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_services/test_slug_service.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/slug_service.py backend/api/posts.py tests/test_services/test_slug_service.py
git commit -m "fix: cap slug collision loop at 1000 iterations to prevent DoS"
```

---

### Task 3: Block asset upload overwriting index.md

**Files:**
- Modify: `backend/api/posts.py:436-438`
- Test: `tests/test_api/test_post_assets_upload.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_post_assets_upload.py` in `TestUploadAssets`:

```python
    @pytest.mark.asyncio
    async def test_upload_index_md_rejected(self, client: AsyncClient) -> None:
        """Upload with filename 'index.md' must be rejected to prevent post corruption."""
        token = await _login(client)
        resp = await client.post(
            f"/api/posts/{POST_PATH}/assets",
            files=[("files", ("index.md", b"overwrite attack", "text/markdown"))],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "index.md" in resp.json()["detail"].lower() or "content file" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_post_assets_upload.py::TestUploadAssets::test_upload_index_md_rejected -v`
Expected: FAIL (200 instead of 400)

- [ ] **Step 3: Add index.md check to upload validation**

In `backend/api/posts.py`, after the filename sanitization and dotfile check (around line 438), add:

```python
        if filename == "index.md":
            raise HTTPException(status_code=400, detail="Cannot overwrite the post content file")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api/test_post_assets_upload.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/posts.py tests/test_api/test_post_assets_upload.py
git commit -m "fix: reject asset upload with filename index.md to prevent post corruption"
```

---

### Task 4: Validate PageOrderItem.file for path traversal

**Files:**
- Modify: `backend/schemas/admin.py:65-70`
- Test: `tests/test_services/test_admin_service.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_admin_service.py`:

```python
class TestPageOrderItemValidation:
    """PageOrderItem.file must reject path traversal."""

    def test_rejects_path_traversal_dotdot(self) -> None:
        from pydantic import ValidationError
        from backend.schemas.admin import PageOrderItem
        with pytest.raises(ValidationError):
            PageOrderItem(id="test", title="Test", file="../../.env")

    def test_rejects_absolute_path(self) -> None:
        from pydantic import ValidationError
        from backend.schemas.admin import PageOrderItem
        with pytest.raises(ValidationError):
            PageOrderItem(id="test", title="Test", file="/etc/passwd")

    def test_accepts_valid_relative_path(self) -> None:
        from backend.schemas.admin import PageOrderItem
        item = PageOrderItem(id="about", title="About", file="about.md")
        assert item.file == "about.md"

    def test_accepts_none_file(self) -> None:
        from backend.schemas.admin import PageOrderItem
        item = PageOrderItem(id="timeline", title="Timeline", file=None)
        assert item.file is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_admin_service.py::TestPageOrderItemValidation -v`
Expected: FAIL (no validation error raised)

- [ ] **Step 3: Add validator to PageOrderItem**

In `backend/schemas/admin.py`, add a `field_validator` to `PageOrderItem`:

```python
class PageOrderItem(BaseModel):
    """A single page in the reorder list."""

    id: str
    title: str
    file: str | None = None

    @field_validator("file")
    @classmethod
    def validate_file_path(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("Invalid file path")
        return v
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_services/test_admin_service.py::TestPageOrderItemValidation -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/admin.py tests/test_services/test_admin_service.py
git commit -m "fix: validate PageOrderItem.file to prevent path traversal"
```

---

### Task 5: Symlink-safe post deletion

**Files:**
- Modify: `backend/filesystem/content_manager.py:181-195`
- Test: `tests/test_services/test_content_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_content_manager.py`:

```python
class TestDeletePostSymlink:
    """Deleting a symlinked post directory must not delete the symlink target."""

    def test_delete_symlinked_post_does_not_delete_target(self, tmp_path: Path) -> None:
        from backend.filesystem.content_manager import ContentManager

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        posts_dir = content_dir / "posts"
        posts_dir.mkdir()
        (content_dir / "index.toml").write_text('[site]\ntitle = "Test"\n')
        (content_dir / "labels.toml").write_text("[labels]\n")

        # Real post directory
        real_dir = posts_dir / "2026-01-01-real-post"
        real_dir.mkdir()
        (real_dir / "index.md").write_text("---\ntitle: Real\n---\nContent")
        (real_dir / "image.png").write_bytes(b"PNG")

        # Symlink pointing to real_dir
        symlink_dir = posts_dir / "2026-01-01-old-name"
        symlink_dir.symlink_to(real_dir)

        cm = ContentManager(content_dir)

        # Delete the symlink (as if deleting the old-name post)
        cm.delete_post("posts/2026-01-01-old-name/index.md", delete_assets=True)

        # Real post directory must still exist
        assert real_dir.exists()
        assert (real_dir / "index.md").exists()
        assert (real_dir / "image.png").exists()
        # Symlink must be gone
        assert not symlink_dir.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_services/test_content_manager.py::TestDeletePostSymlink -v`
Expected: FAIL (shutil.rmtree follows symlink and deletes target)

- [ ] **Step 3: Fix delete_post to handle symlinks**

In `backend/filesystem/content_manager.py`, modify the `delete_post` method (around line 181-195). Before calling `shutil.rmtree`, check if `post_dir` is a symlink:

```python
        if delete_assets and full_path.name == "index.md":
            post_dir = full_path.parent
            resolved_dir = post_dir.resolve()
            parent = post_dir.parent
            # Remove symlinks in the parent directory pointing to this directory
            try:
                for item in parent.iterdir():
                    try:
                        if item.is_symlink() and item.resolve() == resolved_dir:
                            item.unlink()
                    except OSError as exc:
                        logger.warning("Failed to clean up symlink %s: %s", item, exc)
            except OSError as exc:
                logger.warning("Failed to iterate parent directory %s: %s", parent, exc)
            if post_dir.is_symlink():
                # Don't follow symlinks — just remove the symlink itself
                post_dir.unlink()
            else:
                shutil.rmtree(post_dir)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_services/test_content_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/filesystem/content_manager.py tests/test_services/test_content_manager.py
git commit -m "fix: prevent shutil.rmtree from following symlinks in post deletion"
```

---

### Task 6: Content-Disposition header escaping

**Files:**
- Modify: `backend/api/content.py:152`
- Test: `tests/test_api/test_content_api.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_content_api.py`:

```python
class TestContentDispositionEscaping:
    """Content-Disposition filename must be properly escaped."""

    async def test_filename_with_quotes_is_escaped(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        # Create a file with quotes in name
        posts_dir = app_settings.content_dir / "posts"
        hello_dir = posts_dir / "2026-02-02-hello-world"
        hello_dir.mkdir(exist_ok=True)
        (hello_dir / "index.md").write_text(
            "---\ntitle: Hello\ncreated_at: 2026-02-02T22:21:29+00:00\nauthor: admin\nlabels: []\n---\nContent\n"
        )
        # Create a file with a quote in the name
        tricky_name = 'file"name.svg'
        (hello_dir / tricky_name).write_bytes(b"<svg></svg>")

        resp = await client.get(f"/content/posts/2026-02-02-hello-world/{tricky_name}")
        # The response should be valid — Content-Disposition should not have unescaped quotes
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        if cd:
            # Should not have broken quoting like: attachment; filename="file"name.svg"
            # Count quotes — should be exactly 2 (opening and closing)
            assert cd.count('"') == 2 or "filename*=" in cd
```

Note: This test may need adjustment based on the test infrastructure for the content API. Check the existing tests in `test_content_api.py` for the fixture setup pattern, and follow it. The key assertion is that filenames with `"` chars produce valid headers.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_content_api.py::TestContentDispositionEscaping -v`
Expected: FAIL

- [ ] **Step 3: Fix the Content-Disposition header**

In `backend/api/content.py`, replace line 152:

```python
    # Old:
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    # New:
    safe_filename = filename.replace("\\", "\\\\").replace('"', '\\"')
    headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api/test_content_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/content.py tests/test_api/test_content_api.py
git commit -m "fix: escape Content-Disposition filename to prevent header injection"
```

---

### Task 7: Validate TOML parents field type

**Files:**
- Modify: `backend/filesystem/toml_manager.py:138-143`
- Test: `tests/test_services/test_toml_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_toml_manager.py`:

```python
class TestNonIterableParents:
    """Non-iterable parents value in labels.toml must not crash."""

    def test_integer_parents_skipped_gracefully(self, tmp_path: Path) -> None:
        labels_path = tmp_path / "labels.toml"
        labels_path.write_text(
            '[labels.broken]\nnames = ["broken"]\nparents = 42\n'
            '[labels.good]\nnames = ["good"]\n'
        )
        result = parse_labels_config(tmp_path)
        # The broken label should have empty parents (42 is not iterable)
        assert result["broken"].parents == []
        # Good label is unaffected
        assert "good" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_services/test_toml_manager.py::TestNonIterableParents -v`
Expected: FAIL (TypeError: cannot iterate over int)

- [ ] **Step 3: Add type check for raw_parents**

In `backend/filesystem/toml_manager.py`, around line 138-142, add a type guard:

```python
        raw_parents = label_info.get("parents", [])
        if not isinstance(raw_parents, list):
            logger.warning(
                "Skipping non-list 'parents' for label %r in labels.toml", label_id
            )
            raw_parents = []
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_services/test_toml_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/filesystem/toml_manager.py tests/test_services/test_toml_manager.py
git commit -m "fix: handle non-iterable parents field in labels.toml gracefully"
```

---

### Task 8: Fix pandoc renderer error handling

**Files:**
- Modify: `backend/pandoc/renderer.py:317-341`
- Test: `tests/test_rendering/test_pandoc_server.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_rendering/test_pandoc_server.py`:

```python
class TestRendererHttpxErrorHandling:
    """Renderer must catch all httpx transport errors, not just NetworkError and ReadTimeout."""

    async def test_write_timeout_raises_render_error(self) -> None:
        from backend.pandoc.renderer import RenderError, _render_markdown
        from backend.pandoc.renderer import _sanitize_html
        import httpx

        with patch("backend.pandoc.renderer._server") as mock_server, \
             patch("backend.pandoc.renderer._http_client") as mock_client:
            mock_server.base_url = "http://localhost:3000"
            mock_client.post = AsyncMock(side_effect=httpx.WriteTimeout("write timeout"))
            with pytest.raises(RenderError, match="timed out"):
                await _render_markdown("# test", from_format="markdown", sanitizer=_sanitize_html)

    async def test_pool_timeout_raises_render_error(self) -> None:
        from backend.pandoc.renderer import RenderError, _render_markdown
        from backend.pandoc.renderer import _sanitize_html
        import httpx

        with patch("backend.pandoc.renderer._server") as mock_server, \
             patch("backend.pandoc.renderer._http_client") as mock_client:
            mock_server.base_url = "http://localhost:3000"
            mock_client.post = AsyncMock(side_effect=httpx.PoolTimeout("pool timeout"))
            with pytest.raises(RenderError, match="timed out"):
                await _render_markdown("# test", from_format="markdown", sanitizer=_sanitize_html)

    async def test_non_200_with_no_error_key_raises_render_error(self) -> None:
        from backend.pandoc.renderer import RenderError, _render_markdown
        from backend.pandoc.renderer import _sanitize_html

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"message": "internal error"}

        with patch("backend.pandoc.renderer._server") as mock_server, \
             patch("backend.pandoc.renderer._http_client") as mock_client:
            mock_server.base_url = "http://localhost:3000"
            mock_client.post = AsyncMock(return_value=mock_response)
            with pytest.raises(RenderError, match="non-2xx"):
                await _render_markdown("# test", from_format="markdown", sanitizer=_sanitize_html)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rendering/test_pandoc_server.py::TestRendererHttpxErrorHandling -v`
Expected: FAIL

- [ ] **Step 3: Fix the renderer error handling**

In `backend/pandoc/renderer.py`, modify `_render_markdown` (lines 317-341):

1. Catch `httpx.TimeoutException` (parent of ReadTimeout, WriteTimeout, PoolTimeout, ConnectTimeout) instead of just `httpx.ReadTimeout`:

```python
    try:
        response = await client.post(f"{server.base_url}/", json=payload, headers=headers)
    except httpx.NetworkError:
        logger.warning("Pandoc server network error, attempting restart")
        await server.ensure_running()
        try:
            response = await client.post(f"{server.base_url}/", json=payload, headers=headers)
        except Exception as retry_exc:
            msg = f"Pandoc server unreachable after restart: {retry_exc}"
            raise RenderError(msg) from retry_exc
    except httpx.TimeoutException:
        raise RenderError(f"Pandoc rendering timed out after {_RENDER_TIMEOUT}s") from None
```

2. After parsing JSON, check for non-2xx status:

```python
    try:
        data = response.json()
    except ValueError:
        raise RenderError(
            f"Pandoc server returned non-JSON response (HTTP {response.status_code})"
        ) from None
    if "error" in data:
        raise RenderError(f"Pandoc rendering error: {str(data['error'])[:200]}")
    if response.status_code >= 300:
        raise RenderError(
            f"Pandoc server returned non-2xx status ({response.status_code})"
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_rendering/test_pandoc_server.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pandoc/renderer.py tests/test_rendering/test_pandoc_server.py
git commit -m "fix: catch all httpx timeout types and non-2xx pandoc responses"
```

---

### Task 9: Fix regex backtracking in get_plain_excerpt

**Files:**
- Modify: `backend/filesystem/content_manager.py:242`
- Test: `tests/test_services/test_content_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_services/test_content_manager.py`:

```python
class TestPlainExcerptRegexSafety:
    """get_plain_excerpt must not exhibit quadratic regex behavior."""

    def test_adversarial_asterisks_completes_quickly(self, tmp_path: Path) -> None:
        import time
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "index.toml").write_text('[site]\ntitle = "T"\n')
        (content_dir / "labels.toml").write_text("[labels]\n")
        cm = ContentManager(content_dir)

        # Adversarial: many * chars that don't close — this triggers backtracking
        # with the old pattern [*_]{1,3}([^*_]+)[*_]{1,3}
        adversarial = "* " * 5000
        post_data = PostData(
            file_path="posts/test.md",
            title="Test",
            author="admin",
            created_at="2026-01-01T00:00:00+00:00",
            modified_at="2026-01-01T00:00:00+00:00",
            content=adversarial,
            raw_content=adversarial,
            labels=[],
        )

        start = time.monotonic()
        cm.get_plain_excerpt(post_data)
        elapsed = time.monotonic() - start
        # Must complete in under 1 second (was potentially minutes with backtracking)
        assert elapsed < 1.0
```

- [ ] **Step 2: Run test to verify it fails or is slow**

Run: `pytest tests/test_services/test_content_manager.py::TestPlainExcerptRegexSafety -v --timeout=10`
Expected: FAIL or very slow

- [ ] **Step 3: Fix the regex**

In `backend/filesystem/content_manager.py`, line 242, replace the backtracking-prone regex with an atomic alternative using possessive-like behavior. The simplest fix is to use a non-greedy match or restructure:

```python
# Old:
stripped = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", stripped)
# New — use a more specific pattern that doesn't backtrack:
stripped = re.sub(r"(\*{1,3}|_{1,3})(.+?)\1", r"\2", stripped)
```

Note: This changes semantics slightly (requires matching delimiters) but is more correct for markdown bold/italic stripping and avoids backtracking. If this causes test failures, an alternative is:
```python
stripped = re.sub(r"[*_]+", "", stripped)
```
which simply strips all `*` and `_` chars (good enough for plain-text excerpt generation).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_services/test_content_manager.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/filesystem/content_manager.py tests/test_services/test_content_manager.py
git commit -m "fix: prevent regex backtracking in get_plain_excerpt"
```

---

### Task 10: Use .get() for facebook_callback external data

**Files:**
- Modify: `backend/api/crosspost.py:902`
- Test: `tests/test_api/test_crosspost_robustness.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_crosspost_robustness.py`:

```python
class TestFacebookCallbackMissingPages:
    """facebook_callback must return 502 if 'pages' key missing from token exchange result."""

    async def test_missing_pages_key_returns_502(self, client: AsyncClient) -> None:
        headers = await _login(client)

        with patch("backend.api.crosspost.exchange_facebook_oauth_token", new_callable=AsyncMock) as mock_exchange, \
             patch("backend.api.crosspost._oauth_state_store") as mock_store:
            # State store returns valid pending data
            mock_store.pop.return_value = {
                "app_id": "test_app",
                "app_secret": "test_secret",
                "redirect_uri": "http://localhost/callback",
                "user_id": 1,
            }
            # Token exchange returns result WITHOUT "pages" key
            mock_exchange.return_value = {"access_token": "tok"}

            resp = await client.get("/api/crosspost/facebook/callback?code=abc&state=test-state", headers=headers)

        assert resp.status_code == 502
```

Note: This test may need adjustment based on the existing test fixtures and patterns in `test_crosspost_robustness.py`. Check the file for the correct fixture setup. The key assertion is that missing `pages` key returns 502, not 500.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_crosspost_robustness.py::TestFacebookCallbackMissingPages -v`
Expected: FAIL (500/KeyError instead of 502)

- [ ] **Step 3: Use .get() for pages key**

In `backend/api/crosspost.py`, replace line 902:

```python
    # Old:
    raw_pages = result["pages"]
    # New:
    raw_pages = result.get("pages")
    if raw_pages is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook API response missing page data",
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api/test_crosspost_robustness.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/crosspost.py tests/test_api/test_crosspost_robustness.py
git commit -m "fix: use .get() for facebook callback pages key, return 502 on missing"
```

---

### Task 11: Wrap scan_content_files in asyncio.to_thread

**Files:**
- Modify: `backend/api/sync.py:138, 375`
- Test: `tests/test_services/test_sync_service.py`

- [ ] **Step 1: Write failing test**

This is a structural fix — the test verifies the function is called via `asyncio.to_thread`. Add to `tests/test_services/test_sync_service.py`:

```python
class TestScanContentFilesAsync:
    """scan_content_files must be called via asyncio.to_thread from async endpoints."""

    async def test_sync_status_calls_scan_in_thread(self) -> None:
        """Verify scan_content_files is wrapped in to_thread in sync.py."""
        import ast
        import inspect
        from backend.api import sync as sync_module

        source = inspect.getsource(sync_module.sync_status)
        tree = ast.parse(source)
        # Check that scan_content_files is called within an await expression
        # (indicating asyncio.to_thread wrapping)
        found_to_thread = "to_thread" in source and "scan_content_files" in source
        found_bare_call = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "scan_content_files":
                    found_bare_call = True
                elif isinstance(func, ast.Attribute) and func.attr == "scan_content_files":
                    found_bare_call = True
        # Either wrapped in to_thread or not called bare
        assert found_to_thread or not found_bare_call, (
            "scan_content_files is called without asyncio.to_thread wrapping"
        )
```

Actually, a simpler approach: just verify via integration test that the endpoint doesn't block. But the simplest test is an AST inspection. However, this test is fragile. A better approach is to just make the change and verify existing tests still pass.

Skip the test for this task — it's a mechanical refactoring. Verify with existing sync tests.

- [ ] **Step 1: Wrap scan_content_files calls in asyncio.to_thread**

In `backend/api/sync.py`:

Line 138 — change:
```python
    # Old:
    server_current = scan_content_files(content_manager.content_dir)
    # New:
    server_current = await asyncio.to_thread(scan_content_files, content_manager.content_dir)
```

Line 375 — change:
```python
    # Old:
    current_files = scan_content_files(content_dir)
    # New:
    current_files = await asyncio.to_thread(scan_content_files, content_dir)
```

Make sure `import asyncio` is present at the top of the file.

- [ ] **Step 2: Run existing sync tests**

Run: `pytest tests/test_services/test_sync_service.py tests/test_api/test_api_integration.py -v -k sync`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/api/sync.py
git commit -m "fix: wrap scan_content_files in asyncio.to_thread to avoid blocking event loop"
```

---

### Task 12: Fix _upsert_social_account race condition

**Files:**
- Modify: `backend/api/crosspost.py:97-132`
- Test: `tests/test_api/test_crosspost_helpers.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_crosspost_helpers.py`:

```python
class TestUpsertSocialAccountAtomicity:
    """_upsert_social_account must not delete account if re-create will fail."""

    async def test_uses_update_instead_of_delete_create(self) -> None:
        """After DuplicateAccountError, the function should update the existing
        account rather than delete-then-create, to avoid a window where the user
        has no account."""
        # Verify the function uses session.merge or UPDATE instead of delete+create
        import ast
        import inspect
        from backend.api import crosspost

        source = inspect.getsource(crosspost._upsert_social_account)
        # The key fix: the function should not delete the existing account
        # before creating a new one. It should use a single operation.
        # Check that delete_social_account is no longer called.
        assert "delete_social_account" not in source, (
            "_upsert_social_account should update-in-place, not delete-then-create"
        )
```

This test is too fragile for a real test. Instead, let's write a test that verifies the behavior:

```python
class TestUpsertSocialAccountRace:
    """_upsert_social_account must handle concurrent duplicate gracefully."""

    async def test_concurrent_duplicate_preserves_existing_account(self) -> None:
        """If re-create fails after replacing existing, user must not lose account."""
        from unittest.mock import AsyncMock, patch, MagicMock
        from backend.api.crosspost import _upsert_social_account
        from backend.services.crosspost_service import DuplicateAccountError

        session = AsyncMock()
        account_data = MagicMock()

        # First create raises DuplicateAccountError
        # get_social_accounts returns an existing account
        # The function should update the existing account rather than delete+create
        existing_account = MagicMock()
        existing_account.platform = "bluesky"
        existing_account.account_name = "test.bsky.social"
        existing_account.id = 42

        with patch("backend.api.crosspost.create_social_account", new_callable=AsyncMock) as mock_create, \
             patch("backend.api.crosspost.get_social_accounts", new_callable=AsyncMock) as mock_get, \
             patch("backend.api.crosspost.update_social_account", new_callable=AsyncMock) as mock_update:
            # First create fails, second would also fail
            mock_create.side_effect = DuplicateAccountError("dup")
            mock_get.return_value = [existing_account]

            await _upsert_social_account(
                session, 1, account_data, "secret", "bluesky", "test.bsky.social"
            )

            # Should have called update, not delete+create
            mock_update.assert_called_once()
```

Actually, the simplest fix is to change `_upsert_social_account` to update the existing account in-place rather than delete+create. But this requires adding an `update_social_account` function which is a larger change.

A simpler approach: wrap the delete+create in a try/except and if the re-create fails, roll back and re-create the original. But that's complex too.

The simplest safe fix: just use a transaction savepoint around the delete+create, so if re-create fails, the delete is rolled back.

Let me reconsider. The actual fix should be: instead of delete-then-create, use `session.merge()` or an UPDATE query to modify the existing account in-place. But we need to understand the `create_social_account` and `delete_social_account` functions.

For the plan, let's use a simpler approach: catch the second DuplicateAccountError and if it happens, restore the deleted account. The current code already catches it and returns 409. The issue is that the old account has been deleted. The fix is to use a savepoint:

```python
async with session.begin_nested():
    await delete_social_account(session, acct.id, user_id)
    try:
        await create_social_account(session, user_id, account_data, secret_key)
    except DuplicateAccountError:
        raise  # Savepoint rollback restores the deleted account
```

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_crosspost_helpers.py` a test verifying that a failed re-create doesn't lose the original account. The test should mock `create_social_account` to always raise `DuplicateAccountError` and verify the existing account is not deleted.

- [ ] **Step 2: Fix _upsert_social_account to use savepoint**

In `backend/api/crosspost.py`, modify `_upsert_social_account` (lines 97-132):

```python
async def _upsert_social_account(
    session: AsyncSession,
    user_id: int,
    account_data: SocialAccountCreate,
    secret_key: str,
    platform: str,
    account_name: str,
) -> None:
    """Create a social account, replacing an existing one with the same platform+name."""
    try:
        await create_social_account(session, user_id, account_data, secret_key)
    except DuplicateAccountError:
        existing = await get_social_accounts(session, user_id)
        replaced = False
        for acct in existing:
            if acct.platform == platform and acct.account_name == account_name:
                # Use a savepoint so if re-create fails, the delete is rolled back
                async with session.begin_nested():
                    await delete_social_account(session, acct.id, user_id)
                    try:
                        await create_social_account(session, user_id, account_data, secret_key)
                    except DuplicateAccountError:
                        logger.error(
                            "Race condition: failed to re-create %s account %s after deletion",
                            platform,
                            account_name,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Could not connect {platform} account due to a conflict. Please try again.",
                        ) from None
                replaced = True
                break
        if not replaced:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{platform.capitalize()} account already exists",
            ) from None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_api/test_crosspost_helpers.py tests/test_api/test_crosspost_robustness.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add backend/api/crosspost.py tests/test_api/test_crosspost_helpers.py
git commit -m "fix: use savepoint in _upsert_social_account to prevent account loss on race"
```

---

## Chunk 2: Complex fixes

### Task 13: Fix update_profile atomicity

**Files:**
- Modify: `backend/api/auth.py:504-533`
- Test: `tests/test_api/test_auth_profile.py`

The core problem: post files are rewritten with the new author, but if `rebuild_cache` or the final `session.commit()` fails, the DB rolls back while the filesystem retains the new author. The fix: collect files to update, write them all, and if anything downstream fails, revert the files.

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_auth_profile.py`:

```python
class TestProfileUpdateAtomicity:
    """Username change must be atomic: if cache rebuild fails, filesystem must be reverted."""

    async def test_filesystem_reverted_on_rebuild_cache_failure(
        self, client: AsyncClient, app_settings: Settings
    ) -> None:
        token = await _login(client)

        # Create a post first
        resp = await client.post(
            "/api/posts",
            json={"title": "Atomic Test", "body": "Content"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        file_path = resp.json()["file_path"]

        # Now try to change username — but make rebuild_cache fail
        with patch("backend.api.auth.rebuild_cache", new_callable=AsyncMock, side_effect=RuntimeError("cache boom")):
            resp = await client.patch(
                "/api/auth/me",
                json={"username": "newname"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Should fail (500)
        assert resp.status_code == 500

        # Filesystem must still have the OLD author (admin), not the new one
        post_path = app_settings.content_dir / file_path
        content = post_path.read_text()
        assert "author: admin" in content
        assert "author: newname" not in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_auth_profile.py::TestProfileUpdateAtomicity -v`
Expected: FAIL (filesystem has "newname" but should have "admin")

- [ ] **Step 3: Implement filesystem rollback in update_profile**

In `backend/api/auth.py`, modify the `update_profile` function (lines 504-533). Wrap the file update + cache rebuild in a try/except that reverts files on failure:

```python
    if needs_file_update:
        new_username = user.username
        logger.info(
            "Username change: %s -> %s, updating author in posts",
            old_username,
            new_username,
        )
        async with content_write_lock:
            try:
                count = await asyncio.to_thread(
                    _update_author_in_posts,
                    content_manager,
                    old_username,
                    new_username,
                )
                logger.info("Updated author in %d post(s)", count)
            except OSError as exc:
                logger.error("Failed to update author in posts: %s", exc)
                await session.rollback()
                raise HTTPException(
                    status_code=500,
                    detail="Failed to update author in post files",
                ) from exc

            try:
                await rebuild_cache(session, content_manager)
            except Exception as exc:
                logger.error(
                    "Cache rebuild failed after author update, reverting files: %s", exc
                )
                # Revert filesystem changes
                try:
                    await asyncio.to_thread(
                        _update_author_in_posts,
                        content_manager,
                        new_username,
                        old_username,
                    )
                except OSError as revert_exc:
                    logger.error("Failed to revert author in posts: %s", revert_exc)
                await session.rollback()
                raise HTTPException(
                    status_code=500,
                    detail="Failed to update author",
                ) from exc
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api/test_auth_profile.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/auth.py tests/test_api/test_auth_profile.py
git commit -m "fix: revert filesystem on cache rebuild failure during profile update"
```

---

### Task 14: Fix rebuild_cache visibility to concurrent readers

**Files:**
- Modify: `backend/services/cache_service.py:24-137`
- Test: `tests/test_services/test_cache_rebuild_resilience.py`

The core problem: `rebuild_cache` deletes all cache rows, then repopulates them, then commits. During the window between delete and commit, concurrent readers see empty results.

The fix: use a dedicated session for the rebuild, and do all work within a single transaction. Since SQLite uses WAL mode, readers will see the old data until the transaction commits. The key insight: `rebuild_cache` already commits at the end (line 137). The problem is that it deletes rows and flushes midway. The fix is to ensure all the DELETEs and INSERTs happen in a single transaction that only becomes visible on final commit.

Actually, looking at the code more carefully: `rebuild_cache` takes a session parameter and calls `session.commit()` at the end. The deletes are followed by `session.flush()` calls (which don't commit to disk in SQLite WAL mode — they're only visible within the same session). In WAL mode, other connections see the committed state until this transaction commits. So this should actually be fine in WAL mode...

Wait — the issue is that `rebuild_cache` is called from `update_profile` at line 530, using the SAME session as the profile update. And `rebuild_cache` calls `session.commit()` at line 137, which commits EVERYTHING including the partially-flushed user changes. This is the real problem: rebuild_cache's commit commits the outer session's changes too.

The fix: have `rebuild_cache` use its own session (a separate database connection), so its commit doesn't affect the caller's transaction. This also fixes the visibility issue: in WAL mode, the rebuild happens in its own transaction and becomes visible atomically on commit.

- [ ] **Step 1: Write test for rebuild_cache using separate session**

Add to `tests/test_services/test_cache_rebuild_resilience.py`:

```python
class TestRebuildCacheIsolation:
    """rebuild_cache must use its own session to avoid committing caller's transaction."""

    async def test_rebuild_does_not_commit_callers_session(self) -> None:
        """Verify rebuild_cache creates its own session and doesn't commit the caller's."""
        import ast
        import inspect
        from backend.services import cache_service

        source = inspect.getsource(cache_service.rebuild_cache)
        # The function should create its own session (via async_sessionmaker or similar)
        # and not call commit on the passed-in session
        # This is a structural test — verify the function signature accepts a sessionmaker
        # or creates its own session
        tree = ast.parse(source)

        # Check that the function does NOT call session.commit() on the passed-in session
        # It should use its own session via a context manager
        assert "async_sessionmaker" in source or "session_factory" in source or "get_session" in source, (
            "rebuild_cache should use its own session, not the caller's"
        )
```

Actually, structural tests are fragile. Let's write a behavioral test instead:

- [ ] **Step 1: Write behavioral test**

The test verifies that during rebuild_cache, concurrent reads still return data. This is hard to test directly. Instead, let's test that rebuild_cache accepts a `session_factory` parameter and creates its own session:

Modify `rebuild_cache` to accept an `async_sessionmaker` instead of (or in addition to) a raw session, and create its own session internally. This ensures atomicity.

Actually, the simplest fix that addresses both the visibility problem AND the "commits caller's session" problem: change `rebuild_cache` to accept a `session_factory` (an `async_sessionmaker`), create its own session, do all work in it, and commit only at the end.

- [ ] **Step 1: Refactor rebuild_cache to use its own session**

Modify `backend/services/cache_service.py`:

```python
async def rebuild_cache(
    session_factory: async_sessionmaker[AsyncSession],
    content_manager: ContentManager,
) -> tuple[int, list[str]]:
    """Rebuild all cache tables from filesystem.

    Uses its own database session to avoid interfering with the caller's
    transaction and to ensure atomic visibility to concurrent readers.
    """
    async with session_factory() as session:
        # ... existing logic, but using this new session ...
        await session.commit()
    return post_count, warnings
```

This is a significant refactor — all callers of `rebuild_cache` need to pass a session factory instead of a session. The callers are:
1. `backend/main.py` (lifespan) — has access to `async_sessionmaker`
2. `backend/api/auth.py` (update_profile) — needs to get session factory from dependency
3. `backend/api/sync.py` (sync_commit) — needs to get session factory from dependency

- [ ] **Step 2: Update all callers**

In `backend/main.py` lifespan, pass the session factory.
In `backend/api/auth.py` and `backend/api/sync.py`, add a dependency to get the session factory.

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v -x`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/cache_service.py backend/main.py backend/api/auth.py backend/api/sync.py tests/test_services/test_cache_rebuild_resilience.py
git commit -m "refactor: rebuild_cache uses its own session for atomic visibility"
```

---

### Task 15: Sync status under read lock (issue 10)

**Files:**
- Modify: `backend/api/sync.py:119-168`

The `sync_status` endpoint reads the filesystem without holding `content_write_lock`. The fix: acquire a read lock (or the write lock as a short hold) while scanning.

Actually, looking at the code — `content_write_lock` is an `AsyncWriteLock` (a simple asyncio.Lock). All mutation endpoints hold it during writes. The `sync_status` endpoint reads the filesystem without it, so its scan can race with a concurrent write.

The simplest fix: acquire `content_write_lock` during the filesystem scan portion of `sync_status`. This serializes the scan with writes, ensuring a consistent snapshot. The lock hold is brief (just the scan).

- [ ] **Step 1: Acquire lock during scan**

In `backend/api/sync.py`, modify `sync_status` to acquire `content_write_lock` during the scan:

```python
@router.post("/status", response_model=SyncStatusResponse)
async def sync_status(
    body: SyncStatusRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    git_service: Annotated[GitService, Depends(get_git_service)],
    content_write_lock: Annotated[AsyncWriteLock, Depends(get_content_write_lock)],
    user: Annotated[User, Depends(require_admin)],
) -> SyncStatusResponse:
    # ... client_manifest parsing ...

    async with content_write_lock:
        server_manifest = await get_server_manifest(session)
        server_current = await asyncio.to_thread(scan_content_files, content_manager.content_dir)

    plan = compute_sync_plan(client_manifest, server_manifest, server_current)
    # ... rest of function ...
```

Note: `content_write_lock` is already a dependency. Add it if not present. Add `import asyncio` if not present.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_services/test_sync_service.py tests/test_api/test_api_integration.py -v -k sync`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/api/sync.py
git commit -m "fix: hold content_write_lock during sync_status filesystem scan"
```

---

## Parallelization Guide

**Independent tasks (can all run in parallel):**
- Tasks 1-12 are all independent of each other (they modify different files)

**Sequential tasks:**
- Task 13 (update_profile atomicity) depends on Task 14 (rebuild_cache refactor) because the fix to update_profile calls rebuild_cache, and if rebuild_cache's signature changes, the call site must match

**Recommended execution order:**
1. Run Tasks 1-12 in parallel (all independent)
2. Run Task 14 (rebuild_cache refactor)
3. Run Task 13 (update_profile atomicity — uses new rebuild_cache signature)
4. Run Task 15 (sync_status lock)
5. Final `just check` to verify everything passes together

---
