"""Time-limited in-memory store for pending OAuth flows."""

from __future__ import annotations

import time
from typing import Any


class OAuthStateStore:
    """Store pending OAuth authorization state with automatic expiry.

    Thread-safety: safe under asyncio's single-threaded cooperative model.
    All methods (set, get, pop, cleanup) are synchronous with no await points,
    so no interleaving can occur between check-and-act sequences.
    Do NOT use from multiple OS threads without external synchronization.
    """

    def __init__(
        self,
        ttl_seconds: int = 600,
        max_entries: int = 100,
        max_entries_per_user: int = 10,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._max_entries_per_user = max_entries_per_user
        self._entries: dict[str, tuple[dict[str, Any], float]] = {}

    @staticmethod
    def _owner_key(data: dict[str, Any]) -> str:
        """Group pending states by authenticated user when possible."""
        user_id = data.get("user_id")
        return str(user_id) if user_id is not None else "__global__"

    def set(self, state: str, data: dict[str, Any]) -> None:
        """Store data for a pending OAuth flow."""
        self.cleanup()
        existing = self._entries.pop(state, None)
        owner_key = self._owner_key(data)
        if existing is not None and self._owner_key(existing[0]) != owner_key:
            existing = None
        owner_entries = [
            key
            for key, (entry_data, _) in self._entries.items()
            if self._owner_key(entry_data) == owner_key
        ]
        if len(owner_entries) >= self._max_entries_per_user:
            raise ValueError("Too many pending OAuth flows for this user")
        if len(self._entries) >= self._max_entries:
            raise ValueError("OAuth state store is full")
        self._entries[state] = (data, time.time())

    def get(self, state: str) -> dict[str, Any] | None:
        """Retrieve data for a pending OAuth flow without removing it."""
        entry = self._entries.get(state)
        if entry is None:
            return None
        data, created_at = entry
        if time.time() - created_at > self._ttl:
            del self._entries[state]
            return None
        return data

    def pop(self, state: str) -> dict[str, Any] | None:
        """Retrieve and remove data for a completed OAuth flow."""
        entry = self._entries.pop(state, None)
        if entry is None:
            return None
        data, created_at = entry
        if time.time() - created_at > self._ttl:
            return None
        return data

    def cleanup(self) -> None:
        """Remove expired entries."""
        now = time.time()
        expired = [k for k, (_, t) in self._entries.items() if now - t > self._ttl]
        for k in expired:
            del self._entries[k]
