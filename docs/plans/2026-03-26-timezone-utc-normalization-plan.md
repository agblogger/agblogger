# Timezone UTC Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make date filtering timezone-aware by having the frontend convert local dates to UTC before sending to the backend, and rename `default_tz` to `fallback_tz` throughout.

**Architecture:** The frontend converts filter dates (YYYY-MM-DD from `<input type="date">`) to UTC ISO timestamps using the browser's local timezone. The backend receives full UTC timestamps and parses them directly, removing the hardcoded UTC midnight/end-of-day logic. The `default_tz` parameter on `parse_datetime` is renamed to `fallback_tz` to clarify it's only for ambiguous inputs (like date-only front matter).

**Tech Stack:** Python/pendulum (backend), TypeScript/date-fns (frontend), vitest (frontend tests), pytest (backend tests)

---

### Task 1: Rename `default_tz` to `fallback_tz` in `parse_datetime`

**Files:**
- Modify: `backend/services/datetime_service.py:14-46`
- Modify: `tests/test_services/test_datetime_service.py`
- Modify: `tests/test_services/test_datetime_service_hypothesis.py:85-87,150`

- [ ] **Step 1: Update tests to use `fallback_tz`**

In `tests/test_services/test_datetime_service.py`, rename:

```python
def test_parse_with_default_timezone(self) -> None:
    result = parse_datetime("2026-02-02 10:30", fallback_tz="America/New_York")
    assert result.year == 2026
    assert result.hour == 10

def test_parse_datetime_naive_adds_tz(self) -> None:
    dt = datetime(2026, 1, 1, 12, 0)
    result = parse_datetime(dt, fallback_tz="UTC")
    assert result.tzinfo is not None
```

In `tests/test_services/test_datetime_service_hypothesis.py`, rename:

```python
def test_parse_datetime_object_attaches_default_tz(self, dt: datetime) -> None:
    """Passing a naive datetime object attaches the fallback timezone."""
    result = parse_datetime(dt, fallback_tz="UTC")
    assert result.tzinfo is not None
```

```python
def test_date_only_strings_parse_to_midnight(self, d: date) -> None:
    """Date-only strings (YYYY-MM-DD) parse to midnight with fallback timezone."""
    date_str = d.isoformat()
    parsed = parse_datetime(date_str, fallback_tz="UTC")
    assert parsed.hour == 0
    assert parsed.minute == 0
    assert parsed.second == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend`
Expected: FAIL — `parse_datetime()` does not accept `fallback_tz` keyword.

- [ ] **Step 3: Rename parameter in `parse_datetime`**

In `backend/services/datetime_service.py`, change the function signature and all internal references:

```python
def parse_datetime(value: str | datetime, fallback_tz: str = "UTC") -> datetime:
    """Parse a lax datetime string into a strict timezone-aware datetime.

    Accepts various formats:
    - 2026-02-02 22:21:29.975359+00
    - 2026-02-02 22:21:29+00
    - 2026-02-02 22:21+00
    - 2026-02-02 22:21
    - 2026-02-02
    - ISO 8601 variants with T separator

    Missing timezone defaults to fallback_tz.
    Missing time components default to zeros.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            tz = pendulum.timezone(fallback_tz)
            value = value.replace(tzinfo=tz)
        return value

    value_str = value.strip()

    try:
        parsed = pendulum.parse(value_str, tz=fallback_tz, strict=False)
    except ParserError as exc:
        raise ValueError(f"Cannot parse date from: {value_str}") from exc
    if isinstance(parsed, pendulum.DateTime):
        return parsed
    if not isinstance(parsed, pendulum.Date):
        msg = f"Cannot parse date from: {value_str}"
        raise ValueError(msg)
    # pendulum.parse returns Date for date-only strings
    return pendulum.datetime(parsed.year, parsed.month, parsed.day, tz=fallback_tz)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-backend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/datetime_service.py tests/test_services/test_datetime_service.py tests/test_services/test_datetime_service_hypothesis.py
git commit -m "refactor: rename default_tz to fallback_tz in parse_datetime"
```

### Task 2: Update all callers of `parse_datetime` to use `fallback_tz`

**Files:**
- Modify: `backend/filesystem/frontmatter.py:112-128`
- Modify: `backend/filesystem/content_manager.py:102-172`
- Modify: `backend/services/post_service.py:113-131`
- Modify: `tests/test_services/test_crash_hunting_high.py:48-87`
- Modify: `tests/test_rendering/test_frontmatter_parsing_hypothesis.py:238-274`

- [ ] **Step 1: Update `frontmatter.py`**

In `backend/filesystem/frontmatter.py`, rename the parameter on `parse_post` and update the calls inside:

```python
def parse_post(
    raw_content: str,
    file_path: str = "",
    fallback_tz: str = "UTC",
) -> PostData:
```

Update all 4 calls to `parse_datetime` inside `parse_post` to use `fallback_tz=fallback_tz`:

```python
created_at = parse_datetime(raw_created, fallback_tz=fallback_tz)
```
```python
created_at = parse_datetime(str(raw_created), fallback_tz=fallback_tz)
```
```python
modified_at = parse_datetime(raw_modified, fallback_tz=fallback_tz)
```
```python
modified_at = parse_datetime(str(raw_modified), fallback_tz=fallback_tz)
```

- [ ] **Step 2: Update `content_manager.py`**

In `backend/filesystem/content_manager.py`, update the 3 call sites from `default_tz=` to `fallback_tz=`:

Line ~105:
```python
post_data = parse_post(
    raw_content,
    file_path=rel_path,
    fallback_tz=self.site_config.timezone,
)
```

Line ~137:
```python
post_data = parse_post(
    raw_content,
    file_path="",
    fallback_tz=self.site_config.timezone,
)
```

Line ~172:
```python
post_data = parse_post(
    raw_content,
    file_path=rel_path,
    fallback_tz=self.site_config.timezone,
)
```

- [ ] **Step 3: Update `post_service.py` filter parsing**

In `backend/services/post_service.py`, update to use `fallback_tz=`:

```python
if from_date:
    try:
        date_part = from_date.split("T")[0].split(" ")[0]
        from_dt = parse_datetime(date_part + " 00:00:00", fallback_tz="UTC")
        stmt = stmt.where(PostCache.created_at >= from_dt)
    except ValueError:
        logger.warning("Failed to parse 'from' date %r", from_date, exc_info=True)
        msg = f"Invalid 'from' date format: {from_date!r}. Expected YYYY-MM-DD."
        raise ValueError(msg) from None

if to_date:
    try:
        date_part = to_date.split("T")[0].split(" ")[0]
        to_dt = parse_datetime(date_part + " 23:59:59.999999", fallback_tz="UTC")
        stmt = stmt.where(PostCache.created_at <= to_dt)
    except ValueError:
        logger.warning("Failed to parse 'to' date %r", to_date, exc_info=True)
        msg = f"Invalid 'to' date format: {to_date!r}. Expected YYYY-MM-DD."
        raise ValueError(msg) from None
```

- [ ] **Step 4: Update test files**

In `tests/test_services/test_crash_hunting_high.py`, update the 4 occurrences of `default_tz` to `fallback_tz`:

```python
def _parse_post_raising_key_error(
    raw_content: str, file_path: str = "", fallback_tz: str = "UTC"
) -> Any:
    if "Bad" in raw_content:
        raise KeyError("missing_key")
    return original_parse_post(raw_content, file_path=file_path, fallback_tz=fallback_tz)
```

```python
def _parse_post_raising_type_error(
    raw_content: str, file_path: str = "", fallback_tz: str = "UTC"
) -> Any:
    if "Bad" in raw_content:
        raise TypeError("unexpected type")
    return original_parse_post(raw_content, file_path=file_path, fallback_tz=fallback_tz)
```

In `tests/test_rendering/test_frontmatter_parsing_hypothesis.py`, update all 6 occurrences of `default_tz="UTC"` to `fallback_tz="UTC"`:

```python
parsed = parse_post(raw, fallback_tz="UTC")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/filesystem/frontmatter.py backend/filesystem/content_manager.py backend/services/post_service.py tests/test_services/test_crash_hunting_high.py tests/test_rendering/test_frontmatter_parsing_hypothesis.py
git commit -m "refactor: update all callers to use fallback_tz parameter name"
```

### Task 3: Simplify backend date filter parsing to accept full ISO timestamps

**Files:**
- Modify: `backend/services/post_service.py:113-131`
- Modify: `tests/test_services/test_error_handling.py:222-273`
- Modify: `tests/test_api/test_input_validation.py:174-192`

- [ ] **Step 1: Update error handling tests for new error message**

In `tests/test_api/test_input_validation.py`, update the valid-dates test to also accept ISO timestamps:

```python
class TestDateFilterValidation:
    """Invalid date filters return 400 with descriptive message."""

    @pytest.mark.asyncio
    async def test_invalid_from_date_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?from=not-a-date")
        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invalid_to_date_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?to=not-a-date")
        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_valid_dates_still_work(self, client: AsyncClient) -> None:
        resp = await client.get("/api/posts?from=2026-01-01&to=2026-12-31")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_iso_timestamps_work(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/posts?from=2026-01-01T00:00:00.000Z&to=2026-12-31T23:59:59.999Z"
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify new test passes (it should already pass with current parsing)**

Run: `uv run pytest tests/test_api/test_input_validation.py::TestDateFilterValidation -v`
Expected: PASS (parse_datetime already handles ISO timestamps)

- [ ] **Step 3: Simplify filter parsing in `post_service.py`**

Replace the from_date/to_date blocks in `backend/services/post_service.py`:

```python
if from_date:
    try:
        from_dt = parse_datetime(from_date)
        stmt = stmt.where(PostCache.created_at >= from_dt)
    except ValueError:
        logger.warning("Failed to parse 'from' date %r", from_date, exc_info=True)
        msg = f"Invalid 'from' date format: {from_date!r}. Expected ISO 8601."
        raise ValueError(msg) from None

if to_date:
    try:
        to_dt = parse_datetime(to_date)
        stmt = stmt.where(PostCache.created_at <= to_dt)
    except ValueError:
        logger.warning("Failed to parse 'to' date %r", to_date, exc_info=True)
        msg = f"Invalid 'to' date format: {to_date!r}. Expected ISO 8601."
        raise ValueError(msg) from None
```

- [ ] **Step 4: Update error message assertions in error handling tests**

In `tests/test_services/test_error_handling.py`, update the error message match strings from `"date"` to `"date"` (they already match — just verify the tests still pass after simplification).

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/post_service.py tests/test_api/test_input_validation.py
git commit -m "refactor: simplify date filter parsing to accept full ISO timestamps"
```

### Task 4: Add frontend date-to-UTC conversion utilities

**Files:**
- Create: `frontend/src/utils/date.ts` (add functions to existing file)
- Create: `frontend/src/utils/__tests__/date.test.ts` (add tests to existing file)

- [ ] **Step 1: Write failing tests for new utilities**

Add to `frontend/src/utils/__tests__/date.test.ts`:

```typescript
import { localDateToUtcStart, localDateToUtcEnd } from '../date'

describe('localDateToUtcStart', () => {
  it('converts a date string to UTC start-of-day ISO string', () => {
    // Create a date and check the result is a valid ISO string ending in Z
    const result = localDateToUtcStart('2026-03-01')
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z$/)
    // The result represents midnight local time converted to UTC
    const parsed = new Date(result)
    expect(parsed.getFullYear()).toBe(2026)
    // Verify it represents start of day in local timezone
    const local = new Date(2026, 2, 1, 0, 0, 0, 0) // March 1 midnight local
    expect(parsed.getTime()).toBe(local.getTime())
  })

  it('returns empty string for empty input', () => {
    expect(localDateToUtcStart('')).toBe('')
  })
})

describe('localDateToUtcEnd', () => {
  it('converts a date string to UTC end-of-day ISO string', () => {
    const result = localDateToUtcEnd('2026-03-01')
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z$/)
    const parsed = new Date(result)
    // Verify it represents end of day in local timezone
    const local = new Date(2026, 2, 1, 23, 59, 59, 999) // March 1 23:59:59.999 local
    expect(parsed.getTime()).toBe(local.getTime())
  })

  it('returns empty string for empty input', () => {
    expect(localDateToUtcEnd('')).toBe('')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-frontend`
Expected: FAIL — `localDateToUtcStart` and `localDateToUtcEnd` not exported from `date.ts`.

- [ ] **Step 3: Implement the conversion utilities**

Add to `frontend/src/utils/date.ts`:

```typescript
/**
 * Convert a YYYY-MM-DD date string to a UTC ISO timestamp representing
 * the start of that day in the user's local timezone.
 */
export function localDateToUtcStart(dateStr: string): string {
  if (!dateStr) return ''
  const [year, month, day] = dateStr.split('-').map(Number)
  const local = new Date(year, month - 1, day, 0, 0, 0, 0)
  return local.toISOString()
}

/**
 * Convert a YYYY-MM-DD date string to a UTC ISO timestamp representing
 * the end of that day in the user's local timezone.
 */
export function localDateToUtcEnd(dateStr: string): string {
  if (!dateStr) return ''
  const [year, month, day] = dateStr.split('-').map(Number)
  const local = new Date(year, month - 1, day, 23, 59, 59, 999)
  return local.toISOString()
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `just test-frontend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/date.ts frontend/src/utils/__tests__/date.test.ts
git commit -m "feat: add localDateToUtcStart and localDateToUtcEnd utilities"
```

### Task 5: Wire up UTC conversion in the TimelinePage API call

**Files:**
- Modify: `frontend/src/pages/TimelinePage.tsx:64-80`

- [ ] **Step 1: Import the conversion utilities**

At the top of `frontend/src/pages/TimelinePage.tsx`, add:

```typescript
import { localDateToUtcStart, localDateToUtcEnd } from '@/utils/date'
```

- [ ] **Step 2: Apply conversion when building API params**

In the `useEffect` block around lines 79-80, change:

```typescript
if (fromDate) params.from = localDateToUtcStart(fromDate)
if (toDate) params.to = localDateToUtcEnd(toDate)
```

This replaces the existing lines:
```typescript
if (fromDate) params.from = fromDate
if (toDate) params.to = toDate
```

- [ ] **Step 3: Run the full check**

Run: `just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TimelinePage.tsx
git commit -m "feat: convert filter dates to UTC before sending to API"
```

### Task 6: Run full verification

- [ ] **Step 1: Run `just check`**

Run: `just check`
Expected: All static checks and tests pass.

- [ ] **Step 2: Verify no remaining references to `default_tz` in source code**

Run: `grep -r "default_tz" backend/ tests/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx"`
Expected: No matches (docs/plans files are OK to have references).
