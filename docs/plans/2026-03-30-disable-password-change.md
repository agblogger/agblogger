# Disable Password Change Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow server operators to disable admin password changes via `DISABLE_PASSWORD_CHANGE` env var, returning 403 from the API and hiding the form in the UI.

**Architecture:** Add a boolean setting to backend config. Guard the existing `PUT /api/admin/password` endpoint. Expose the flag in the `GET /api/admin/site` response so the frontend can hide the form. TDD throughout.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), pytest, vitest

---

### Task 1: Backend config setting

**Files:**
- Modify: `backend/config.py:139` (after `admin_display_name`)
- Modify: `.env.example`

- [ ] **Step 1: Add config field**

In `backend/config.py`, add after `admin_display_name` (line 137):

```python
    # Feature flags
    disable_password_change: bool = False
```

- [ ] **Step 2: Add to .env.example**

In `.env.example`, add after the `ADMIN_PASSWORD` line:

```
# Set to true to prevent admin password changes via the web UI (e.g., for public demos)
# DISABLE_PASSWORD_CHANGE=false
```

- [ ] **Step 3: Commit**

```bash
git add backend/config.py .env.example
git commit -m "feat: add DISABLE_PASSWORD_CHANGE config setting"
```

---

### Task 2: Backend endpoint guard — test first

**Files:**
- Modify: `tests/test_api/test_auth_hardening.py`
- Modify: `backend/api/admin.py:261-267`

- [ ] **Step 1: Write the failing test**

In `tests/test_api/test_auth_hardening.py`, add a new test class after the existing password change tests:

```python
class TestPasswordChangeDisabled:
    @pytest.fixture
    def app_settings(self, tmp_content_dir: Path, tmp_path: Path) -> Settings:
        posts_dir = tmp_content_dir / "posts"
        hello_post = posts_dir / "hello"
        hello_post.mkdir()
        (hello_post / "index.md").write_text("# Hello\n")
        (tmp_content_dir / "labels.toml").write_text("[labels]\n")

        db_path = tmp_path / "test.db"
        return Settings(
            secret_key="test-secret-key-with-at-least-32-characters",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{db_path}",
            content_dir=tmp_content_dir,
            frontend_dir=tmp_path / "frontend",
            admin_username="admin",
            admin_password="admin123",
            disable_password_change=True,
        )

    @pytest.fixture
    async def client(self, app_settings: Settings) -> AsyncGenerator[AsyncClient]:
        async with create_test_client(app_settings) as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_password_change_returns_403_when_disabled(self, client: AsyncClient) -> None:
        """PUT /api/admin/password should return 403 when DISABLE_PASSWORD_CHANGE is set."""
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = await client.put(
            "/api/admin/password",
            json={
                "current_password": "admin123",
                "new_password": "newpassword1234",
                "confirm_password": "newpassword1234",
            },
            headers=headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Password changes are disabled by server configuration"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `just test-backend -- tests/test_api/test_auth_hardening.py::TestPasswordChangeDisabled -v`
Expected: FAIL — the endpoint currently returns 200 instead of 403.

- [ ] **Step 3: Implement the guard**

In `backend/api/admin.py`, add the guard at the top of `change_password()`, right after the function signature and before the rate limiter access (line 269). The handler needs access to settings, so add a `get_settings` dependency import and parameter:

First, add the import at the top of `backend/api/admin.py`:

```python
from backend.config import Settings
```

Add a dependency function. Check if there's an existing `get_settings` dependency in `backend/api/deps.py` — if not, add one. The settings are stored on `request.app.state.settings` during lifespan. Add to `backend/api/deps.py`:

```python
def get_settings(request: Request) -> Settings:
    return request.app.state.settings
```

Then modify the `change_password` handler signature and add the guard:

```python
@router.put("/password")
async def change_password(
    body: PasswordChange,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str | bool]:
    """Change admin password."""
    if settings.disable_password_change:
        raise HTTPException(
            status_code=403,
            detail="Password changes are disabled by server configuration",
        )
    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    ...  # rest unchanged
```

Note: Check `backend/api/deps.py` to see if `get_settings` already exists. If it does, import it from there. If not, add it there and import it.

- [ ] **Step 4: Run test to verify it passes**

Run: `just test-backend -- tests/test_api/test_auth_hardening.py::TestPasswordChangeDisabled -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/admin.py backend/api/deps.py tests/test_api/test_auth_hardening.py
git commit -m "feat: return 403 on password change when DISABLE_PASSWORD_CHANGE is set"
```

---

### Task 3: Expose flag in site settings response — test first

**Files:**
- Modify: `backend/schemas/admin.py`
- Modify: `backend/api/admin.py:64-75` (the `get_settings` endpoint)
- Modify: `tests/test_api/test_auth_hardening.py`

- [ ] **Step 1: Write the failing test**

Add to the `TestPasswordChangeDisabled` class in `tests/test_api/test_auth_hardening.py`:

```python
    @pytest.mark.asyncio
    async def test_site_settings_includes_password_change_disabled(
        self, client: AsyncClient
    ) -> None:
        """GET /api/admin/site should include password_change_disabled flag."""
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = await client.get("/api/admin/site", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["password_change_disabled"] is True
```

Also add a test for the default (false) case. Add to the existing tests that use the default `app_settings` fixture (e.g., add a new test method inside the existing test class that already has a client with default settings, or add a standalone test):

```python
class TestPasswordChangeEnabled:
    """Verify password_change_disabled defaults to false in site settings."""

    @pytest.mark.asyncio
    async def test_site_settings_password_change_disabled_defaults_false(
        self, client: AsyncClient
    ) -> None:
        token_resp = await client.post(
            "/api/auth/token-login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = await client.get("/api/admin/site", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["password_change_disabled"] is False
```

This class reuses the module-level `app_settings` and `client` fixtures which have `disable_password_change` defaulting to `False`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test-backend -- tests/test_api/test_auth_hardening.py::TestPasswordChangeDisabled::test_site_settings_includes_password_change_disabled tests/test_api/test_auth_hardening.py::TestPasswordChangeEnabled -v`
Expected: FAIL — `password_change_disabled` not in the response.

- [ ] **Step 3: Add the field to the response schema**

In `backend/schemas/admin.py`, add to `SiteSettingsResponse`:

```python
class SiteSettingsResponse(BaseModel):
    """Site settings response."""

    title: str
    description: str
    timezone: str
    password_change_disabled: bool
```

- [ ] **Step 4: Populate the field in the endpoint**

In `backend/api/admin.py`, modify the `get_settings` endpoint to accept the app settings dependency and pass the flag:

```python
@router.get("/site", response_model=SiteSettingsResponse)
async def get_settings(
    content_manager: Annotated[ContentManager, Depends(get_content_manager)],
    _user: Annotated[AdminUser, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SiteSettingsResponse:
    """Get current site settings."""
    cfg = get_site_settings(content_manager)
    return SiteSettingsResponse(
        title=cfg.title,
        description=cfg.description,
        timezone=cfg.timezone,
        password_change_disabled=settings.disable_password_change,
    )
```

Note: There will be a name collision between the endpoint function `get_settings` and the dependency `get_settings` from deps.py. Resolve by importing the dependency with an alias: `from backend.api.deps import get_settings as get_settings_dep` or by renaming the dependency in deps.py to `get_app_settings`. Choose the approach that's cleanest given what already exists. Both `get_settings` (the endpoint) and the `change_password` handler need the dependency, so use a consistent import alias.

- [ ] **Step 5: Run tests to verify they pass**

Run: `just test-backend -- tests/test_api/test_auth_hardening.py::TestPasswordChangeDisabled::test_site_settings_includes_password_change_disabled tests/test_api/test_auth_hardening.py::TestPasswordChangeEnabled -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/admin.py backend/api/admin.py tests/test_api/test_auth_hardening.py
git commit -m "feat: expose password_change_disabled in GET /api/admin/site response"
```

---

### Task 4: Frontend — update types and hide password form

**Files:**
- Modify: `frontend/src/api/client.ts:263-267`
- Modify: `frontend/src/components/admin/AccountSection.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx:160-162`

- [ ] **Step 1: Update the TypeScript type**

In `frontend/src/api/client.ts`, update the `AdminSiteSettings` interface:

```typescript
export interface AdminSiteSettings {
  title: string
  description: string
  timezone: string
  password_change_disabled: boolean
}
```

- [ ] **Step 2: Update the EMPTY_SITE_SETTINGS default**

In `frontend/src/pages/AdminPage.tsx`, update line 30:

```typescript
const EMPTY_SITE_SETTINGS: AdminSiteSettings = { title: '', description: '', timezone: '', password_change_disabled: false }
```

- [ ] **Step 3: Pass the flag to AccountSection**

In `frontend/src/pages/AdminPage.tsx`, update the `AccountSection` rendering (line 161):

```tsx
<AccountSection
  busy={busy}
  passwordChangeDisabled={siteSettings.password_change_disabled}
  onSaving={setAccountSaving}
  onDirtyChange={setAccountDirty}
/>
```

- [ ] **Step 4: Update AccountSection to accept and use the prop**

In `frontend/src/components/admin/AccountSection.tsx`:

Add `passwordChangeDisabled` to the props interface:

```typescript
interface AccountSectionProps {
  busy: boolean
  passwordChangeDisabled: boolean
  onSaving: (saving: boolean) => void
  onDirtyChange: (dirty: boolean) => void
}
```

Update the destructuring:

```typescript
export default function AccountSection({ busy, passwordChangeDisabled, onSaving, onDirtyChange }: AccountSectionProps) {
```

Replace the password `<section>` block (the entire section from `{/* Password section */}` to its closing `</section>`) with a conditional:

```tsx
{/* Password section */}
{passwordChangeDisabled ? (
  <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
    <div className="flex items-center gap-2 mb-4">
      <Lock size={16} className="text-accent" />
      <h2 className="text-sm font-medium text-ink">Change Password</h2>
    </div>
    <p className="text-sm text-muted">
      Password changes are disabled by server configuration.
    </p>
  </section>
) : (
  <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
    {/* ... existing password form unchanged ... */}
  </section>
)}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/AdminPage.tsx frontend/src/components/admin/AccountSection.tsx
git commit -m "feat: hide password change form when disabled by server config"
```

---

### Task 5: Frontend tests

**Files:**
- Modify: `frontend/src/pages/__tests__/AdminPage.test.tsx`

- [ ] **Step 1: Update defaultSettings in tests**

In `frontend/src/pages/__tests__/AdminPage.test.tsx`, update `defaultSettings` (around line 85):

```typescript
const defaultSettings: AdminSiteSettings = {
  title: 'My Blog',
  description: 'A test blog',
  timezone: 'UTC',
  password_change_disabled: false,
}
```

- [ ] **Step 2: Write test for hidden password form**

Add a test that verifies the password form is hidden when `password_change_disabled` is true:

```typescript
it('hides password form when password change is disabled', async () => {
  mockFetchAdminSiteSettings.mockResolvedValue({
    ...defaultSettings,
    password_change_disabled: true,
  })
  mockFetchAdminPages.mockResolvedValue({ pages: defaultPages })
  renderAdmin()
  const user = userEvent.setup()
  await switchToTab(user, 'Account')

  expect(
    screen.getByText('Password changes are disabled by server configuration.'),
  ).toBeInTheDocument()
  expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument()
})
```

Also add a test confirming the form shows when not disabled:

```typescript
it('shows password form when password change is enabled', async () => {
  setupLoadSuccess()
  renderAdmin()
  const user = userEvent.setup()
  await switchToTab(user, 'Account')

  expect(screen.getByLabelText(/current password/i)).toBeInTheDocument()
  expect(
    screen.queryByText('Password changes are disabled by server configuration.'),
  ).not.toBeInTheDocument()
})
```

- [ ] **Step 3: Run frontend tests**

Run: `just test-frontend`
Expected: PASS (all tests including the new ones)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/__tests__/AdminPage.test.tsx
git commit -m "test: add frontend tests for password change disabled state"
```

---

### Task 6: Update docs and run full check

**Files:**
- Modify: `docs/arch/auth.md`

- [ ] **Step 1: Update auth docs**

In `docs/arch/auth.md`, add a section before "Code Entry Points":

```markdown
## Feature Flags

The `DISABLE_PASSWORD_CHANGE` environment variable prevents admin password changes through the web UI. When set to `true`, the `PUT /api/admin/password` endpoint returns 403 and the frontend hides the password change form. The flag is exposed in the `GET /api/admin/site` response as `password_change_disabled`. Intended for public demo deployments with shared admin access.
```

- [ ] **Step 2: Run full check**

Run: `just check`
Expected: All static checks and tests pass.

- [ ] **Step 3: Commit**

```bash
git add docs/arch/auth.md
git commit -m "docs: document DISABLE_PASSWORD_CHANGE feature flag"
```
