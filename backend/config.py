"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.exceptions import InternalServerError
from backend.validation import is_valid_trusted_host

INSECURE_DEV_SENTINEL = "change-me-in-production"
INSECURE_BOOTSTRAP_SENTINEL = "admin"
_SQLITE_ABSOLUTE_URL_PREFIXES = ("sqlite+aiosqlite:////", "sqlite:////")
_SQLITE_RELATIVE_URL_PREFIXES = ("sqlite+aiosqlite:///", "sqlite:///")


def _is_valid_public_oauth_base_url(url: str) -> bool:
    """Return True when the configured public OAuth base URL is a canonical HTTPS origin."""
    candidate = url.strip()
    if not candidate:
        return False
    parsed = urlparse(candidate)
    if parsed.scheme != "https":
        return False
    if parsed.hostname is None:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    return not (parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment)


def sqlite_database_path(database_url: str) -> Path | None:
    """Return the configured SQLite database path when the URL uses SQLite."""
    for prefix in _SQLITE_ABSOLUTE_URL_PREFIXES:
        if database_url.startswith(prefix):
            raw_path = database_url.removeprefix(prefix)
            return Path("/") / raw_path.lstrip("/")
    for prefix in _SQLITE_RELATIVE_URL_PREFIXES:
        if database_url.startswith(prefix):
            raw_path = database_url.removeprefix(prefix)
            return Path(raw_path)
    return None


class Settings(BaseSettings):
    """AgBlogger application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    secret_key: str = INSECURE_DEV_SENTINEL
    debug: bool = False
    expose_docs: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///data/db/agblogger.db"

    # Paths
    content_dir: Path = Path("./content")
    frontend_dir: Path = Path("./frontend/dist")

    # Server
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # CORS
    cors_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=list)
    trusted_proxy_ips: list[str] = Field(default_factory=list)

    # Auth
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)
    auth_self_registration: bool = False
    auth_invites_enabled: bool = True
    auth_invite_expire_days: int = Field(default=7, ge=1, le=90)
    auth_login_max_failures: int = Field(default=5, ge=1)
    auth_refresh_max_failures: int = Field(default=10, ge=1)
    auth_rate_limit_window_seconds: int = Field(default=300, ge=1)
    auth_enforce_login_origin: bool = True

    # Bluesky OAuth
    bluesky_client_url: str = ""

    # X (Twitter) OAuth
    x_client_id: str = ""
    x_client_secret: str = ""

    # Facebook OAuth
    facebook_app_id: str = ""
    facebook_app_secret: str = ""

    # Admin bootstrap
    admin_username: str = "admin"
    admin_password: str = INSECURE_BOOTSTRAP_SENTINEL
    admin_display_name: str = ""

    # Response hardening
    security_headers_enabled: bool = True
    cross_origin_opener_policy: str = "same-origin"
    cross_origin_resource_policy: str = "same-origin"
    permissions_policy: str = (
        "accelerometer=(), "
        "camera=(), "
        "geolocation=(), "
        "gyroscope=(), "
        "magnetometer=(), "
        "microphone=(), "
        "payment=(), "
        "usb=(), "
        "clipboard-write=(self), "
        "fullscreen=(self), "
        "web-share=(self)"
    )
    content_security_policy: str = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https: data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    def atproto_oauth_key_path(self) -> Path:
        """Return the persisted ATProto OAuth key path outside the content tree."""
        database_path = sqlite_database_path(self.database_url)
        if database_path is not None:
            return database_path.parent / ".agblogger-secrets" / "atproto-oauth-key.json"
        return self.content_dir.parent / ".agblogger-secrets" / "atproto-oauth-key.json"

    def validate_runtime_security(self) -> None:
        """Validate security-critical production settings."""
        if self.debug:
            return

        violations: list[str] = []
        if self.secret_key == INSECURE_DEV_SENTINEL or len(self.secret_key) < 32:
            violations.append(
                "SECRET_KEY must be overridden with a high-entropy value (>=32 chars)"
            )
        if self.admin_password == INSECURE_BOOTSTRAP_SENTINEL or len(self.admin_password) < 8:
            violations.append("ADMIN_PASSWORD must be overridden with a strong value (>=8 chars)")
        if not self.trusted_hosts:
            violations.append("TRUSTED_HOSTS must be configured in production")
        elif any(not is_valid_trusted_host(host) for host in self.trusted_hosts):
            violations.append(
                "TRUSTED_HOSTS must not use a catch-all wildcard; "
                "use explicit hosts or '*.example.com'"
            )
        if self.bluesky_client_url and not _is_valid_public_oauth_base_url(self.bluesky_client_url):
            violations.append(
                "BLUESKY_CLIENT_URL must be an https:// origin without path, "
                "query, fragment, or userinfo"
            )

        if violations:
            joined = "; ".join(violations)
            raise InternalServerError(f"Insecure production configuration: {joined}")
