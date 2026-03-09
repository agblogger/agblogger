#!/bin/sh
set -e

# Fix ownership of data directories for bind mounts on Linux.
# Docker auto-creates bind mount directories as root:root, which prevents
# the non-root agblogger user from writing to them.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/content /data/db
    chown agblogger:agblogger /data/content /data/db
    exec gosu agblogger "$@"
fi

exec "$@"
