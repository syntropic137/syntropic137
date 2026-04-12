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

echo "All compose overlays valid."
