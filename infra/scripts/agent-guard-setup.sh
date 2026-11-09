#!/usr/bin/env bash
# =============================================================================
# dcg destructive-command guard for agent harnesses on this host
# =============================================================================
# Installs the dcg release pinned in infra/agent-guard/dcg-version.toml
# (SHA256 + minisign verified), root-owned, registers it in the root-owned
# settings layer of Claude Code, Codex and Gemini CLI, then validates it as the
# invoking (agent) account. The logic is infra/scripts/agent_guard.py (tested
# in infra/scripts/tests/test_agent_guard.py); this wrapper adds privilege.
#
# Opt-in per host: the first install is explicit (`just agent-guard-setup`).
# After that, `just selfhost-update` and `just selfhost-up` call this with
# --if-installed: a host with ANY piece of the guard installed is re-pinned
# and validated, and a failed validation FAILS the deploy (a damaged or
# half-removed guard is not mistaken for "never installed").
#
# Usage:
#   infra/scripts/agent-guard-setup.sh                 # install/refresh + validate
#   infra/scripts/agent-guard-setup.sh --check         # validate only, unprivileged
#   infra/scripts/agent-guard-setup.sh --if-installed  # as default, skip if never enrolled
#
# Never run `dcg update`: a new version is a reviewed bump of the version file.
# Overrides (tests only): SYN_AGENT_GUARD_SUDO, SYN_AGENT_GUARD_ROOT.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/infra/scripts/agent_guard.py"
ROOT="${SYN_AGENT_GUARD_ROOT:-}"
if [[ -n "${SYN_AGENT_GUARD_SUDO+set}" ]]; then
    SUDO="$SYN_AGENT_GUARD_SUDO"
elif [[ "$(id -u)" == 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

enrolled() {
    [[ -e "${ROOT}/etc/dcg" || -e "${ROOT}/usr/local/bin/dcg" || -e "${ROOT}/etc/codex/requirements.toml" ]]
}

validate() {
    if [[ "$(id -u)" == 0 && -z "$ROOT" ]]; then
        echo "  ❌ agent guard: validate runs as the agent account; re-run this as that user" >&2
        return 1
    fi
    python3 -I "$GUARD" validate --user "$(id -un)"
}

mode="${1:-}"
case "$mode" in
    --check) validate; exit $? ;;
    --if-installed)
        if ! enrolled; then
            echo "  dcg agent guard: not installed on this host (opt in: just agent-guard-setup)"
            exit 0
        fi
        ;;
    "") ;;
    *) echo "usage: $0 [--check|--if-installed]" >&2; exit 2 ;;
esac

# The installer, pin and key come from this checkout: refuse local edits to them.
if [[ -z "$ROOT" ]] && [[ -n "$(git -C "$REPO_ROOT" status --porcelain -- infra/agent-guard infra/scripts/agent_guard.py infra/scripts/agent-guard-setup.sh)" ]]; then
    echo "  ❌ agent guard: uncommitted changes to the guard files in $REPO_ROOT; install only from a reviewed commit" >&2
    exit 1
fi

echo "  🛡  dcg agent guard: installing the pinned release (needs root)"
$SUDO python3 -I "$GUARD" ensure
validate
