"""Unit tests for InMemoryRateLimiter."""

from __future__ import annotations

from unittest.mock import patch

from backend.services.rate_limit_service import InMemoryRateLimiter


class TestInMemoryRateLimiter:
    def test_not_limited_below_threshold(self):
        limiter = InMemoryRateLimiter()
        limiter.add_failure("key1", 60)
        limited, retry = limiter.is_limited("key1", 3, 60)
        assert not limited
        assert retry == 0

    def test_limited_at_threshold(self):
        limiter = InMemoryRateLimiter()
        for _ in range(3):
            limiter.add_failure("key1", 60)
        limited, retry = limiter.is_limited("key1", 3, 60)
        assert limited
        assert retry > 0

    def test_retry_after_is_positive(self):
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.add_failure("key1", 60)
        limited, retry = limiter.is_limited("key1", 3, 60)
        assert limited
        assert retry >= 1

    def test_clear_removes_attempts(self):
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.add_failure("key1", 60)
        limiter.clear("key1")
        limited, _ = limiter.is_limited("key1", 3, 60)
        assert not limited

    def test_keys_are_isolated(self):
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.add_failure("key1", 60)
        limited, _ = limiter.is_limited("key2", 3, 60)
        assert not limited

    def test_expired_attempts_are_evicted(self):
        limiter = InMemoryRateLimiter()
        # Add failures with a very short window
        with patch("backend.services.rate_limit_service.datetime") as mock_dt:
            # Simulate failures at time T
            mock_dt.now.return_value.timestamp.return_value = 1000.0
            for _ in range(5):
                limiter.add_failure("key1", 10)

            # Check at T+11 (window expired)
            mock_dt.now.return_value.timestamp.return_value = 1011.0
            limited, _ = limiter.is_limited("key1", 3, 10)
            assert not limited

    def test_is_limited_does_not_create_entries_for_unknown_keys(self):
        """is_limited should not leak memory for keys that never had failures."""
        limiter = InMemoryRateLimiter()
        limited, retry = limiter.is_limited("unknown-key", 3, 60)
        assert not limited
        assert retry == 0

    def test_empty_deque_cleaned_up_after_expiry(self):
        """After all attempts expire, the key should behave as if it never had failures."""
        limiter = InMemoryRateLimiter()
        with patch("backend.services.rate_limit_service.datetime") as mock_dt:
            mock_dt.now.return_value.timestamp.return_value = 1000.0
            limiter.add_failure("key1", 10)

            # After window expires
            mock_dt.now.return_value.timestamp.return_value = 1011.0
            limited, retry = limiter.is_limited("key1", 3, 10)
            assert not limited
            assert retry == 0

    def test_zero_window_keeps_current_timestamp(self):
        limiter = InMemoryRateLimiter()
        with patch("backend.services.rate_limit_service.datetime") as mock_dt:
            mock_dt.now.return_value.timestamp.return_value = 1000.0
            for _ in range(3):
                limiter.add_failure("key1", 0)
            limited, _ = limiter.is_limited("key1", 3, 0)
            assert limited

    def test_max_keys_eviction(self):
        limiter = InMemoryRateLimiter()
        with patch("backend.services.rate_limit_service.datetime") as mock_dt:
            mock_dt.now.return_value.timestamp.return_value = 1000.0
            for i in range(limiter._MAX_KEYS):
                limiter.add_failure(f"key-{i}", 60)
            assert len(limiter._attempts) == limiter._MAX_KEYS

            mock_dt.now.return_value.timestamp.return_value = 1070.0
            limiter.add_failure("overflow-key", 60)
            assert "overflow-key" in limiter._attempts
            assert len(limiter._attempts) == 1
