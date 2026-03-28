"""Tests for crosspost API helper functions."""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.crosspost import _generate_pkce_pair, _store_pending_oauth_state
from backend.crosspost.bluesky_oauth_state import OAuthStateStore
from backend.exceptions import CrossPostValidationError
from backend.models.base import DurableBase
from backend.models.crosspost import SocialAccount
from backend.services.crosspost_service import DuplicateAccountError, get_social_accounts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class TestGeneratePkcePair:
    """Tests for PKCE code verifier and challenge generation (RFC 7636)."""

    def test_verifier_length_is_64(self) -> None:
        verifier, _ = _generate_pkce_pair()
        assert len(verifier) == 64

    def test_verifier_uses_only_unreserved_characters(self) -> None:
        unreserved = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        verifier, _ = _generate_pkce_pair()
        assert set(verifier).issubset(unreserved)

    def test_challenge_is_base64url_sha256_of_verifier(self) -> None:
        verifier, challenge = _generate_pkce_pair()
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert challenge == expected_challenge

    def test_generates_unique_pairs(self) -> None:
        pairs = [_generate_pkce_pair() for _ in range(10)]
        verifiers = [v for v, _ in pairs]
        assert len(set(verifiers)) == 10

    def test_challenge_has_no_padding(self) -> None:
        _, challenge = _generate_pkce_pair()
        assert "=" not in challenge


class TestStorePendingOAuthState:
    """Tests for _store_pending_oauth_state exception-to-HTTP-status mapping."""

    def test_success_stores_state(self) -> None:
        store = OAuthStateStore(ttl_seconds=60)
        _store_pending_oauth_state(store, "state-1", {"user_id": 1})
        assert store.get("state-1") == {"user_id": 1}

    def test_per_user_limit_raises_429(self) -> None:
        store = OAuthStateStore(ttl_seconds=60, max_entries=10, max_entries_per_user=1)
        store.set("state-1", {"user_id": 1})

        with pytest.raises(HTTPException) as exc_info:
            _store_pending_oauth_state(store, "state-2", {"user_id": 1})

        assert exc_info.value.status_code == 429
        assert "Too many pending OAuth flows" in exc_info.value.detail

    def test_global_capacity_raises_503(self) -> None:
        store = OAuthStateStore(ttl_seconds=60, max_entries=1, max_entries_per_user=5)
        store.set("state-1", {"user_id": 1})

        with pytest.raises(HTTPException) as exc_info:
            _store_pending_oauth_state(store, "state-2", {"user_id": 2})

        assert exc_info.value.status_code == 503
        assert "temporarily unavailable" in exc_info.value.detail


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """In-memory SQLite session for testing DB-level behaviour."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(DurableBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestUpsertSocialAccountSavepoint:
    """Savepoint rollback in _upsert_social_account prevents account loss on race."""

    @pytest.mark.asyncio
    async def test_account_preserved_when_recreate_fails(self, db_session: AsyncSession) -> None:
        """If re-create fails after delete, the savepoint rolls back the delete.

        Without a savepoint the existing account would be permanently deleted when
        the second create_social_account raises DuplicateAccountError.  With a
        savepoint wrapping both operations, a failure in re-create causes the entire
        savepoint (including the delete) to be rolled back automatically.
        """
        from backend.api.crosspost import _upsert_social_account
        from backend.schemas.crosspost import SocialAccountCreate
        from backend.utils.datetime import format_datetime, now_utc

        # Insert an account directly so we can verify it survives the race.
        now = format_datetime(now_utc())
        existing_account = SocialAccount(
            user_id=1,
            platform="bluesky",
            account_name="preserved.bsky.social",
            credentials="encrypted-creds",
            created_at=now,
            updated_at=now,
        )
        db_session.add(existing_account)
        await db_session.commit()
        await db_session.refresh(existing_account)
        account_id = existing_account.id

        account_data = SocialAccountCreate(
            platform="bluesky",
            account_name="preserved.bsky.social",
            credentials={"identifier": "test", "password": "secret"},
        )

        mock_account = AsyncMock()
        mock_account.id = account_id
        mock_account.platform = "bluesky"
        mock_account.account_name = "preserved.bsky.social"

        # Simulate the race: create_social_account always raises DuplicateAccountError
        # (another concurrent request owns the row at the moment of re-create).
        # delete_social_account is also mocked so that it operates without committing
        # the session, allowing the savepoint context manager to roll back the
        # deletion when create fails.
        async def _mock_delete(session: AsyncSession, account_id: int, user_id: int) -> bool:
            """Delete within session without committing — savepoint handles atomicity."""
            from sqlalchemy import select as sa_select

            result = await session.execute(
                sa_select(SocialAccount).where(SocialAccount.id == account_id)
            )
            acct = result.scalar_one_or_none()
            if acct is None:
                return False
            await session.delete(acct)
            await session.flush()  # mark deleted but do NOT commit — let savepoint own this
            return True

        with (
            patch(
                "backend.api.crosspost.create_social_account",
                new_callable=AsyncMock,
                side_effect=DuplicateAccountError("duplicate"),
            ),
            patch(
                "backend.api.crosspost.get_social_accounts",
                new_callable=AsyncMock,
                return_value=[mock_account],
            ),
            patch(
                "backend.api.crosspost.delete_social_account",
                side_effect=_mock_delete,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _upsert_social_account(
                    db_session,
                    user_id=1,
                    account_data=account_data,
                    secret_key="test-secret-key-with-at-least-32-characters",
                    platform="bluesky",
                    account_name="preserved.bsky.social",
                )
            assert exc_info.value.status_code == 409

        # The account must still exist — the savepoint rolled back the delete.
        remaining = await get_social_accounts(db_session, user_id=1)
        assert any(a.id == account_id for a in remaining), (
            "Account was permanently deleted despite race condition — savepoint not in effect"
        )


class TestCrosspostDraftRaisesSpecificException:
    """S-05: crosspost service raises CrossPostValidationError for draft posts, not ValueError."""

    @pytest.mark.asyncio
    async def test_crosspost_draft_raises_crosspost_validation_error(self) -> None:
        """crosspost() must raise CrossPostValidationError (not bare ValueError) for drafts."""
        from backend.services.crosspost_service import crosspost

        mock_cm = MagicMock()
        mock_cm.read_post.return_value = MagicMock(
            title="Draft Post", content="content", labels=[], is_draft=True
        )
        mock_cm.get_plain_excerpt.return_value = "excerpt"
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(CrossPostValidationError, match="Cannot cross-post a draft post"):
            await crosspost(
                session=mock_session,
                content_manager=mock_cm,
                post_path="posts/my-draft/index.md",
                platforms=["bluesky"],
                actor=MagicMock(id=1, username="admin", display_name="Admin"),
                site_url="https://example.com",
                secret_key="test-secret-key-with-at-least-32-characters",
            )

    def test_crosspost_validation_error_is_subclass_of_value_error(self) -> None:
        """CrossPostValidationError must be a subclass of ValueError for backward compat."""
        assert issubclass(CrossPostValidationError, ValueError)

    @pytest.mark.asyncio
    async def test_crosspost_api_returns_400_for_draft(self) -> None:
        """The API layer maps CrossPostValidationError to HTTP 400."""
        from backend.api.crosspost import crosspost_endpoint
        from backend.schemas.crosspost import CrossPostRequest

        mock_session = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.secret_key = "test-secret-key-with-at-least-32-characters"
        mock_settings.site_url = "https://example.com"
        mock_user = MagicMock()

        with patch(
            "backend.api.crosspost.crosspost",
            new_callable=AsyncMock,
            side_effect=CrossPostValidationError("Cannot cross-post a draft post"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await crosspost_endpoint(
                    body=CrossPostRequest(
                        post_path="posts/draft/index.md",
                        platforms=["bluesky"],
                    ),
                    session=mock_session,
                    user=mock_user,
                    settings=mock_settings,
                    content_manager=MagicMock(),
                )
            assert exc_info.value.status_code == 400
            assert "Cannot cross-post a draft post" in exc_info.value.detail
