"""Shared test fixtures for AgBlogger."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import Settings
from backend.main import create_app
from backend.services.git_service import GitService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

logger = logging.getLogger(__name__)

TEST_SECRET_KEY = "test-secret-key-with-at-least-32-characters"

# Module-level flag: once pandoc server mode is known to be broken for this
# process, skip all further attempts and use the subprocess fallback directly.
_pandoc_server_broken = False

# Modules that import render_markdown by name and may hold direct references.
_RENDER_MARKDOWN_IMPORT_SITES = (
    "backend.services.cache_service",
    "backend.services.admin_service",
    "backend.api.posts",
    "backend.api.render",
)


def _restore_original_renderer() -> None:
    """Restore the original renderer functions on all patched modules.

    Called during fixture teardown so that unit tests for the renderer module
    see the real (HTTP-based) function rather than the subprocess shim.
    Also resets the ``_pandoc_server_broken`` flag so the next test retries
    server mode (important for pytest-xdist where each worker manages its own
    pandoc server lifecycle).
    """
    global _pandoc_server_broken
    _pandoc_server_broken = False

    import sys

    import backend.pandoc.renderer as _renderer_mod

    original = getattr(_renderer_mod, "_original_render_markdown", None)
    original_excerpt = getattr(_renderer_mod, "_original_render_markdown_excerpt", None)
    if original is None or original_excerpt is None:
        return

    _renderer_mod.render_markdown = original
    _renderer_mod.render_markdown_excerpt = original_excerpt
    for mod_name in _RENDER_MARKDOWN_IMPORT_SITES:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "render_markdown"):
            mod.render_markdown = original  # type: ignore[attr-defined]
        if mod is not None and hasattr(mod, "render_markdown_excerpt"):
            mod.render_markdown_excerpt = original_excerpt  # type: ignore[attr-defined]


def _install_subprocess_fallback() -> None:
    """Monkey-patch renderer functions to use subprocess instead of the HTTP API.

    Sets the module-level ``_pandoc_server_broken`` flag so that subsequent
    calls to ``create_test_client`` skip the server startup entirely.

    Patches both the canonical module and all known import sites so that
    modules which already hold a direct reference also pick up the shim.
    """
    global _pandoc_server_broken
    _pandoc_server_broken = True

    import sys

    import backend.pandoc.renderer as _renderer_mod

    # If already monkey-patched, skip.
    if getattr(_renderer_mod.render_markdown, "_is_subprocess_fallback", False):
        return

    async def _subprocess_render_common(markdown: str, *, from_format: str, excerpt: bool) -> str:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "pandoc",
                "-f",
                from_format,
                "-t",
                "html5",
                "--katex",
                "--highlight-style=pygments",
                "--wrap=none",
            ],
            input=markdown,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Pandoc failed: {result.stderr[:200]}")
        if excerpt:
            sanitized = _renderer_mod._sanitize_excerpt_html(result.stdout)
        else:
            sanitized = _renderer_mod._sanitize_html(result.stdout)
        return _renderer_mod._add_heading_anchors(sanitized)

    async def _subprocess_render(markdown: str) -> str:
        """Fallback renderer using subprocess (for tests when server mode unavailable)."""
        return await _subprocess_render_common(
            markdown,
            from_format="markdown+emoji+lists_without_preceding_blankline+mark",
            excerpt=False,
        )

    async def _subprocess_render_excerpt(markdown: str) -> str:
        """Fallback excerpt renderer using subprocess."""
        return await _subprocess_render_common(
            markdown,
            from_format="markdown-raw_html+emoji+lists_without_preceding_blankline+mark",
            excerpt=True,
        )

    _subprocess_render._is_subprocess_fallback = True  # type: ignore[attr-defined]
    _subprocess_render_excerpt._is_subprocess_fallback = True  # type: ignore[attr-defined]

    # Save original so it can be restored on cleanup.
    if not hasattr(_renderer_mod, "_original_render_markdown"):
        _renderer_mod._original_render_markdown = _renderer_mod.render_markdown  # type: ignore[attr-defined]
    if not hasattr(_renderer_mod, "_original_render_markdown_excerpt"):
        _renderer_mod._original_render_markdown_excerpt = (  # type: ignore[attr-defined]
            _renderer_mod.render_markdown_excerpt
        )

    _renderer_mod.render_markdown = _subprocess_render
    _renderer_mod.render_markdown_excerpt = _subprocess_render_excerpt

    # Patch modules that may have already imported render_markdown by reference.
    for mod_name in _RENDER_MARKDOWN_IMPORT_SITES:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "render_markdown"):
            mod.render_markdown = _subprocess_render  # type: ignore[attr-defined]
        if mod is not None and hasattr(mod, "render_markdown_excerpt"):
            mod.render_markdown_excerpt = _subprocess_render_excerpt  # type: ignore[attr-defined]


@asynccontextmanager
async def create_test_client(settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Create an HTTP test client with a fully initialized app.

    Manually performs the work of the application lifespan (DB, FTS, git,
    admin user, cache rebuild) because ASGITransport does not trigger it.
    """
    from backend.database import create_engine as create_db_engine
    from backend.filesystem.content_manager import ContentManager
    from backend.main import run_durable_migrations, setup_cache_tables
    from backend.pandoc.renderer import close_renderer, init_renderer
    from backend.pandoc.server import PandocServer
    from backend.services.auth_service import ensure_admin_user
    from backend.services.cache_service import rebuild_cache

    app = create_app(settings)
    settings.validate_runtime_security()

    engine, session_factory = create_db_engine(settings)
    pandoc_server: PandocServer | None = None
    try:
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.settings = settings

        await run_durable_migrations(engine)
        await setup_cache_tables(engine)

        content_manager = ContentManager(content_dir=settings.content_dir)
        app.state.content_manager = content_manager
        app.state.content_write_lock = asyncio.Lock()

        git_service = GitService(content_dir=settings.content_dir)
        await git_service.init_repo()
        app.state.git_service = git_service

        # mutmut stats/test runs can perturb cryptography internals in instrumented
        # modules.  For mutation-testing contexts, these state fields only need to
        # exist.
        # Note: MUTANT_UNDER_TEST is a standard env var set by mutmut itself
        # when running mutants — do not rename it.
        in_mutation_mode = "MUTANT_UNDER_TEST" in os.environ
        from backend.crosspost.bluesky_oauth_state import OAuthStateStore

        if in_mutation_mode:
            atproto_key: object = object()
            atproto_jwk: dict[str, str] = {
                "kty": "EC",
                "crv": "P-256",
                "x": "mutmut-x",
                "y": "mutmut-y",
                "kid": "mutmut",
            }
        else:
            from backend.crosspost.atproto_oauth import load_or_create_keypair

            oauth_key_path = settings.atproto_oauth_key_path()
            atproto_key, atproto_jwk = load_or_create_keypair(oauth_key_path)
        app.state.atproto_oauth_key = atproto_key
        app.state.atproto_oauth_jwk = atproto_jwk
        app.state.bluesky_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.mastodon_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.x_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.facebook_oauth_state = OAuthStateStore(ttl_seconds=600)

        async with session_factory() as session:
            await ensure_admin_user(session, settings, content_manager=content_manager)

        test_port = 13100 + os.getpid() % 900
        if not _pandoc_server_broken:
            try:
                pandoc_server = PandocServer(port=test_port)
                await pandoc_server.start()
                app.state.pandoc_server = pandoc_server
                init_renderer(pandoc_server)
                # Verify the server can actually render (catches broken builds
                # where +server is listed but the runtime crashes on first
                # request).
                from backend.pandoc.renderer import render_markdown

                await render_markdown("test")
            except Exception:
                logger.warning("Pandoc server unavailable in tests, using subprocess fallback")
                await close_renderer()
                if pandoc_server is not None:
                    await pandoc_server.stop()
                pandoc_server = None
                _install_subprocess_fallback()
        else:
            _install_subprocess_fallback()

        await rebuild_cache(session_factory, content_manager)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        await close_renderer()
        if pandoc_server is not None:
            await pandoc_server.stop()
        _restore_original_renderer()
        await engine.dispose()


async def create_test_user(
    client: AsyncClient,
    username: str,
    email: str,
    password: str,
) -> None:
    """Create a user directly in the database.

    Uses the app's session factory to insert the user, bypassing the API layer.
    """
    from backend.models.user import AdminUser
    from backend.services.auth_service import hash_password
    from backend.utils.datetime import format_iso, now_utc

    transport = client._transport
    app = getattr(transport, "app", None)
    assert app is not None, "Test client must use ASGITransport"
    session_factory = app.state.session_factory
    now = format_iso(now_utc())
    async with session_factory() as session:
        user = AdminUser(
            username=username,
            email=email,
            password_hash=hash_password(password),
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()


@pytest.fixture(autouse=True)
def _reset_analytics_globals():
    """Reset analytics service module-level state between tests.

    Saves and restores _goatcounter_token, _token_warning_issued, _http_client,
    and _background_tasks so that mutations in one test do not leak into others.
    """
    import backend.services.analytics_service as svc

    saved_token = svc._goatcounter_token
    saved_warning = svc._token_warning_issued
    saved_client = svc._http_client
    saved_tasks = svc._background_tasks.copy()

    svc._goatcounter_token = None
    svc._token_warning_issued = False
    svc._http_client = None
    svc._background_tasks = set()

    yield

    svc._goatcounter_token = saved_token
    svc._token_warning_issued = saved_warning
    svc._http_client = saved_client
    svc._background_tasks = saved_tasks


@pytest.fixture
def tmp_content_dir(tmp_path: Path) -> Path:
    """Create a temporary content directory with default structure."""
    content = tmp_path / "content"
    content.mkdir()
    (content / "posts").mkdir()
    (content / "assets").mkdir()

    # Write minimal index.toml
    (content / "index.toml").write_text(
        '[site]\ntitle = "Test Blog"\ntimezone = "UTC"\n\n'
        '[[pages]]\nid = "timeline"\ntitle = "Posts"\n'
    )
    (content / "labels.toml").write_text("[labels]\n")

    return content


@pytest.fixture
def test_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    """Create test settings with temporary paths."""
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key=TEST_SECRET_KEY,
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=tmp_path / "frontend",
    )


@pytest.fixture
async def git_service(tmp_content_dir: Path) -> GitService:
    """Create a git service for the temporary content directory."""
    gs = GitService(tmp_content_dir)
    await gs.init_repo()
    return gs


@pytest.fixture
async def db_engine(test_settings: Settings) -> AsyncGenerator[AsyncEngine]:
    """Create a test database engine."""
    engine = create_async_engine(
        test_settings.database_url,
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create a test database session factory."""
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Create a test database session."""
    async with db_session_factory() as session:
        yield session
