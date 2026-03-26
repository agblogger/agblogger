"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import posixpath
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.api.admin import router as admin_router
from backend.api.analytics import admin_router as analytics_admin_router
from backend.api.analytics import public_router as analytics_public_router
from backend.api.auth import router as auth_router
from backend.api.content import router as content_router
from backend.api.crosspost import router as crosspost_router
from backend.api.health import router as health_router
from backend.api.labels import router as labels_router
from backend.api.pages import router as pages_router
from backend.api.posts import router as posts_router
from backend.api.render import router as render_router
from backend.api.sync import router as sync_router
from backend.config import Settings, sqlite_database_path
from backend.database import create_engine
from backend.filesystem.content_manager import ContentManager
from backend.models.base import CacheBase
from backend.services.csrf_service import validate_csrf_token
from backend.services.rate_limit_service import InMemoryRateLimiter
from backend.services.upload_limits import get_multipart_body_limit
from backend.version import get_version

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable
    from pathlib import Path

    from sqlalchemy import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine
    from starlette.responses import Response
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_TOML = (
    '[site]\ntitle = "My Blog"\ntimezone = "UTC"\n\n'
    '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
    '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
)
_DEFAULT_LABELS_TOML = "[labels]\n"


def _looks_like_post_asset_path(file_path: str) -> bool:
    """Identify asset requests using extension-based heuristics.

    Returns True when the path contains at least one ``/`` (i.e. ``<slug>/<file>``)
    and the leaf filename has a file extension other than ``.md``.
    A bare slug (no ``/``) is never an asset, even if it contains a dot.
    """
    if "/" not in file_path:
        return False

    leaf = posixpath.basename(file_path.rstrip("/"))
    if leaf == "" or leaf == "index.md":
        return False

    suffix = posixpath.splitext(leaf)[1]
    return suffix != "" and suffix != ".md"


class _MultipartBodyTooLargeError(Exception):
    """Raised when a multipart request exceeds the configured body-size limit."""


def _configure_logging(debug: bool) -> None:
    """Configure application logging."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        stream=sys.stdout,
        force=True,
    )
    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if debug else logging.WARNING)


def ensure_content_dir(content_dir: Path) -> None:
    """Ensure required content scaffold entries exist without overwriting existing files."""
    if content_dir.exists() and not content_dir.is_dir():
        msg = f"Content path exists but is not a directory: {content_dir}"
        raise NotADirectoryError(msg)

    content_dir.mkdir(parents=True, exist_ok=True)

    posts_dir = content_dir / "posts"
    posts_dir.mkdir(exist_ok=True)

    index_toml = content_dir / "index.toml"
    if not index_toml.exists():
        index_toml.write_text(_DEFAULT_INDEX_TOML, encoding="utf-8")
        logger.info("Created missing content scaffold file: %s", index_toml)

    labels_toml = content_dir / "labels.toml"
    if not labels_toml.exists():
        labels_toml.write_text(_DEFAULT_LABELS_TOML, encoding="utf-8")
        logger.info("Created missing content scaffold file: %s", labels_toml)


async def run_durable_migrations(engine: AsyncEngine) -> None:
    """Run Alembic migrations for durable tables.

    Passes the sync connection to Alembic via config.attributes so env.py
    reuses it instead of creating a new engine with asyncio.run().

    The Config object is built without ``config_file_name`` so that env.py
    skips ``fileConfig()`` and does not reconfigure the application's
    logging handlers at runtime.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "backend/migrations")

    def _do_upgrade(sync_conn: Connection) -> None:
        alembic_cfg.attributes["connection"] = sync_conn
        command.upgrade(alembic_cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_do_upgrade)


async def setup_cache_tables(engine: AsyncEngine) -> None:
    """Drop and recreate all cache tables.

    Cache tables use CacheBase and are regenerated from the filesystem
    on every startup.
    """
    async with engine.begin() as conn:
        # Drop posts_fts first (FTS5 virtual table that SQLAlchemy cannot
        # correctly drop/recreate via metadata.drop_all/create_all).
        await conn.execute(text("DROP TABLE IF EXISTS posts_fts"))
        await conn.run_sync(CacheBase.metadata.drop_all)
        await conn.run_sync(CacheBase.metadata.create_all)
        # Recreate FTS5 virtual table (not managed by ORM).
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                "title, content, content='posts_cache', content_rowid='id')"
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown."""
    settings: Settings = app.state.settings
    settings.validate_runtime_security()
    _configure_logging(settings.debug)
    logger.info("Starting AgBlogger (debug=%s)", settings.debug)
    app.state.content_write_lock = asyncio.Lock()
    # Ensure SQLite database parent directory exists
    database_path = sqlite_database_path(settings.database_url)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        engine, session_factory = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
    except Exception as exc:
        logger.critical(
            "Failed to initialize database: %s. Check database path and permissions.", exc
        )
        raise

    from backend.pandoc.renderer import close_renderer, init_renderer
    from backend.pandoc.server import PandocServer

    pandoc_server = PandocServer()
    pandoc_started = False
    try:
        try:
            await run_durable_migrations(engine)
        except Exception as exc:
            logger.critical("Failed to run database migrations: %s", exc, exc_info=True)
            raise

        try:
            await setup_cache_tables(engine)
        except Exception as exc:
            logger.critical("Failed to set up cache tables: %s", exc, exc_info=True)
            raise

        try:
            ensure_content_dir(settings.content_dir)
        except Exception as exc:
            logger.critical("Failed to initialize content directory: %s", exc)
            raise

        content_manager = ContentManager(content_dir=settings.content_dir)
        app.state.content_manager = content_manager

        from backend.services.git_service import GitService

        try:
            git_service = GitService(content_dir=settings.content_dir)
            await git_service.init_repo()
            app.state.git_service = git_service
        except Exception as exc:
            logger.critical("Failed to initialize git: %s. Ensure git is installed.", exc)
            raise

        from backend.crosspost.atproto_oauth import load_or_create_keypair
        from backend.crosspost.bluesky_oauth_state import OAuthStateStore

        try:
            oauth_key_path = settings.atproto_oauth_key_path()
            atproto_key, atproto_jwk = load_or_create_keypair(oauth_key_path)
            app.state.atproto_oauth_key = atproto_key
            app.state.atproto_oauth_jwk = atproto_jwk
        except Exception as exc:
            logger.critical("Failed to load or create OAuth keypair: %s", exc)
            raise

        app.state.bluesky_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.mastodon_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.x_oauth_state = OAuthStateStore(ttl_seconds=600)
        app.state.facebook_oauth_state = OAuthStateStore(ttl_seconds=600)

        from backend.services.auth_service import ensure_admin_user

        try:
            async with session_factory() as session:
                await ensure_admin_user(session, settings)
        except Exception as exc:
            logger.critical("Failed to ensure admin user: %s", exc)
            raise

        try:
            await pandoc_server.start()
            pandoc_started = True
            app.state.pandoc_server = pandoc_server
            init_renderer(pandoc_server)
        except Exception as exc:
            logger.critical("Failed to start pandoc server: %s. Ensure pandoc is installed.", exc)
            raise

        from backend.services.cache_service import rebuild_cache

        try:
            post_count, warnings = await rebuild_cache(session_factory, content_manager)
            logger.info("Indexed %d posts from filesystem", post_count)
            for warning in warnings:
                logger.warning("Cache rebuild: %s", warning)
        except Exception as exc:
            logger.critical("Failed to rebuild cache: %s", exc)
            raise

        yield
    finally:
        from backend.services.analytics_service import close_analytics_client

        try:
            await close_analytics_client()
        except Exception as exc:
            logger.error("Error during analytics client shutdown: %s", exc, exc_info=True)

        try:
            await close_renderer()
        except Exception as exc:
            logger.error("Error during renderer shutdown: %s", exc, exc_info=True)

        if pandoc_started:
            try:
                await pandoc_server.stop()
            except Exception as exc:
                logger.error("Error during pandoc server shutdown: %s", exc, exc_info=True)

        try:
            await engine.dispose()
        except Exception as exc:
            logger.error("Error during engine disposal: %s", exc, exc_info=True)

        logger.info("AgBlogger stopped")


class _ProxyHeadersMiddleware:
    """Trust ``X-Forwarded-Proto`` and ``X-Forwarded-For`` from known proxies.

    When ``TRUSTED_PROXY_IPS`` is configured, this middleware rewrites the ASGI
    scope so that ``request.url.scheme``, ``request.base_url``, and
    ``request.client`` reflect the public-facing connection rather than the
    internal proxy-to-backend hop.  This is essential for TLS-terminating
    reverse proxies (e.g. Caddy) where the backend sees plain HTTP but the
    client connected over HTTPS.
    """

    def __init__(self, app: ASGIApp, trusted_ips: list[str]) -> None:
        self.app = app
        self.trusted_ips = trusted_ips

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and self.trusted_ips:
            client = scope.get("client")
            if client and self._is_trusted(client[0]):
                # Iterate the raw header list to pick the FIRST occurrence of each
                # header.  dict(scope["headers"]) would silently drop duplicates,
                # keeping only the last value — wrong for X-Forwarded-For.
                proto: bytes | None = None
                xff: bytes | None = None
                for name, value in scope["headers"]:
                    if proto is None and name == b"x-forwarded-proto":
                        proto = value
                    if xff is None and name == b"x-forwarded-for":
                        xff = value
                    if proto is not None and xff is not None:
                        break
                if proto is not None:
                    proto_str = proto.decode("latin-1")
                    if proto_str in ("http", "https"):
                        scope["scheme"] = proto_str
                    else:
                        logger.warning(
                            "Unexpected X-Forwarded-Proto value %r from trusted proxy; ignoring",
                            proto_str,
                        )
                if xff is not None:
                    scope["client"] = (xff.decode("latin-1").split(",")[0].strip(), 0)
        await self.app(scope, receive, send)

    def _is_trusted(self, client_ip: str) -> bool:
        from backend.net_utils import is_trusted_proxy

        return is_trusted_proxy(client_ip, self.trusted_ips)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()

    docs_enabled = settings.debug or settings.expose_docs

    app = FastAPI(
        title="AgBlogger",
        description="A markdown-first blogging platform",
        version=get_version(),
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.rate_limiter = InMemoryRateLimiter()

    app.add_middleware(GZipMiddleware, minimum_size=500)

    cors_origins = (
        settings.cors_origins
        if settings.cors_origins
        else (["http://localhost:5173", "http://localhost:8000"] if settings.debug else [])
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    trusted_hosts = settings.trusted_hosts or (
        ["localhost", "127.0.0.1", "::1", "test", "testserver"] if settings.debug else []
    )
    # Always allow loopback for container health checks (not reachable externally).
    if trusted_hosts and "127.0.0.1" not in trusted_hosts:
        trusted_hosts = [*trusted_hosts, "127.0.0.1"]
    if trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

    # Starlette wraps middleware in the reverse of registration order: the last
    # middleware added becomes the outermost layer and therefore runs FIRST on
    # incoming requests.  Consequently, _ProxyHeadersMiddleware must be added
    # AFTER TrustedHostMiddleware so that it wraps around it and executes before
    # it at request time.  This ensures scope["scheme"] and scope["client"] are
    # rewritten from forwarded headers before TrustedHostMiddleware (or any
    # other middleware) inspects them.
    if settings.trusted_proxy_ips:
        app.add_middleware(_ProxyHeadersMiddleware, trusted_ips=settings.trusted_proxy_ips)

    @app.middleware("http")
    async def multipart_request_limits(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_type = request.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return await call_next(request)

        limit = get_multipart_body_limit(request.url.path)
        if limit is None:
            return await call_next(request)

        content_length = request.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Multipart request body too large"},
                    )
            except ValueError:
                logger.warning("Invalid Content-Length header on %s", request.url.path)

        received = 0
        original_receive = request._receive

        async def limited_receive() -> Message:
            nonlocal received
            message = await original_receive()
            if message["type"] != "http.request":
                return message
            body = message.get("body", b"")
            if isinstance(body, bytes):
                received += len(body)
                if received > limit:
                    raise _MultipartBodyTooLargeError
            return message

        request._receive = limited_receive
        try:
            return await call_next(request)
        except _MultipartBodyTooLargeError:
            return JSONResponse(
                status_code=413,
                content={"detail": "Multipart request body too large"},
            )

    @app.middleware("http")
    async def csrf_protection(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(
            "/api/"
        ):
            auth_header = request.headers.get("Authorization", "")
            has_bearer = auth_header.lower().startswith("bearer ")
            access_cookie = request.cookies.get("access_token")
            if (
                access_cookie
                and not has_bearer
                and request.url.path
                not in {
                    "/api/auth/login",
                    "/api/auth/token-login",
                }
            ):
                header_token = request.headers.get("X-CSRF-Token")
                if header_token is None or not validate_csrf_token(
                    access_cookie,
                    header_token,
                    settings.secret_key,
                ):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Invalid CSRF token"},
                    )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if settings.security_headers_enabled:
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            if settings.cross_origin_opener_policy:
                response.headers.setdefault(
                    "Cross-Origin-Opener-Policy",
                    settings.cross_origin_opener_policy,
                )
            if settings.cross_origin_resource_policy:
                response.headers.setdefault(
                    "Cross-Origin-Resource-Policy",
                    settings.cross_origin_resource_policy,
                )
            if settings.permissions_policy:
                response.headers.setdefault("Permissions-Policy", settings.permissions_policy)
            if settings.content_security_policy:
                response.headers.setdefault(
                    "Content-Security-Policy",
                    settings.content_security_policy,
                )
        return response

    app.include_router(health_router)
    app.include_router(admin_router)
    app.include_router(analytics_admin_router)
    app.include_router(analytics_public_router)
    app.include_router(auth_router)
    app.include_router(content_router)
    app.include_router(posts_router)
    app.include_router(labels_router)
    app.include_router(pages_router)
    app.include_router(render_router)
    app.include_router(sync_router)
    app.include_router(crosspost_router)

    # Global exception handlers — safety net for unhandled exceptions

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = err.get("loc", ())
            field = str(loc[-1]) if loc else "unknown"
            errors.append({"field": field, "message": err.get("msg", "Invalid value")})
        logger.warning(
            "RequestValidationError in %s %s: %s",
            request.method,
            request.url.path,
            errors,
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    from backend.pandoc.renderer import RenderError

    @app.exception_handler(RenderError)
    async def render_error_handler(request: Request, exc: RenderError) -> JSONResponse:
        logger.error(
            "RenderError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Rendering service unavailable"},
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        logger.error(
            "RuntimeError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(OSError)
    async def os_error_handler(request: Request, exc: OSError) -> JSONResponse:
        if isinstance(exc, ConnectionError):
            logger.error(
                "ConnectionError in %s %s: %s",
                request.method,
                request.url.path,
                exc,
                exc_info=exc,
            )
            return JSONResponse(
                status_code=502,
                content={"detail": "External service connection failed"},
            )
        if isinstance(exc, TimeoutError):
            logger.error(
                "TimeoutError in %s %s: %s",
                request.method,
                request.url.path,
                exc,
                exc_info=exc,
            )
            return JSONResponse(
                status_code=504,
                content={"detail": "Operation timed out"},
            )
        logger.error("OSError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Storage operation failed"},
        )

    @app.exception_handler(yaml.YAMLError)
    async def yaml_error_handler(request: Request, exc: yaml.YAMLError) -> JSONResponse:
        logger.error("YAMLError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid content format"},
        )

    @app.exception_handler(json.JSONDecodeError)
    async def json_error_handler(request: Request, exc: json.JSONDecodeError) -> JSONResponse:
        logger.error(
            "JSONDecodeError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Data integrity error"},
        )

    from backend.exceptions import ExternalServiceError, InternalServerError

    @app.exception_handler(InternalServerError)
    async def internal_server_error_handler(
        request: Request, exc: InternalServerError
    ) -> JSONResponse:
        logger.error(
            "InternalServerError in %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(ExternalServiceError)
    async def external_service_error_handler(
        request: Request, exc: ExternalServiceError
    ) -> JSONResponse:
        logger.error(
            "ExternalServiceError in %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "External service error"},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        logger.error("ValueError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        # Always use a generic message. Intentional business-logic ValueErrors are
        # caught at the endpoint level and return specific messages there. This
        # global handler is a safety net for unexpected ValueErrors, which may
        # originate from library code (int(), datetime.fromisoformat(), etc.) and
        # could leak internal details if str(exc) were forwarded.
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid value"},
        )

    @app.exception_handler(TypeError)
    async def type_error_handler(request: Request, exc: TypeError) -> JSONResponse:
        logger.error(
            "[BUG] TypeError in %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(subprocess.CalledProcessError)
    async def subprocess_error_handler(
        request: Request, exc: subprocess.CalledProcessError
    ) -> JSONResponse:
        logger.error(
            "CalledProcessError in %s %s: cmd=%s exit=%d",
            request.method,
            request.url.path,
            exc.cmd,
            exc.returncode,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "External process failed"},
        )

    @app.exception_handler(subprocess.TimeoutExpired)
    async def timeout_expired_handler(
        request: Request, exc: subprocess.TimeoutExpired
    ) -> JSONResponse:
        logger.error(
            "TimeoutExpired in %s %s: timeout=%ss",
            request.method,
            request.url.path,
            exc.timeout,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "External process timed out"},
        )

    @app.exception_handler(UnicodeDecodeError)
    async def unicode_error_handler(request: Request, exc: UnicodeDecodeError) -> JSONResponse:
        logger.error(
            "UnicodeDecodeError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid content encoding"},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.error(
            "IntegrityError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "Data conflict"},
        )

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
        logger.error(
            "[BUG] KeyError in %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(OperationalError)
    async def operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
        logger.error(
            "OperationalError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Database temporarily unavailable"},
        )

    import httpx

    @app.exception_handler(httpx.HTTPError)
    async def httpx_error_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
        logger.error(
            "httpx.HTTPError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "External service request failed"},
        )

    @app.exception_handler(AttributeError)
    async def attribute_error_handler(request: Request, exc: AttributeError) -> JSONResponse:
        logger.error(
            "[BUG] AttributeError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(IndexError)
    async def index_error_handler(request: Request, exc: IndexError) -> JSONResponse:
        logger.error(
            "[BUG] IndexError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(Exception)
    async def catch_all_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled %s in %s %s: %s",
            type(exc).__name__,
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    # Post route — serves OG-enriched SPA HTML for post views, and redirects
    # asset requests to the content API.  Must be registered before the
    # StaticFiles catch-all.
    @app.get("/post/{file_path:path}", include_in_schema=False, response_model=None)
    async def post_route(file_path: str, request: Request) -> HTMLResponse | RedirectResponse:
        if ".." in file_path.split("/"):
            logger.warning("Path traversal attempt in post asset URL: %s", file_path)
            return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        content_path = request.app.state.settings.content_dir / "posts" / file_path
        if (
            content_path.exists() and content_path.is_file() and content_path.suffix != ".md"
        ) or _looks_like_post_asset_path(file_path):
            return RedirectResponse(
                url=f"/api/content/posts/{file_path}",
                status_code=301,
            )

        # Post view: /post/<slug> → serve SPA HTML with OG tags
        from backend.models.post import PostCache
        from backend.services.datetime_service import format_iso
        from backend.services.opengraph_service import inject_og_tags, strip_html_tags

        frontend_dir_path: Path = request.app.state.settings.frontend_dir
        index_path = frontend_dir_path / "index.html"

        # Read and cache the base index.html
        base_html: str | None = getattr(request.app.state, "_og_base_html", None)
        if base_html is None:
            try:
                base_html = await asyncio.to_thread(index_path.read_text, encoding="utf-8")
                request.app.state._og_base_html = base_html
            except OSError:
                logger.warning("index.html not found at %s", index_path)
                return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

        # Look up the post by exact canonical file path or canonical slug.
        from backend.utils.slug import is_directory_post_path, resolve_slug_candidates

        slug = file_path
        post = None
        try:
            session_factory = request.app.state.session_factory
            async with session_factory() as session:
                candidates: tuple[str, ...]
                if is_directory_post_path(file_path):
                    candidates = (file_path,)
                elif file_path.startswith("posts/"):
                    candidates = ()
                else:
                    candidates = resolve_slug_candidates(slug)

                for candidate in candidates:
                    stmt = select(PostCache).where(PostCache.file_path == candidate)
                    result = await session.execute(stmt)
                    post = result.scalar_one_or_none()
                    if post is not None:
                        break
        except SQLAlchemyError:
            logger.exception("DB error looking up post for OG tags: %s", slug)
            return HTMLResponse(base_html)

        if post is None or post.is_draft:
            return HTMLResponse(base_html)

        description = ""
        if post.rendered_excerpt:
            description = strip_html_tags(post.rendered_excerpt)

        content_manager: ContentManager = request.app.state.content_manager
        site_name = content_manager.site_config.title

        enriched = inject_og_tags(
            base_html,
            title=post.title,
            description=description,
            url=str(request.url),
            site_name=site_name,
            author=post.author,
            published_time=format_iso(post.created_at),
            modified_time=format_iso(post.modified_at),
        )
        return HTMLResponse(enriched)

    # Serve frontend static files in production
    frontend_dir = settings.frontend_dir
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")

    return app


app = create_app()
