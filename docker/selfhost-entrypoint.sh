#!/bin/sh
set -e

# Selfhost entrypoint — reads Docker secrets, matches Docker socket GID,
# and drops privileges to 'aef' before exec-ing the container's CMD.
#
# This ensures DATABASE_URL and REDIS_URL are built from secrets rather
# than dev defaults, and the 'aef' user can access the Docker socket for
# spawning workspace containers.
#
# GitHub secrets (SYN_GITHUB_PRIVATE_KEY, SYN_GITHUB_WEBHOOK_SECRET) are
# passed as env vars via compose (sourced from 1Password or .env), not as
# Docker secret files.

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

# Match Docker socket GID so 'aef' user can spawn workspace containers
# (Only runs in dashboard container — other containers skip this block)
if [ -S /var/run/docker.sock ]; then
  SOCK_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock 2>/dev/null)
  if [ -n "$SOCK_GID" ] && [ "$SOCK_GID" != "0" ]; then
    # Linux: create group matching socket GID and add aef to it
    groupadd -g "$SOCK_GID" -o docker-host 2>/dev/null || true
    usermod -aG docker-host aef 2>/dev/null || true
  else
    # macOS Docker Desktop: socket owned by root:root — make world-accessible
    # (chgrp on bind-mounted sockets doesn't persist on macOS)
    chmod 666 /var/run/docker.sock 2>/dev/null || true
  fi
fi

# Drop privileges to 'aef' if gosu is available (dashboard container).
# Other containers (event-store) don't have gosu and run as their own user.
if command -v gosu >/dev/null 2>&1 && id aef >/dev/null 2>&1; then
  exec gosu aef "$@"
else
  exec "$@"
fi
