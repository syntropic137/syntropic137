#!/usr/bin/env bash
# Validate all Docker Compose overlay combinations parse correctly.
# Called by: just check-compose-overlays (QA + CI gate)
# See: ADR-034, ADR-060
set -euo pipefail

cd "$(dirname "$0")/../docker"

echo "Validating compose overlays..."

# Dev overlay
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml config --services > /dev/null
echo "  dev: ok"

# Selfhost overlay
docker compose -f docker-compose.yaml -f docker-compose.selfhost.yaml config --services > /dev/null
echo "  selfhost: ok"

# On-demand overlay (needs env vars that would come from .env.ondemand-{name})
SYN_ENV_NAME=validate SYN_ENV_PORT_GATEWAY=28137 SYN_ENV_PORT_API=29137 \
  SYN_ENV_PORT_DB=25432 SYN_ENV_PORT_ES=60051 SYN_ENV_PORT_COLLECTOR=28080 \
  SYN_ENV_PORT_MINIO=29000 SYN_ENV_PORT_MINIO_CONSOLE=29001 \
  SYN_ENV_PORT_REDIS=26379 SYN_ENV_PORT_ENVOY=28081 \
  SYN_AGENT_NETWORK=syn-env-validate_agent-net \
  docker compose -f docker-compose.yaml -f docker-compose.ondemand.yaml config --services > /dev/null
echo "  ondemand: ok"

# The deployment identity a stack reports when APP_ENVIRONMENT is unset.
#
# This is not cosmetic. `deployment_identity()` turns APP_ENVIRONMENT into the
# `syntropic137__<tier>` stamped on every captured session, and
# infra/scripts/selfhost-env.sh derives the 1Password vault from the same
# value. A stack that falls through to the wrong default reports its sessions
# under the wrong tier and reads the wrong vault.
#
# It drifted once already: selfhost.yaml defaulted to `production` while
# selfhost.env.example and docker-compose.syntropic137.yaml both said
# `selfhost` - three files, two answers, and which one you got depended on the
# compose file you launched. Asserting the RESOLVED values is the only check
# that notices, since each file looks self-consistent on its own.
#
# HERMETIC and SEMANTIC, deliberately:
#   --env-file /dev/null  so a developer's local docker/.env cannot make a
#                         broken default appear to pass. Compose loads that
#                         file automatically otherwise.
#   --format json + jq    so each value is looked up by its exact path. A
#                         first-textual-match grep would silently start
#                         reading some other service the day one gains an
#                         APP_ENVIRONMENT of its own.
#   no 2>/dev/null        so a Compose failure is a loud failure rather than
#                         an empty string that fails with a confusing message.
#
# All four identities are asserted, not just the API variable: they have
# already disagreed with each other once.
echo "Checking default deployment identities..."

check_selfhost_defaults() {
    local expected_tier="selfhost"
    local resolved
    # COMPOSE_PROJECT_NAME too: it outranks the top-level `name:` key, so an
    # ambient one in the caller's shell would mask a broken default and make
    # the project assertion pass for the wrong reason.
    resolved=$(env -u APP_ENVIRONMENT -u COMPOSE_PROJECT_NAME docker compose --env-file /dev/null \
        -f docker-compose.yaml -f docker-compose.selfhost.yaml config --format json)

    local project api_env api_net net_name
    project=$(printf '%s' "$resolved" | jq -r '.name')
    api_env=$(printf '%s' "$resolved" | jq -r '.services.api.environment.APP_ENVIRONMENT')
    api_net=$(printf '%s' "$resolved" | jq -r '.services.api.environment.SYN_AGENT_NETWORK')
    net_name=$(printf '%s' "$resolved" | jq -r '.networks["agent-net"].name')

    local failed=0
    _expect() {
        if [ "$2" != "$3" ]; then
            echo "  FAIL selfhost $1: '$2', expected '$3'"
            failed=1
        fi
    }
    _expect "project name"    "$project"  "syntropic137_${expected_tier}"
    _expect "APP_ENVIRONMENT" "$api_env"  "$expected_tier"
    _expect "SYN_AGENT_NETWORK" "$api_net" "syntropic137_${expected_tier}_agent-net"
    _expect "agent-net name"  "$net_name" "syntropic137_${expected_tier}_agent-net"

    if [ "$failed" -ne 0 ]; then
        echo "       Sessions from this stack would be attributed to the wrong"
        echo "       tier, and selfhost-env.sh would derive the wrong vault."
        exit 1
    fi
    echo "  selfhost defaults are all ${expected_tier}: ok"
}

# Selfhost only. The dev overlay has a fixed project name and takes
# APP_ENVIRONMENT from the user-owned repo-root .env rather than a compose
# default, so there is no stable default there for this gate to enforce.
check_selfhost_defaults

echo "All compose overlays valid."
