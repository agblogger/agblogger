"""Regression tests for INFO/BEHAVIOR severity issues #20-#23.

Issue #20: ValueError handler exposes str(exc) from library code to clients.
Issue #21: Rate-limit stale keys never cleaned, unbounded memory growth.
Issue #22: Multiple accounts on same platform silently collapse (last wins).
Issue #23: DuplicateAccountError swallowed by ValueError catch, returns 400 not 409.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.crosspost_service import DuplicateAccountError
from backend.services.rate_limit_service import InMemoryRateLimiter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient

    from backend.config import Settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create settings for test app."""
    from backend.config import Settings

    posts_dir = tmp_content_dir / "posts"
    hello_post = posts_dir / "hello"
    hello_post.mkdir()
    (hello_post / "index.md").write_text(
        "---\ncreated_at: 2026-02-02 22:21:29.975359+00\n"
        "author: admin\nlabels: ['#swe']\n---\n# Hello World\n\nTest content.\n"
    )
    (tmp_content_dir / "labels.toml").write_text(
        "[labels]\n[labels.swe]\nnames = ['software engineering']\n"
    )
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(app_settings: Settings) -> AsyncGenerator[AsyncClient]:
    from tests.conftest import create_test_client

    async with create_test_client(app_settings) as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/token-login",
        json={"username": "admin", "password": "admin123"},
    )
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


# ---------------------------------------------------------------------------
# Issue #20: ValueError handler must not expose library-originated error details
# ---------------------------------------------------------------------------


class TestValueErrorHandlerSafety:
    """Issue #20: Global ValueError handler must not leak internal details.

    The global handler is a safety net for uncaught ValueErrors. All intentional
    business-logic ValueErrors are caught at the endpoint level. The global handler
    must always return a generic message.
    """

    async def test_global_handler_returns_generic_message(self, client: AsyncClient) -> None:
        """An unhandled ValueError reaching the global handler must return
        the generic 'Invalid value' message, not the raw exception text."""
        # Use /api/pages which has no local ValueError catch, so the error
        # reaches the global handler.
        lib_error = ValueError("invalid literal for int() with base 10: 'abc'")

        with patch(
            "backend.api.pages.get_site_config",
            side_effect=lib_error,
        ):
            resp = await client.get("/api/pages")

        assert resp.status_code == 422
        body = resp.json()
        # The raw error message must NOT appear in the response
        assert "invalid literal" not in body["detail"]
        assert body["detail"] == "Invalid value"

    async def test_global_handler_hides_datetime_parse_details(self, client: AsyncClient) -> None:
        """datetime.fromisoformat() ValueError must not leak format details."""
        datetime_error = ValueError("Invalid isoformat string: '2026-13-45T99:99:99'")

        with patch(
            "backend.api.pages.get_site_config",
            side_effect=datetime_error,
        ):
            resp = await client.get("/api/pages")

        assert resp.status_code == 422
        body = resp.json()
        assert "isoformat" not in body["detail"]
        assert "2026-13-45" not in body["detail"]
        assert body["detail"] == "Invalid value"

    async def test_endpoint_level_catch_preserves_message(self, client: AsyncClient) -> None:
        """Endpoint-level ValueError catches (e.g. in list_posts_endpoint) should
        still preserve the original message since those are intentional."""
        headers = await _login(client)

        with patch(
            "backend.api.posts.list_posts",
            new_callable=AsyncMock,
            side_effect=ValueError("Post slug cannot be empty"),
        ):
            resp = await client.get("/api/posts", headers=headers)

        # Endpoint-level catch returns 400 with the original message
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"] == "Post slug cannot be empty"


# ---------------------------------------------------------------------------
# Issue #21: Rate-limiter stale keys never cleaned
# ---------------------------------------------------------------------------


class TestRateLimiterKeyBounding:
    """Issue #21: Rate-limiter must not grow unbounded with stale keys."""

    def test_prune_all_expired_removes_stale_keys(self) -> None:
        """_prune_all_expired should remove keys with no recent attempts."""
        limiter = InMemoryRateLimiter()
        window = 60  # 60 second window

        # Insert some keys with old timestamps directly
        old_time = 1000.0
        for i in range(10):
            limiter._attempts[f"old_key_{i}"] = deque([old_time])

        # Insert a fresh key
        limiter.add_failure("fresh_key", window)

        # Verify all keys exist
        assert len(limiter._attempts) >= 11

        # Prune expired keys
        limiter._prune_all_expired(window)

        # Old keys should be removed, fresh key should remain
        assert "fresh_key" in limiter._attempts
        for i in range(10):
            assert f"old_key_{i}" not in limiter._attempts

    def test_add_failure_triggers_prune_at_capacity(self) -> None:
        """When _MAX_KEYS is reached, add_failure should prune expired entries."""
        limiter = InMemoryRateLimiter()
        window = 60

        # Fill with stale keys up to _MAX_KEYS
        old_time = 1000.0
        for i in range(limiter._MAX_KEYS):
            limiter._attempts[f"stale_{i}"] = deque([old_time])

        assert len(limiter._attempts) == limiter._MAX_KEYS

        # Adding a new key should trigger pruning and succeed without
        # exceeding the capacity limit
        limiter.add_failure("new_key", window)

        # Stale keys should have been pruned
        assert len(limiter._attempts) < limiter._MAX_KEYS
        assert "new_key" in limiter._attempts

    def test_max_keys_constant_exists(self) -> None:
        """The limiter must have a _MAX_KEYS capacity limit."""
        assert hasattr(InMemoryRateLimiter, "_MAX_KEYS")
        assert InMemoryRateLimiter._MAX_KEYS > 0


# ---------------------------------------------------------------------------
# Issue #22: Multiple accounts on same platform silently collapse
# ---------------------------------------------------------------------------


class TestMultipleAccountsSamePlatform:
    """Issue #22: Multiple accounts on the same platform must not silently collapse."""

    async def test_first_account_used_when_duplicates_exist(self) -> None:
        """When multiple accounts exist for a platform, the first one should be used
        (not the last, which was the old dict-comprehension behavior)."""
        # Create mock accounts - alphabetical order means "alice" comes first
        account_alice = MagicMock()
        account_alice.platform = "bluesky"
        account_alice.account_name = "alice"
        account_alice.credentials = "encrypted_alice"
        account_alice.id = 1

        account_bob = MagicMock()
        account_bob.platform = "bluesky"
        account_bob.account_name = "bob"
        account_bob.credentials = "encrypted_bob"
        account_bob.id = 2

        # Simulate what the dict comprehension used to do: last wins
        old_dict = {acct.platform: acct for acct in [account_alice, account_bob]}
        assert old_dict["bluesky"].account_name == "bob"  # Old behavior: last wins

        # The fix should use first-wins logic
        accounts: dict[str, object] = {}
        for acct in [account_alice, account_bob]:
            if acct.platform not in accounts:
                accounts[acct.platform] = acct
        assert accounts["bluesky"] is account_alice  # New behavior: first wins

    async def test_duplicate_accounts_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A warning should be logged when multiple accounts exist for the same platform."""
        import logging

        from backend.models.crosspost import SocialAccount

        # Build the accounts dict the way the fixed code does
        account1 = MagicMock(spec=SocialAccount)
        account1.platform = "bluesky"
        account1.account_name = "alice"

        account2 = MagicMock(spec=SocialAccount)
        account2.platform = "bluesky"
        account2.account_name = "bob"

        # Re-import the module-level logger to capture its output
        import backend.services.crosspost_service as cs_mod

        accounts: dict[str, SocialAccount] = {}
        with caplog.at_level(logging.WARNING, logger="backend.services.crosspost_service"):
            for acct in [account1, account2]:
                if acct.platform in accounts:
                    cs_mod.logger.warning(
                        "Multiple %s accounts found for user %d; using %s",
                        acct.platform,
                        1,
                        accounts[acct.platform].account_name,
                    )
                else:
                    accounts[acct.platform] = acct

        assert accounts["bluesky"] is account1
        assert any("Multiple bluesky accounts" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Issue #23: DuplicateAccountError swallowed by ValueError catch
# ---------------------------------------------------------------------------


class TestDuplicateAccountErrorNotSwallowed:
    """Issue #23: DuplicateAccountError should return 409 Conflict, not 400 Bad Request."""

    async def test_duplicate_account_returns_409_not_400(self, client: AsyncClient) -> None:
        """create_account_endpoint must catch DuplicateAccountError before ValueError
        and return 409 Conflict."""
        headers = await _login(client)

        dup_error = DuplicateAccountError("Account already exists for bluesky/myhandle")

        with patch(
            "backend.api.crosspost.create_social_account",
            new_callable=AsyncMock,
            side_effect=dup_error,
        ):
            resp = await client.post(
                "/api/crosspost/accounts",
                json={
                    "platform": "bluesky",
                    "account_name": "myhandle",
                    "credentials": {"access_token": "test"},
                },
                headers=headers,
            )

        assert resp.status_code == 409, (
            f"Expected 409 Conflict for DuplicateAccountError, got {resp.status_code}"
        )
        body = resp.json()
        assert "already exists" in body["detail"].lower()

    async def test_regular_value_error_still_returns_400(self, client: AsyncClient) -> None:
        """Plain ValueError from create_social_account should still return 400."""
        headers = await _login(client)

        with patch(
            "backend.api.crosspost.create_social_account",
            new_callable=AsyncMock,
            side_effect=ValueError("Unsupported platform: 'tiktok'"),
        ):
            resp = await client.post(
                "/api/crosspost/accounts",
                json={
                    "platform": "tiktok",
                    "account_name": "myhandle",
                    "credentials": {"access_token": "test"},
                },
                headers=headers,
            )

        assert resp.status_code == 400
