# Timezone Searchable Dropdown Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the plain text timezone input in the admin panel with a searchable combobox dropdown that shows IANA timezones with city names, user's detected timezone first, then UTC, then the rest alphabetically.

**Architecture:** Frontend-only timezone list via `Intl.supportedValuesOf('timeZone')`. A new `TimezoneCombobox` component replaces the text input in `SiteSettingsSection`. Backend adds a Pydantic validator to reject invalid timezones with 422 instead of silently accepting them.

**Tech Stack:** React, TypeScript, Tailwind, Pydantic, zoneinfo

---

### Task 1: Backend — Validate timezone in SiteSettingsUpdate schema

**Files:**
- Modify: `backend/schemas/admin.py:14`
- Test: `tests/test_api/test_input_validation.py`

**Step 1: Write the failing test**

Add a test to `tests/test_api/test_input_validation.py` that sends `PUT /api/admin/site` with an invalid timezone and expects 422:

```python
async def test_invalid_timezone_rejected(self, admin_client: AsyncClient) -> None:
    resp = await admin_client.put(
        "/api/admin/site",
        json={"title": "Blog", "timezone": "Not/A/Timezone"},
    )
    assert resp.status_code == 422
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_input_validation.py -k "invalid_timezone" -v`
Expected: FAIL (currently returns 200, invalid timezone is accepted)

**Step 3: Add a field_validator to SiteSettingsUpdate**

In `backend/schemas/admin.py`, add a `field_validator` for `timezone` that checks it against `zoneinfo.ZoneInfo`:

```python
import zoneinfo
from pydantic import field_validator

class SiteSettingsUpdate(BaseModel):
    ...
    timezone: str = Field(default="UTC", max_length=100)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except (KeyError, ValueError):
            raise ValueError(f"Invalid timezone: {v}")
        return v
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api/test_input_validation.py -k "invalid_timezone" -v`
Expected: PASS

**Step 5: Run full backend checks**

Run: `just check-backend`
Expected: All pass

**Step 6: Commit**

```
feat: validate timezone in admin site settings API
```

---

### Task 2: Frontend — Create TimezoneCombobox component

**Files:**
- Create: `frontend/src/components/admin/TimezoneCombobox.tsx`
- Test: `frontend/src/components/admin/__tests__/TimezoneCombobox.test.tsx`

**Step 1: Write the failing tests**

Create `frontend/src/components/admin/__tests__/TimezoneCombobox.test.tsx` with tests:

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import TimezoneCombobox from '../TimezoneCombobox'

describe('TimezoneCombobox', () => {
  it('renders with the current value displayed', () => {
    render(<TimezoneCombobox value="America/New_York" onChange={vi.fn()} disabled={false} />)
    expect(screen.getByRole('combobox')).toHaveValue('America/New_York (New York)')
  })

  it('shows dropdown on focus', async () => {
    const user = userEvent.setup()
    render(<TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />)
    await user.click(screen.getByRole('combobox'))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('shows detected timezone first, then UTC', async () => {
    const user = userEvent.setup()
    render(<TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />)
    await user.click(screen.getByRole('combobox'))
    const options = screen.getAllByRole('option')
    // First option should be the detected timezone (varies by env, but should exist)
    // Second should be UTC (unless detected IS UTC, in which case UTC is first and only pinned)
    expect(options.length).toBeGreaterThan(2)
  })

  it('filters options when typing', async () => {
    const user = userEvent.setup()
    render(<TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />)
    await user.clear(screen.getByRole('combobox'))
    await user.type(screen.getByRole('combobox'), 'New York')
    const options = screen.getAllByRole('option')
    expect(options.some(o => o.textContent?.includes('New York'))).toBe(true)
    expect(options.length).toBeLessThan(20)
  })

  it('calls onChange with IANA key when option is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<TimezoneCombobox value="UTC" onChange={onChange} disabled={false} />)
    await user.clear(screen.getByRole('combobox'))
    await user.type(screen.getByRole('combobox'), 'Tokyo')
    const option = screen.getByRole('option', { name: /Tokyo/ })
    await user.click(option)
    expect(onChange).toHaveBeenCalledWith('Asia/Tokyo')
  })

  it('is disabled when disabled prop is true', () => {
    render(<TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={true} />)
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('closes dropdown on Escape', async () => {
    const user = userEvent.setup()
    render(<TimezoneCombobox value="UTC" onChange={vi.fn()} disabled={false} />)
    await user.click(screen.getByRole('combobox'))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('selects option with Enter key', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<TimezoneCombobox value="UTC" onChange={onChange} disabled={false} />)
    await user.clear(screen.getByRole('combobox'))
    await user.type(screen.getByRole('combobox'), 'Tokyo')
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onChange).toHaveBeenCalledWith('Asia/Tokyo')
  })
})
```

**Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/admin/__tests__/TimezoneCombobox.test.tsx` from `frontend/`
Expected: FAIL (component doesn't exist)

**Step 3: Implement TimezoneCombobox**

Create `frontend/src/components/admin/TimezoneCombobox.tsx`:

Key implementation details:
- Use `Intl.supportedValuesOf('timeZone')` to get timezone list
- Extract city name: split by `/`, take last segment, replace `_` with space → display as `America/New_York (New York)`
- Detect browser timezone: `Intl.DateTimeFormat().resolvedOptions().timeZone`
- Order: detected (labeled "detected") → UTC → rest alphabetically
- If detected IS UTC, show UTC once with "(detected)" label
- Filter: case-insensitive match on IANA key and city name
- Keyboard: ArrowDown/ArrowUp navigate, Enter selects, Escape closes
- Click outside closes dropdown (useEffect with document click listener)
- ARIA: `role="combobox"` on input, `role="listbox"` on dropdown, `role="option"` on items, `aria-activedescendant` for keyboard focus

**Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/admin/__tests__/TimezoneCombobox.test.tsx` from `frontend/`
Expected: PASS

**Step 5: Run frontend checks**

Run: `just check-frontend`
Expected: All pass

**Step 6: Commit**

```
feat: add TimezoneCombobox component
```

---

### Task 3: Frontend — Integrate TimezoneCombobox into SiteSettingsSection

**Files:**
- Modify: `frontend/src/components/admin/SiteSettingsSection.tsx:146-165`
- Modify: `frontend/src/pages/__tests__/AdminPage.test.tsx:165`

**Step 1: Update the existing test assertion**

In `frontend/src/pages/__tests__/AdminPage.test.tsx`, the test at line 165 checks `screen.getByLabelText('Timezone')` has value `'UTC'`. Update this to match the new combobox display format. The combobox will show `'UTC'` as the display value for UTC, so the assertion should check the combobox role instead:

```typescript
// Change from:
expect(screen.getByLabelText('Timezone')).toHaveValue('UTC')
// To:
expect(screen.getByLabelText('Timezone')).toHaveValue('UTC')
```

Note: UTC displays as just `'UTC'` (no city name), so the assertion value stays the same. But the element is now a combobox, so verify the test still passes.

**Step 2: Run the test to verify it passes with current code**

Run: `npx vitest run src/pages/__tests__/AdminPage.test.tsx` from `frontend/`
Expected: PASS (still using old input)

**Step 3: Replace the timezone input in SiteSettingsSection**

In `frontend/src/components/admin/SiteSettingsSection.tsx`, replace lines 146-165 (the timezone `<div>` block) with:

```tsx
import TimezoneCombobox from './TimezoneCombobox'

// Replace the timezone input div with:
<div>
  <label htmlFor="site-timezone" className="block text-xs font-medium text-muted mb-1">
    Timezone
  </label>
  <TimezoneCombobox
    value={siteSettings.timezone}
    onChange={(tz) => {
      setSiteSettings({ ...siteSettings, timezone: tz })
      setSiteSuccess(null)
    }}
    disabled={busy}
  />
</div>
```

**Step 4: Run AdminPage tests to verify they still pass**

Run: `npx vitest run src/pages/__tests__/AdminPage.test.tsx` from `frontend/`
Expected: PASS

**Step 5: Run full frontend checks**

Run: `just check-frontend`
Expected: All pass

**Step 6: Commit**

```
feat: integrate timezone combobox into admin settings
```

---

### Task 4: End-to-end verification

**Step 1: Start the dev server**

Run: `just start`

**Step 2: Browser test with Playwright MCP**

- Navigate to `/admin`
- Log in if needed
- Verify the timezone dropdown appears in the Settings tab
- Click on it — verify the dropdown opens with detected timezone first, then UTC
- Type "Tokyo" — verify filtered results show Asia/Tokyo
- Select Asia/Tokyo — verify it populates the field
- Click Save Settings — verify it saves successfully
- Refresh — verify Asia/Tokyo is still selected

**Step 3: Stop the dev server**

Run: `just stop`

**Step 4: Run full check**

Run: `just check`
Expected: All pass

**Step 5: Commit any fixes if needed**

---
