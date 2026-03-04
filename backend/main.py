"""FastAPI application entry point."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.api.admin import router as admin_router
from backend.api.auth import router as auth_router
from backend.api.content import router as content_router
from backend.api.crosspost import router as crosspost_router
from backend.api.health import router as health_router
from backend.api.labels import router as labels_router
from backend.api.pages import router as pages_router
from backend.api.posts import router as posts_router
from backend.api.render import router as render_router
from backend.api.sync import router as sync_router
from backend.config import Settings
from backend.database import create_engine
from backend.filesystem.content_manager import ContentManager
from backend.models.base import Base
from backend.services.csrf_service import validate_csrf_token
from backend.services.rate_limit_service import InMemoryRateLimiter
from backend.services.upload_limits import get_multipart_body_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from starlette.responses import Response
    from starlette.types import Message

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_TOML = (
    '[site]\ntitle = "My Blog"\ntimezone = "UTC"\n\n'
    '[[pages]]\nid = "timeline"\ntitle = "Posts"\n\n'
    '[[pages]]\nid = "labels"\ntitle = "Labels"\n'
)
_DEFAULT_LABELS_TOML = "[labels]\n"


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

    if not content_dir.exists():
        logger.info("Creating default content directory at %s", content_dir)
        content_dir.mkdir(parents=True)

    posts_dir = content_dir / "posts"
    if not posts_dir.exists():
        posts_dir.mkdir()
        logger.info("Created missing content scaffold directory: %s", posts_dir)

    index_toml = content_dir / "index.toml"
    if not index_toml.exists():
        index_toml.write_text(_DEFAULT_INDEX_TOML, encoding="utf-8")
        logger.info("Created missing content scaffold file: %s", index_toml)

    labels_toml = content_dir / "labels.toml"
    if not labels_toml.exists():
        labels_toml.write_text(_DEFAULT_LABELS_TOML, encoding="utf-8")
        logger.info("Created missing content scaffold file: %s", labels_toml)


async def _ensure_crosspost_user_id_column(app: FastAPI) -> None:
    """Backfill schema for cross_posts.user_id on pre-existing databases."""
    try:
        engine = app.state.engine
        async with engine.begin() as conn:
            result = await conn.execute(text("PRAGMA table_info(cross_posts)"))
            columns = {str(row[1]) for row in result}
            if "user_id" in columns:
                return
            await conn.execute(text("ALTER TABLE cross_posts ADD COLUMN user_id INTEGER"))
            logger.warning(
                "Added missing cross_posts.user_id column. Existing history rows remain unscoped."
            )
    except Exception as exc:
        logger.error("Failed to ensure crosspost user_id column: %s", exc)
        raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown."""
    settings: Settings = app.state.settings
    settings.validate_runtime_security()
    _configure_logging(settings.debug)
    logger.info("Starting AgBlogger (debug=%s)", settings.debug)

    # Ensure database directory exists (M16)
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        db_path = db_url.split("///", 1)[-1] if "///" in db_url else None
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        engine, session_factory = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
    except Exception as exc:
        logger.critical(
            "Failed to initialize database: %s. Check database path and permissions.", exc
        )
        raise

    try:
        async with engine.begin() as conn:
            # Drop cache tables so create_all always matches current schema.
            # These are regenerated from the filesystem on every startup.
            drop_cache_tables_sql = (
                "DROP TABLE IF EXISTS post_labels_cache",
                "DROP TABLE IF EXISTS label_parents_cache",
                "DROP TABLE IF EXISTS posts_fts",
                "DROP TABLE IF EXISTS posts_cache",
                "DROP TABLE IF EXISTS labels_cache",
                "DROP TABLE IF EXISTS sync_manifest",
            )
            for statement in drop_cache_tables_sql:
                await conn.execute(text(statement))
            await conn.run_sync(Base.metadata.create_all)
        await _ensure_crosspost_user_id_column(app)
    except Exception as exc:
        logger.critical("Failed to create database schema: %s.", exc)
        raise

    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5("
                    "title, content, content='posts_cache', content_rowid='id')"
                )
            )
            await session.commit()
    except Exception as exc:
        logger.critical("Failed to create FTS5 virtual table: %s.", exc)
        raise

    try:
        ensure_content_dir(settings.content_dir)
    except Exception as exc:
        logger.critical(
            "Failed to initialize content directory at %s: %s.", settings.content_dir, exc
        )
        raise

    content_manager = ContentManager(content_dir=settings.content_dir)
    app.state.content_manager = content_manager

    from backend.services.git_service import GitService

    try:
        git_service = GitService(content_dir=settings.content_dir)
        await git_service.init_repo()
        app.state.git_service = git_service
    except Exception as exc:
        logger.critical(
            "Failed to initialize git repository at %s: %s. Ensure git is installed.",
            settings.content_dir,
            exc,
        )
        raise

    from backend.crosspost.atproto_oauth import load_or_create_keypair
    from backend.crosspost.bluesky_oauth_state import OAuthStateStore

    oauth_key_path = settings.content_dir / ".atproto-oauth-key.json"
    try:
        atproto_key, atproto_jwk = load_or_create_keypair(oauth_key_path)
        app.state.atproto_oauth_key = atproto_key
        app.state.atproto_oauth_jwk = atproto_jwk
    except Exception as exc:
        logger.critical("Failed to load or create OAuth keypair at %s: %s.", oauth_key_path, exc)
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
        logger.critical("Failed to ensure admin user: %s.", exc)
        raise

    from backend.pandoc.renderer import close_renderer, init_renderer
    from backend.pandoc.server import PandocServer

    pandoc_server = PandocServer()
    try:
        await pandoc_server.start()
    except Exception as exc:
        logger.critical("Failed to start pandoc server: %s", exc)
        raise
    app.state.pandoc_server = pandoc_server
    init_renderer(pandoc_server)

    from backend.services.cache_service import rebuild_cache

    try:
        async with session_factory() as session:
            post_count, warnings = await rebuild_cache(session, content_manager)
            logger.info("Indexed %d posts from filesystem", post_count)
            for warning in warnings:
                logger.warning("Cache rebuild: %s", warning)
    except Exception as exc:
        logger.critical("Failed to rebuild cache from filesystem: %s.", exc)
        raise

    yield

    try:
        await close_renderer()
    except Exception as exc:
        logger.error("Error during renderer shutdown: %s", exc, exc_info=True)

    try:
        await pandoc_server.stop()
    except Exception as exc:
        logger.error("Error during pandoc server shutdown: %s", exc, exc_info=True)

    try:
        await engine.dispose()
    except Exception as exc:
        logger.error("Error during engine disposal: %s", exc, exc_info=True)

    logger.info("AgBlogger stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()

    docs_enabled = settings.debug or settings.expose_docs

    app = FastAPI(
        title="AgBlogger",
        description="A markdown-first blogging platform",
        version="0.1.0",
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
    if trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

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
            if settings.content_security_policy:
                response.headers.setdefault(
                    "Content-Security-Policy",
                    settings.content_security_policy,
                )
        return response

    app.include_router(health_router)
    app.include_router(admin_router)
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
        if isinstance(exc, (NotImplementedError, RecursionError)):
            raise exc
        logger.error(
            "RuntimeError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal processing error"},
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
        message = str(exc) or "Invalid value"
        return JSONResponse(
            status_code=422,
            content={"detail": message},
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

    @app.exception_handler(UnicodeDecodeError)
    async def unicode_error_handler(request: Request, exc: UnicodeDecodeError) -> JSONResponse:
        logger.error(
            "UnicodeDecodeError in %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid content encoding"},
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

    # Serve frontend static files in production
    frontend_dir = settings.frontend_dir
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")

    return app


app = create_app()


def cli_entry() -> None:
    """CLI entry point for running the server."""
    import uvicorn

    settings: Settings = app.state.settings
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
