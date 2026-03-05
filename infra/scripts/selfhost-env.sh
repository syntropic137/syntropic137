#!/usr/bin/env bash
# Selfhost environment loader — sources both .env files and resolves 1Password secrets.
# Sourced by justfile selfhost-* recipes to ensure Docker Compose sees all env vars.
#
# After sourcing this script, all variables from root .env (app config) and
# infra/.env (infra config) are exported, and any 1Password-managed secrets
# are resolved into the environment.

# 1. Source root .env (application config: API keys, GitHub creds, logging)
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# 2. Source infra/.env (infrastructure config: compose, resource limits, tunnel)
if [ -f infra/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source infra/.env
    set +a
fi

# 3. Derive vault name from APP_ENVIRONMENT (no separate OP_VAULT needed)
case "${APP_ENVIRONMENT:-}" in
    development) _OP_VAULT="syn137-dev" ;;
    production)  _OP_VAULT="syn137-prod" ;;
    beta)        _OP_VAULT="syn137-beta" ;;
    staging)     _OP_VAULT="syn137-staging" ;;
    *)           _OP_VAULT="" ;;
esac

# 4. Load 1Password service account token from macOS Keychain (vault-specific)
if [ -n "$_OP_VAULT" ] && [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    _VK="OP_SERVICE_ACCOUNT_TOKEN_$(echo "$_OP_VAULT" | tr '[:lower:]-' '[:upper:]_')"
    if [ "$(uname -s)" = "Darwin" ]; then
        _TOKEN=$(security find-generic-password -a "$USER" -s "SYN_${_VK}" -w 2>/dev/null || true)
        if [ -n "$_TOKEN" ]; then
            export OP_SERVICE_ACCOUNT_TOKEN="$_TOKEN"
            echo "  1Password: loaded from Keychain (SYN_${_VK})"
        fi
    elif [ -n "${!_VK:-}" ]; then
        export OP_SERVICE_ACCOUNT_TOKEN="${!_VK}"
        echo "  1Password: loaded from ${_VK}"
    fi
fi

# 5. Resolve 1Password secrets into env so Docker Compose sees them
# Use set -a so eval'd variables are automatically exported.
if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    _op_exports=$(uv run python scripts/op_env_export.py 2>/dev/null) || true
    if [ -n "${_op_exports:-}" ]; then
        set -a
        eval "$_op_exports"
        set +a
    fi
fi
