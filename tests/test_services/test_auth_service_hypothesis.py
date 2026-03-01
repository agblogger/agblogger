"""Property-based tests for authentication primitives."""

from __future__ import annotations

import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.auth_service import (
    create_access_token,
    create_personal_access_token_value,
    create_refresh_token_value,
    decode_access_token,
    hash_password,
    hash_token,
    verify_password,
)

PROPERTY_SETTINGS = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Passwords: printable ASCII, non-empty (bcrypt has practical limits)
_PASSWORD = st.text(
    alphabet=string.printable,
    min_size=1,
    max_size=50,
)

# Secret keys for JWT (HS256 requires at least 32 bytes for security,
# and PyJWT may reject very short keys)
_SECRET_KEY = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=32,
    max_size=64,
)

# JWT payload data (simple key-value pairs, no reserved keys)
_JWT_DATA = st.fixed_dictionaries(
    {"sub": st.text(alphabet=string.digits, min_size=1, max_size=6)},
    optional={"username": st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=20)},
)

# Arbitrary strings for token hashing
_TOKEN_VALUE = st.text(min_size=1, max_size=200)


class TestPasswordHashingProperties:
    @PROPERTY_SETTINGS
    @given(password=_PASSWORD)
    def test_hash_then_verify_succeeds(self, password: str) -> None:
        """A password always verifies against its own hash."""
        hashed = hash_password(password)
        assert verify_password(password, hashed)

    @PROPERTY_SETTINGS
    @given(password=_PASSWORD)
    def test_different_hashes_for_same_password(self, password: str) -> None:
        """Bcrypt salting produces different hashes for the same password."""
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        # But both verify correctly
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)

    @PROPERTY_SETTINGS
    @given(password=_PASSWORD, wrong_password=_PASSWORD)
    def test_wrong_password_fails_verification(self, password: str, wrong_password: str) -> None:
        """A different password does not verify against the hash."""
        if password == wrong_password:
            return  # Skip when passwords happen to match
        hashed = hash_password(password)
        assert not verify_password(wrong_password, hashed)

    @PROPERTY_SETTINGS
    @given(password=_PASSWORD)
    def test_hash_format_is_bcrypt(self, password: str) -> None:
        """Hash output is a valid bcrypt string."""
        hashed = hash_password(password)
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60


class TestJwtTokenProperties:
    @PROPERTY_SETTINGS
    @given(data=_JWT_DATA, secret_key=_SECRET_KEY)
    def test_encode_then_decode_roundtrip(self, data: dict[str, str], secret_key: str) -> None:
        """create_access_token → decode_access_token preserves the payload data."""
        token = create_access_token(data, secret_key)
        decoded = decode_access_token(token, secret_key)
        assert decoded is not None
        for key, value in data.items():
            assert decoded[key] == value

    @PROPERTY_SETTINGS
    @given(data=_JWT_DATA, secret_key=_SECRET_KEY)
    def test_decoded_token_has_access_type(self, data: dict[str, str], secret_key: str) -> None:
        """Decoded tokens always have type='access'."""
        token = create_access_token(data, secret_key)
        decoded = decode_access_token(token, secret_key)
        assert decoded is not None
        assert decoded["type"] == "access"

    @PROPERTY_SETTINGS
    @given(data=_JWT_DATA, secret_key=_SECRET_KEY)
    def test_decoded_token_has_expiration(self, data: dict[str, str], secret_key: str) -> None:
        """Decoded tokens always have an 'exp' field."""
        token = create_access_token(data, secret_key)
        decoded = decode_access_token(token, secret_key)
        assert decoded is not None
        assert "exp" in decoded

    @PROPERTY_SETTINGS
    @given(data=_JWT_DATA, right_key=_SECRET_KEY, wrong_key=_SECRET_KEY)
    def test_wrong_key_returns_none(
        self, data: dict[str, str], right_key: str, wrong_key: str
    ) -> None:
        """Decoding with the wrong key returns None."""
        if right_key == wrong_key:
            return
        token = create_access_token(data, right_key)
        assert decode_access_token(token, wrong_key) is None

    @PROPERTY_SETTINGS
    @given(data=_JWT_DATA, secret_key=_SECRET_KEY)
    def test_original_data_dict_is_not_mutated(self, data: dict[str, str], secret_key: str) -> None:
        """create_access_token does not mutate the input data dict."""
        original = data.copy()
        create_access_token(data, secret_key)
        assert data == original


class TestTokenHashingProperties:
    @PROPERTY_SETTINGS
    @given(token=_TOKEN_VALUE)
    def test_hash_is_deterministic(self, token: str) -> None:
        """Same token always produces the same hash."""
        assert hash_token(token) == hash_token(token)

    @PROPERTY_SETTINGS
    @given(token=_TOKEN_VALUE)
    def test_hash_is_64_char_hex(self, token: str) -> None:
        """Token hash is a 64-character hex string (SHA-256)."""
        h = hash_token(token)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    @PROPERTY_SETTINGS
    @given(token_a=_TOKEN_VALUE, token_b=_TOKEN_VALUE)
    def test_different_tokens_produce_different_hashes(self, token_a: str, token_b: str) -> None:
        """Different tokens produce different hashes (collision resistance)."""
        if token_a == token_b:
            return
        assert hash_token(token_a) != hash_token(token_b)


class TestTokenGeneratorProperties:
    @PROPERTY_SETTINGS
    @given(st.just(None))
    def test_refresh_token_is_nonempty_url_safe(self, _: None) -> None:
        """Refresh tokens are non-empty URL-safe strings."""
        token = create_refresh_token_value()
        assert len(token) > 0
        assert all(c in string.ascii_letters + string.digits + "-_" for c in token)

    @PROPERTY_SETTINGS
    @given(st.just(None))
    def test_personal_access_token_has_prefix(self, _: None) -> None:
        """Personal access tokens start with 'agpat_'."""
        token = create_personal_access_token_value()
        assert token.startswith("agpat_")
        assert len(token) > len("agpat_")

    @PROPERTY_SETTINGS
    @given(st.just(None))
    def test_token_generators_produce_unique_values(self, _: None) -> None:
        """Each call produces a unique token (cryptographic randomness)."""
        tokens = {create_refresh_token_value() for _ in range(10)}
        assert len(tokens) == 10
