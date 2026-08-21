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
# compose file you launched. Asserting the RESOLVED value is the only check
# that notices, since each file looks self-consistent on its own.
echo "Checking default deployment identities..."

check_default_environment() {
    local label="$1" expected="$2"
    shift 2
    local resolved
    # `|| true` on the pipeline: under `set -o pipefail` a grep that matches
    # nothing would abort the script before the diagnostic below ever printed,
    # turning a clear failure into a bare non-zero exit.
    resolved=$(env -u APP_ENVIRONMENT docker compose "$@" config 2>/dev/null \
        | grep -m1 -E '^[[:space:]]+APP_ENVIRONMENT:' | awk '{print $2}' || true)
    if [ "$resolved" != "$expected" ]; then
        echo "  FAIL $label: APP_ENVIRONMENT defaults to '$resolved', expected '$expected'"
        echo "       Sessions from this stack would be attributed to the wrong tier."
        exit 1
    fi
    echo "  $label defaults to $resolved: ok"
}

# Selfhost only. The dev stack takes APP_ENVIRONMENT from the repo-root .env
# rather than from a compose default, so asserting it here would be checking a
# file this script does not own - and would fail in any worktree without one.
check_default_environment selfhost selfhost \
    -f docker-compose.yaml -f docker-compose.selfhost.yaml

echo "All compose overlays valid."
