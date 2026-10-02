#!/usr/bin/env bash
# =============================================================================
# Host-side upgrade steps for `just selfhost-update` (#1398)
# =============================================================================
# Runs AFTER the code and submodules are updated and BEFORE compose restarts
# anything, so the new containers start against a host that matches them:
#
#   1. AppArmor: install/reload the Codex sandbox profile shipped by the new
#      agentic-workspace pin (skips hosts without AppArmor). A profile updated
#      by the pull but not reloaded would leave the kernel enforcing the old
#      rules; a missing one refuses every Codex workspace.
#   2. Workspace image + signer: move a copied, previously shipped default
#      SYN_WORKSPACE_DOCKER_IMAGE and SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP
#      in .env to the new defaults. A value in .env overrides the code default,
#      so without this the upgrade keeps running the old image, or verifies the
#      new image against the old publisher's identity and refuses it. Custom
#      values are never changed; every outcome is printed.
#
# Usage: infra/scripts/selfhost-update-host.sh [ENV_FILE]   (default: .env)
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/.env}"

echo "  AppArmor (Codex sandbox profile):"
if ! bash "${REPO_ROOT}/infra/scripts/apparmor-setup.sh"; then
    echo "  ❌ Update stopped before restarting services: fix the AppArmor step above," >&2
    echo "     then re-run 'just selfhost-update'." >&2
    exit 1
fi

echo "  Workspace image pin and signer identity:"
( cd "$REPO_ROOT" && uv run python -m syn_shared.settings.workspace_image_migration "$ENV_FILE" )
