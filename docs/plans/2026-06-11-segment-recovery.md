# Resend Segment Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow admins to recover from accidental Resend segment deletion by disabling and re-enabling subscriptions, which now verifies the stored segment still exists and creates a fresh one if it doesn't.

**Architecture:** Add `check_segment_exists` to `resend_client.py`, update `_prepare_enable` in `subscription_service.py` to call it when a segment ID is already stored, and show a recovery hint in `SubscriptionsPanel.tsx` when the segment is unreachable.

**Tech Stack:** Python/FastAPI backend, httpx (Resend HTTP client), React/TypeScript frontend, pytest + pytest-asyncio, monkeypatch for HTTP mocking.

---

### Task 1: Add `check_segment_exists` to `resend_client.py`

**Files:**
- Modify: `backend/services/resend_client.py`
- Test: `tests/test_services/test_resend_client.py`

- [ ] **Step 1: Write the three failing tests**

Add to the bottom of `tests/test_services/test_resend_client.py`:

```python
@pytest.mark.asyncio
async def test_check_segment_exists_returns_true_on_2xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/audiences/seg_1"
        return httpx.Response(200, json={"id": "seg_1", "name": "AgBlogger subscribers"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    result = await resend_client.check_segment_exists(api_key="re_x", segment_id="seg_1")
    assert result is True


@pytest.mark.asyncio
async def test_check_segment_exists_returns_false_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Audience not found"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    result = await resend_client.check_segment_exists(api_key="re_x", segment_id="seg_gone")
    assert result is False


@pytest.mark.asyncio
async def test_check_segment_exists_reraises_on_other_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError, match="Invalid API key"):
        await resend_client.check_segment_exists(api_key="re_bad", segment_id="seg_1")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
just test-backend -- tests/test_services/test_resend_client.py::test_check_segment_exists_returns_true_on_2xx tests/test_services/test_resend_client.py::test_check_segment_exists_returns_false_on_404 tests/test_services/test_resend_client.py::test_check_segment_exists_reraises_on_other_error -v
```

Expected: all three FAIL with `AttributeError: module ... has no attribute 'check_segment_exists'`.

- [ ] **Step 3: Implement `check_segment_exists`**

Add after the `create_segment` function in `backend/services/resend_client.py` (after line 112):

```python
async def check_segment_exists(*, api_key: str, segment_id: str) -> bool:
    """Return True if the segment exists in Resend, False if it has been deleted.

    Re-raises ResendError for non-404 failures (auth errors, network errors, etc.)
    so callers cannot accidentally swallow real problems.
    """
    try:
        response = await _get_client().get(
            f"{_API_BASE}/audiences/{segment_id}",
            headers=_headers(api_key),
        )
    except httpx.HTTPError as exc:
        logger.warning("Resend request to /audiences/%s failed: %s", segment_id, exc)
        raise ResendError("Could not reach the email provider") from exc
    if response.status_code == 404:
        return False
    if response.status_code >= 400:
        raise ResendError(_extract_message(response))
    return True
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
just test-backend -- tests/test_services/test_resend_client.py::test_check_segment_exists_returns_true_on_2xx tests/test_services/test_resend_client.py::test_check_segment_exists_returns_false_on_404 tests/test_services/test_resend_client.py::test_check_segment_exists_reraises_on_other_error -v
```

Expected: all three PASS.

- [ ] **Step 5: Run the full resend client test file to check for regressions**

```bash
just test-backend -- tests/test_services/test_resend_client.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/resend_client.py tests/test_services/test_resend_client.py
git commit -m "feat: add check_segment_exists to resend client"
```

---

### Task 2: Update `_prepare_enable` to verify and recover a stale segment

**Files:**
- Modify: `backend/services/subscription_service.py`
- Test: `tests/test_services/test_subscription_settings.py`

The current `_prepare_enable` accepts any stored `resend_segment_id` unconditionally. We
need to verify it still exists via `check_segment_exists` and clear it if not, so the
existing creation path takes over.

We also need to update `test_enable_twice_creates_segment_once` — it will now fail because
the second enable call triggers `check_segment_exists`, which is not yet monkeypatched.

- [ ] **Step 1: Write the new failing tests**

Add to the bottom of `tests/test_services/test_subscription_settings.py`:

```python
@pytest.mark.asyncio
async def test_enable_with_valid_segment_does_not_recreate(
    session: AsyncSession, monkeypatch
) -> None:
    create_calls: list[int] = []

    async def _counting_create(*, api_key: str, name: str) -> str:
        create_calls.append(1)
        return "seg_original"

    async def _exists_true(*, api_key: str, segment_id: str) -> bool:
        assert segment_id == "seg_original"
        return True

    monkeypatch.setattr(resend_client, "create_segment", _counting_create)
    monkeypatch.setattr(resend_client, "check_segment_exists", _exists_true)

    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
    )
    # Enable a second time — segment still exists, no re-creation.
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
    )
    assert len(create_calls) == 1
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_original"


@pytest.mark.asyncio
async def test_enable_with_stale_segment_recreates(
    session: AsyncSession, monkeypatch
) -> None:
    create_calls: list[str] = []

    async def _counting_create(*, api_key: str, name: str) -> str:
        seg_id = f"seg_{len(create_calls) + 1}"
        create_calls.append(seg_id)
        return seg_id

    async def _exists_false(*, api_key: str, segment_id: str) -> bool:
        return False

    monkeypatch.setattr(resend_client, "create_segment", _counting_create)
    monkeypatch.setattr(resend_client, "check_segment_exists", _exists_false)

    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
    )
    # Enable again — segment probe says it's gone, so a new one is created.
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, api_key="re_x", from_email="a@b.com"
    )
    assert len(create_calls) == 2
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_2"
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
just test-backend -- tests/test_services/test_subscription_settings.py::test_enable_with_valid_segment_does_not_recreate tests/test_services/test_subscription_settings.py::test_enable_with_stale_segment_recreates -v
```

Expected: both FAIL — `test_enable_with_valid_segment_does_not_recreate` errors because `check_segment_exists` is not called yet (but the monkeypatch would cause an error or the test assertion about `create_calls == 1` could fail depending on timing), and `test_enable_with_stale_segment_recreates` fails because the stale segment is accepted without verification.

- [ ] **Step 3: Update `_prepare_enable` in `backend/services/subscription_service.py`**

Replace the entire `_prepare_enable` function (lines 152–170):

```python
async def _prepare_enable(
    session: AsyncSession, row: SubscriptionSettings, secret_key: str
) -> None:
    """Validate compliance config and ensure a live Resend segment exists before enabling."""
    if not row.resend_api_key_encrypted:
        raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
    missing = [f for f in _REQUIRED_TO_ENABLE if not getattr(row, f)]
    if missing:
        raise EnablePreconditionError("Set these before enabling: " + ", ".join(missing))
    api_key = decrypt_api_key(row, secret_key)
    if api_key is None:
        raise EnablePreconditionError("A Resend API key is required to enable subscriptions.")
    if row.resend_segment_id:
        exists = await resend_client.check_segment_exists(
            api_key=api_key, segment_id=row.resend_segment_id
        )
        if not exists:
            row.resend_segment_id = None
    if not row.resend_segment_id:
        # Accepted tradeoff: if the commit fails after this succeeds, the created
        # Resend segment is orphaned. Acceptable for this admin-only path (no data
        # loss / security impact).
        row.resend_segment_id = await resend_client.create_segment(
            api_key=api_key, name=_SEGMENT_NAME
        )
```

- [ ] **Step 4: Fix the existing `test_enable_twice_creates_segment_once` test**

The test at the bottom of `tests/test_services/test_subscription_settings.py` no longer works because the second enable now calls `check_segment_exists`. Add a monkeypatch for it:

```python
@pytest.mark.asyncio
async def test_enable_twice_creates_segment_once(session: AsyncSession, monkeypatch) -> None:
    calls: list[int] = []

    async def _counting_create_segment(*, api_key: str, name: str) -> str:
        calls.append(1)
        return "seg_auto"

    async def _fake_check_segment_exists(*, api_key: str, segment_id: str) -> bool:
        return True

    monkeypatch.setattr(resend_client, "create_segment", _counting_create_segment)
    monkeypatch.setattr(resend_client, "check_segment_exists", _fake_check_segment_exists)

    full_kwargs = {
        "api_key": "re_x",
        "from_email": "a@b.com",
    }
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, **full_kwargs
    )
    await subscription_service.update_settings(
        session, secret_key=SECRET, enabled=True, **full_kwargs
    )
    # Second enable reuses the stored resend_segment_id rather than re-creating.
    assert len(calls) == 1
    row = await subscription_service._get_row(session)
    assert row is not None
    assert row.resend_segment_id == "seg_auto"
```

- [ ] **Step 5: Run all subscription settings tests**

```bash
just test-backend -- tests/test_services/test_subscription_settings.py -v
```

Expected: all tests PASS (including the two new ones and the updated existing one).

- [ ] **Step 6: Run the full backend test suite to check for regressions**

```bash
just test-backend
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/subscription_service.py tests/test_services/test_subscription_settings.py
git commit -m "feat: verify segment exists on re-enable, recreate if stale"
```

---

### Task 3: Add recovery hint to `SubscriptionsPanel.tsx`

**Files:**
- Modify: `frontend/src/components/admin/SubscriptionsPanel.tsx`

When subscriptions are enabled but `subscriber_count` is `null`, the segment is unreachable
(either deleted or temporarily unavailable). Show an inline hint so the admin knows to
disable and re-enable to trigger recovery.

- [ ] **Step 1: Update the subscriber count section**

In `frontend/src/components/admin/SubscriptionsPanel.tsx`, find this block (around line 226):

```tsx
        <div className="ml-auto flex items-center gap-2 text-sm text-muted">
          <span className="text-xs uppercase tracking-wide">Subscribers</span>
          <span className="font-semibold text-ink text-base">
            {(settings?.subscriber_count ?? 0).toLocaleString()}
          </span>
        </div>
```

Replace it with:

```tsx
        <div className="ml-auto flex items-center gap-2 text-sm text-muted">
          <span className="text-xs uppercase tracking-wide">Subscribers</span>
          {settings?.enabled === true && settings.subscriber_count === null ? (
            <span className="text-xs text-amber-600 dark:text-amber-400">
              Segment unreachable — disable then re-enable to recover.
            </span>
          ) : (
            <span className="font-semibold text-ink text-base">
              {(settings?.subscriber_count ?? 0).toLocaleString()}
            </span>
          )}
        </div>
```

- [ ] **Step 2: Run frontend checks**

```bash
just check-frontend
```

Expected: all checks and tests PASS with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/SubscriptionsPanel.tsx
git commit -m "feat: show segment recovery hint when segment is unreachable"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run the full gate**

```bash
just check
```

Expected: all static checks and all tests PASS.

- [ ] **Step 2: Commit if anything was fixed by the gate (e.g. formatting)**

Only needed if `just check` auto-fixed anything. If clean, skip.
