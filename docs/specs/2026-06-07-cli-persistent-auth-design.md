# CLI Persistent Authentication Design

**Date:** 2026-06-07

## Goal

Eliminate repeated password prompts for the `agblogger` sync CLI. Users authenticate once; subsequent runs reuse a stored session token. Supports both interactive (laptop) and automated (cron/CI) use.

## Credential Storage

Credentials are stored in `platformdirs.user_config_dir("agblogger")/credentials.json`, permissions `0o600`. The file is a JSON dict keyed by normalized server URL:

```json
{
  "https://blog.example.com": {
    "username": "admin",
    "refresh_token": "..."
  }
}
```

Multiple blogs on different servers each get their own entry. A new `agblogger_cli/credentials.py` module owns all load/save/delete/revoke logic. `platformdirs` is added as a dependency of the `agblogger-cli` package.

## New Commands

### `agblogger login [--server URL] [--username USER]`

Prompts for password (username from `--username`, the config file, or prompted if neither). POSTs to `/api/auth/login`, extracts the `refresh_token` from the response cookie jar, saves `{username, refresh_token}` to the credentials file. Does not keep a live session open.

### `agblogger logout [--server URL]`

Loads the stored refresh token, POSTs to `/api/auth/logout` with the token in the request body (already supported by the server), then deletes the credentials entry. Exits cleanly if no credentials exist locally. If `--server` is omitted, defaults to the server URL from `.agblogger.json` in the current content directory.

Revocation is implemented as a standalone `revoke_session(server_url, refresh_token)` function in `credentials.py`, called directly by the `agblogger logout` command.

## Session Startup Flow

For `agblogger sync` and `agblogger status`:

1. Load server URL from `.agblogger.json`; load credentials from the credentials file
2. If credentials exist:
   - Inject the stored `refresh_token` into the httpx cookie jar
   - POST to `/api/auth/refresh` — server rotates the token; httpx captures the new `refresh_token` from `Set-Cookie` automatically
   - Save the new `refresh_token` from the cookie jar to the credentials file **before** running the sync operation
   - Store the returned `csrf_token` in memory for the session
   - If refresh returns 401: prompt for password only (username from stored credentials), do a full login, save new credentials, continue
3. If no credentials exist: prompt for username + password, do full login, save credentials, continue

Saving the rotated token before the sync operation means a mid-sync crash does not lose the new token.

## Changes to `SyncClient`

- Remove `logout()` method; remove auto-revocation from `close()` — `close()` just closes `self.client`
- Remove the dormant `token` constructor parameter (the unused bearer token path)
- Add `restore_session(refresh_token: str) -> bool`: injects the token into the cookie jar, calls `_refresh_session()`, returns `True` on success and `False` on 401
- After `restore_session()` or `login()`, the rotated refresh token is readable from `self.client.cookies.get("refresh_token")`; callers save it to the credentials file

## Testing

- **`credentials.py` unit tests**: load/save/delete round-trips; missing file returns `None`; malformed JSON handled gracefully; `0o600` permissions on creation; multiple servers coexist correctly
- **`SyncClient` tests**: `restore_session()` returns `True` on 200 and `False` on 401; rotated token is readable from cookie jar after restore; `close()` does not trigger revocation
- **Command integration tests**: `login` saves credentials after successful auth; `logout` calls revoke endpoint and deletes credentials; `logout` with no stored credentials exits cleanly
- **Fallback test**: when `restore_session()` returns `False`, the CLI prompts for password, re-authenticates, saves new credentials, and continues
- **Update `test_sync_client_ux.py`**: remove auto-logout expectations
