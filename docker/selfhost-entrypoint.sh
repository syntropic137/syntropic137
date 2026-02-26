#!/bin/sh
set -e

# Selfhost entrypoint — reads Docker secrets and exports env vars before
# exec-ing the container's original CMD. This ensures DATABASE_URL and
# REDIS_URL are built from secrets rather than dev defaults.

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

# Read GitHub private key from Docker secret (base64-encode for pydantic settings)
if [ -f /run/secrets/github_private_key ] && [ -z "${SYN_GITHUB_PRIVATE_KEY:-}" ]; then
  export SYN_GITHUB_PRIVATE_KEY="$(base64 < /run/secrets/github_private_key | tr -d '\n')"
fi

# Read GitHub webhook secret from Docker secret
if [ -f /run/secrets/github_webhook_secret ] && [ -z "${SYN_GITHUB_WEBHOOK_SECRET:-}" ]; then
  export SYN_GITHUB_WEBHOOK_SECRET="$(cat /run/secrets/github_webhook_secret)"
fi

exec "$@"
