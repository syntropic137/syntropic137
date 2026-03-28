#!/bin/sh
set -e

# Selfhost entrypoint — reads Docker secrets and drops privileges to 'syn'.
#
# This ensures DATABASE_URL and REDIS_URL are built from secrets rather
# than dev defaults.
#
# GitHub App private key is mounted as a Docker secret at
# /run/secrets/github_app_private_key (preferred, tmpfs-backed).
# The app reads the file directly via SYN_GITHUB_APP_PRIVATE_KEY_FILE.
# SYN_GITHUB_WEBHOOK_SECRET is still passed as an env var.

# Read DB password from Docker secret if available
if [ -f /run/secrets/db_password ]; then
  POSTGRES_PASSWORD="$(cat /run/secrets/db_password)"
  export POSTGRES_PASSWORD
  DB_URL="postgres://${POSTGRES_USER:-syn}:${POSTGRES_PASSWORD}@timescaledb:5432/${POSTGRES_DB:-syn}"
  export DATABASE_URL="$DB_URL"
  export SYN_OBSERVABILITY_DB_URL="$DB_URL"
fi

# Read Redis password from Docker secret if available
if [ -f /run/secrets/redis_password ]; then
  REDIS_PASSWORD="$(cat /run/secrets/redis_password)"
  export REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"
fi

# Read MinIO password from Docker secret if available
if [ -f /run/secrets/minio_password ]; then
  export SYN_STORAGE_MINIO_SECRET_KEY="$(cat /run/secrets/minio_password)"
fi

# Drop privileges to 'syn' if running as root and gosu is available.
# With docker-socket-proxy, the api starts as 'syn' directly — skip gosu.
# Other containers (event-store) don't have gosu and run as their own user.
if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1 && id syn >/dev/null 2>&1; then
  exec gosu syn "$@"
fi
exec "$@"
