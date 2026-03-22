#!/bin/sh
set -e

# Fix ownership of data directories for bind mounts on Linux.
# Docker auto-creates bind mount directories as root:root, which prevents
# the non-root agblogger user from writing to them.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/content /data/db
    if ! chown -R agblogger:agblogger /data/content /data/db 2>&1; then
        echo "WARNING: chown failed for /data directories. The application may lack write access." >&2
    fi
    exec su-exec agblogger "$@"
fi

exec "$@"
