# ── Stage 1: Build frontend ──────────────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Build server wheel ──────────────────────────────────────
FROM python:3.14-slim AS server-wheel-build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY packaging/server/pyproject.toml /app/server-src/pyproject.toml
COPY backend/ /app/server-src/backend/
RUN uv build --wheel /app/server-src --out-dir /tmp/dist

# ── Stage 3: Fetch pandoc ────────────────────────────────────────────
FROM alpine:3.21 AS pandoc-fetch
ARG PANDOC_VERSION=3.8.3
RUN apk add --no-cache curl \
    && ARCH=$(uname -m) \
    && case "$ARCH" in x86_64) ARCH=amd64;; aarch64) ARCH=arm64;; esac \
    && curl -fsSL "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-${ARCH}.tar.gz" \
       | tar xz -C /tmp \
    && mv "/tmp/pandoc-${PANDOC_VERSION}/bin/pandoc" /usr/local/bin/pandoc

# ── Stage 4: Production image ───────────────────────────────────────
FROM python:3.14-alpine

# Install runtime dependencies (Alpine has no systemd/libudev, smaller attack surface)
RUN apk upgrade --no-cache \
    && apk add --no-cache git su-exec

# Copy pandoc (statically-linked binary)
COPY --from=pandoc-fetch /usr/local/bin/pandoc /usr/local/bin/pandoc

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN adduser -D -s /bin/sh agblogger

WORKDIR /app

# Install server wheel (uv is removed after install – it is not needed at runtime)
COPY --from=server-wheel-build /tmp/dist/ /tmp/dist/
RUN uv pip install --system /tmp/dist/agblogger_server-*.whl \
    && rm -rf /tmp/dist \
    && rm /usr/local/bin/uv

# Copy Alembic migrations (not in the wheel — Alembic needs a filesystem path)
COPY backend/migrations ./backend/migrations

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Copy version file for runtime version detection
COPY VERSION ./

# Create data directories
RUN mkdir -p /data/content /data/db && chown -R agblogger:agblogger /data

# Content and database volumes
VOLUME /data/content
VOLUME /data/db

ENV CONTENT_DIR=/data/content
ENV DATABASE_URL=sqlite+aiosqlite:////data/db/agblogger.db
ENV FRONTEND_DIR=/app/frontend/dist
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# Health check (wget is provided by busybox on Alpine — no extra dependencies needed)
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=3 \
    CMD wget -qO/dev/null http://127.0.0.1:8000/api/health

COPY docker-entrypoint.sh /usr/local/bin/

USER agblogger

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["agblogger-server"]
