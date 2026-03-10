"""Tests for Bluesky OAuth pending state store."""

from __future__ import annotations

import time

import pytest

from backend.crosspost.bluesky_oauth_state import OAuthStateStore


class TestOAuthStateStore:
    def test_store_and_retrieve(self) -> None:
        store = OAuthStateStore(ttl_seconds=60)
        state_data = {"pkce_verifier": "v123", "user_id": 1}
        store.set("state-abc", state_data)
        result = store.pop("state-abc")
        assert result == state_data

    def test_pop_removes_entry(self) -> None:
        store = OAuthStateStore(ttl_seconds=60)
        store.set("state-abc", {"key": "value"})
        store.pop("state-abc")
        assert store.pop("state-abc") is None

    def test_returns_none_for_unknown_state(self) -> None:
        store = OAuthStateStore(ttl_seconds=60)
        assert store.pop("nonexistent") is None

    def test_expired_entries_are_not_returned(self) -> None:
        store = OAuthStateStore(ttl_seconds=0)
        store.set("state-abc", {"key": "value"})
        store._entries["state-abc"] = (store._entries["state-abc"][0], time.time() - 1)
        assert store.pop("state-abc") is None

    def test_cleanup_removes_expired(self) -> None:
        store = OAuthStateStore(ttl_seconds=60)
        store.set("old", {"key": "value"})
        store._entries["old"] = (store._entries["old"][0], time.time() - 120)
        store.set("new", {"key": "value2"})
        store.cleanup()
        assert "old" not in store._entries
        assert "new" in store._entries

    def test_rejects_new_state_when_per_user_limit_is_reached(self) -> None:
        store = OAuthStateStore(ttl_seconds=60, max_entries=10, max_entries_per_user=1)
        store.set("state-1", {"user_id": 1})

        with pytest.raises(ValueError, match="Too many pending OAuth flows"):
            store.set("state-2", {"user_id": 1})

        assert store.get("state-1") == {"user_id": 1}

    def test_does_not_evict_other_users_when_store_is_full(self) -> None:
        store = OAuthStateStore(ttl_seconds=60, max_entries=1, max_entries_per_user=1)
        store.set("state-admin", {"user_id": 1})

        with pytest.raises(ValueError, match="OAuth state store is full"):
            store.set("state-reader", {"user_id": 2})

        assert store.get("state-admin") == {"user_id": 1}
