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

# ── Stage 3: Production image ───────────────────────────────────────
FROM python:3.14-slim

# Install pandoc from GitHub releases (pinned version with +server support)
ARG PANDOC_VERSION=3.8.3
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${ARCH}.deb" \
       -o /tmp/pandoc.deb \
    && dpkg -i /tmp/pandoc.deb \
    && rm /tmp/pandoc.deb \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN useradd --create-home --shell /bin/bash agblogger

WORKDIR /app

# Install server wheel
COPY --from=server-wheel-build /tmp/dist/ /tmp/dist/
RUN uv pip install --system /tmp/dist/agblogger_server-*.whl \
    && rm -rf /tmp/dist

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directories
RUN mkdir -p /data/content /data/db && chown -R agblogger:agblogger /data

# Content and database volumes
VOLUME /data/content
VOLUME /data/db

ENV CONTENT_DIR=/data/content
ENV DATABASE_URL=sqlite+aiosqlite:///data/db/agblogger.db
ENV FRONTEND_DIR=/app/frontend/dist
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

USER agblogger

CMD ["agblogger-server"]
