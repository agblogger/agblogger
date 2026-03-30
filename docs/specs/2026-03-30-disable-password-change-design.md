# Disable Password Change via Environment Variable

## Purpose

Allow server operators to disable admin password changes through the web UI via an environment variable. Primary use case: public demos with admin access where the password must remain fixed.

## Design

### Configuration

Add to `Settings` in `backend/config.py`:

```python
disable_password_change: bool = False
```

Environment variable: `DISABLE_PASSWORD_CHANGE=true`

### Backend Changes

**`backend/api/admin.py` — `change_password()`**: At the top of the handler, before any other logic, check `settings.disable_password_change`. If true, return HTTP 403 with detail `"Password changes are disabled by server configuration"`.

**`backend/schemas/admin.py` — `AdminSiteSettings`**: Add `password_change_disabled: bool` field so the frontend can read the flag without attempting a password change.

**`backend/api/admin.py` — `get_settings()`**: Populate `password_change_disabled` from `settings.disable_password_change`.

### Frontend Changes

**`frontend/src/components/admin/AccountSection.tsx`**: When `password_change_disabled` is true in the site settings response, hide the password change form and show an informational message (e.g., "Password changes are disabled by server configuration.").

**`frontend/src/api/admin.ts`**: Update the `AdminSiteSettings` type to include `password_change_disabled: boolean`.

### Tests

- Backend integration test: with `disable_password_change=True`, `PUT /api/admin/password` returns 403 with the expected detail message.
- Backend integration test: `GET /api/admin/site` includes `password_change_disabled: true` when the setting is enabled.
- Frontend test: `AccountSection` hides the password form when `password_change_disabled` is true.

## Files Changed

- `backend/config.py`
- `backend/schemas/admin.py`
- `backend/api/admin.py`
- `frontend/src/api/admin.ts`
- `frontend/src/components/admin/AccountSection.tsx`
- `.env.example`
- Tests in `tests/test_api/`
- `docs/arch/auth.md` (document the setting)
