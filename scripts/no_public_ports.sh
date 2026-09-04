#!/usr/bin/env bash
# Thin entry point. The gate itself, and the incident that motivates it, are
# documented at the top of scripts/no_public_ports.py; deciding what a mapping
# MEANS needs a YAML parser, so the logic lives there and this only keeps the
# `bash scripts/no_public_ports.sh` contract that `just check-no-public-ports`
# and the git hooks already call. Exit 0 clean, exit 1 on any finding.
set -euo pipefail

cd "$(dirname "$0")/.."
exec uv run python scripts/no_public_ports.py "$@"
