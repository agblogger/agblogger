"""In-memory sliding-window rate limiter for auth endpoints. State is lost on restart."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime


class InMemoryRateLimiter:
    """Track failed attempts in an in-memory sliding window.

    Thread-safety: safe under asyncio's single-threaded cooperative model.
    All check-and-act sequences (is_limited, add_failure) are synchronous with
    no await points between read and mutation, so no interleaving can occur.
    Do NOT use from multiple OS threads without external synchronization.
    """

    _MAX_KEYS = 10_000

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = {}

    def clear(self, key: str) -> None:
        """Clear all attempts for a key."""
        self._attempts.pop(key, None)

    def _prune(self, key: str, window_seconds: int) -> deque[float] | None:
        """Prune expired attempts, returning the deque or None if empty/missing."""
        attempts = self._attempts.get(key)
        if attempts is None:
            return None
        now = datetime.now(UTC).timestamp()
        cutoff = now - window_seconds
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if not attempts:
            del self._attempts[key]
            return None
        return attempts

    def is_limited(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Check if the key is rate-limited. Returns (is_limited, retry_after_seconds)."""
        attempts = self._prune(key, window_seconds)
        if attempts is None or len(attempts) < limit:
            return False, 0
        now = datetime.now(UTC).timestamp()
        retry_after = int(attempts[0] + window_seconds - now) + 1
        return True, max(retry_after, 1)

    def add_failure(self, key: str, window_seconds: int) -> None:
        """Record one failed attempt."""
        now = datetime.now(UTC).timestamp()
        if key not in self._attempts:
            if len(self._attempts) >= self._MAX_KEYS:
                self._prune_all_expired(window_seconds)
            self._attempts[key] = deque()
        attempts = self._attempts[key]
        cutoff = now - window_seconds
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        attempts.append(now)

    def _prune_all_expired(self, window_seconds: int) -> None:
        """Remove all fully-expired keys to bound memory usage."""
        now = datetime.now(UTC).timestamp()
        cutoff = now - window_seconds
        expired = [k for k, dq in self._attempts.items() if not dq or dq[-1] < cutoff]
        for k in expired:
            del self._attempts[k]
