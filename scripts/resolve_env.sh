#!/usr/bin/env bash
# resolve_env.sh — Source .env files and resolve 1Password secrets.
#
# Usage (must be sourced, not executed):
#   source scripts/resolve_env.sh
#
# After sourcing, all env vars from .env, infra/.env, and 1Password
# are exported into the current shell. Docker Compose inherits them.

set -a  # auto-export all vars

if [ -f .env ]; then source .env; fi
if [ -f infra/.env ]; then source infra/.env; fi

# Resolve 1Password secrets for known environments
case "${APP_ENVIRONMENT:-}" in
    development|production|beta|staging)
        _op_exports=$(uv run python scripts/op_env_export.py 2>/dev/null) && eval "$_op_exports" || true ;;
esac

set +a
