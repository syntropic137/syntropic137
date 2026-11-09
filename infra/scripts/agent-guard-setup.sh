#!/usr/bin/env bash
# =============================================================================
# dcg destructive-command guard for agent harnesses on this host
# =============================================================================
# Installs the dcg release pinned in infra/agent-guard/dcg-version.toml
# (SHA256 + minisign verified), root-owned, registers it in the root-owned
# settings layer of Claude Code, Codex and Gemini CLI, then validates it.
# The logic is infra/scripts/agent_guard.py (tested in
# infra/scripts/tests/test_agent_guard.py); this wrapper only adds sudo.
#
# Opt-in per host: the first install is explicit (`just agent-guard-setup`).
# After that, `just selfhost-update` and `just selfhost-up` call this with
# --if-installed, which keeps the guard at the pin and FAILS the deploy when
# validation fails. Hosts that never opted in are skipped.
#
# Usage:
#   infra/scripts/agent-guard-setup.sh                 # install/refresh + validate (sudo)
#   infra/scripts/agent-guard-setup.sh --check         # validate only, no sudo
#   infra/scripts/agent-guard-setup.sh --if-installed  # as default, skip if never installed
#
# Never run `dcg update`: a new version is a reviewed bump of the version file.
# Overrides (tests only): SYN_AGENT_GUARD_SUDO, SYN_AGENT_GUARD_ROOT.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/infra/scripts/agent_guard.py"
MARKER_FILE="${SYN_AGENT_GUARD_ROOT:-}/etc/dcg/config.toml"
if [[ -n "${SYN_AGENT_GUARD_SUDO+set}" ]]; then
    SUDO="$SYN_AGENT_GUARD_SUDO"
elif [[ "$(id -u)" == 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
fi
# The agent account(s) whose effective dcg policy is validated.
USER_ARGS=()
if [[ -n "${SUDO_USER:-}" ]]; then USER_ARGS=(--user "$SUDO_USER"); elif [[ "$(id -u)" != 0 ]]; then USER_ARGS=(--user "$(id -un)"); fi

mode="${1:-}"
case "$mode" in
    --check)
        exec python3 -I "$GUARD" validate "${USER_ARGS[@]}"
        ;;
    --if-installed)
        if ! grep -qF '# Managed by syntropic137 infra/scripts/agent_guard.py.' "$MARKER_FILE" 2>/dev/null; then
            echo "  dcg agent guard: not installed on this host (opt in: just agent-guard-setup)"
            exit 0
        fi
        ;;
    "") ;;
    *)
        echo "usage: $0 [--check|--if-installed]" >&2
        exit 2
        ;;
esac

echo "  🛡  dcg agent guard: installing the pinned release (needs sudo)"
$SUDO python3 -I "$GUARD" ensure
python3 -I "$GUARD" validate "${USER_ARGS[@]}"
