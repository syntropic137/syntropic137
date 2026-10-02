#!/usr/bin/env bash
# =============================================================================
# Load the Codex sandbox AppArmor profile on the Docker host (#1398)
# =============================================================================
# Workspace images that declare Codex run under the AppArmor profile
# `agentic-codex-sandbox` (docker-default with `deny mount,` replaced by only
# the mounts bubblewrap performs). On a Docker host that enforces AppArmor
# (Ubuntu 24.04, most Debian/Ubuntu servers) agentic-workspace refuses to
# start such a workspace until that profile is loaded, and the API reports the
# typed provision failure `apparmor_profile_not_loaded`.
#
# This step installs the profile shipped with the pinned agentic-workspace
# under /etc/apparmor.d (so it loads at every boot) and loads it now with
# `apparmor_parser -r`. Hosts without AppArmor (macOS, Docker Desktop, hosts
# whose daemon reports no `name=apparmor`) are skipped.
#
# Usage:
#   infra/scripts/apparmor-setup.sh           # install + load if needed (sudo)
#   infra/scripts/apparmor-setup.sh --check   # exit 1 if needed but not loaded
#
# Idempotent: ensure always reloads (replace) the persisted file. Overrides (tests only): SYN_APPARMOR_PROFILE_SOURCE,
# SYN_APPARMOR_ETC_DIR, SYN_APPARMOR_POLICY_DIR, SYN_APPARMOR_SUDO, SYN_APPARMOR_OS.
# =============================================================================

set -euo pipefail

PROFILE_NAME="agentic-codex-sandbox"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="${SYN_APPARMOR_PROFILE_SOURCE:-${REPO_ROOT}/lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/apparmor/${PROFILE_NAME}}"
ETC_DIR="${SYN_APPARMOR_ETC_DIR:-/etc/apparmor.d}"
POLICY_DIR="${SYN_APPARMOR_POLICY_DIR:-/sys/kernel/security/apparmor/policy/profiles}"
if [[ -n "${SYN_APPARMOR_SUDO+set}" ]]; then
    SUDO="$SYN_APPARMOR_SUDO"
elif [[ "$(id -u)" == "0" ]]; then
    SUDO=""
else
    SUDO="sudo"
fi
TARGET="${ETC_DIR}/${PROFILE_NAME}"

MODE="ensure"
case "${1:-}" in
    "") ;;
    --check) MODE="check" ;;
    *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

info() { printf '  %s\n' "$*"; }

# The same signal agentic-workspace uses: the Docker DAEMON's security options.
# A failing `docker info` is an error, never "no AppArmor".
docker_uses_apparmor() {
    local options
    if ! options="$(docker info --format '{{json .SecurityOptions}}' 2>/dev/null)"; then
        echo "  ❌ docker info failed; cannot tell whether the Docker host enforces AppArmor" >&2
        exit 1
    fi
    [[ "$options" == *"name=apparmor"* ]]
}

profile_loaded() {
    local entry
    for entry in "$POLICY_DIR"/*/name; do
        [[ -r "$entry" ]] || continue
        if [[ "$(cat "$entry")" == "$PROFILE_NAME" ]]; then
            return 0
        fi
    done
    return 1
}

persisted_current() {
    [[ -f "$TARGET" ]] && cmp -s "$SOURCE" "$TARGET"
}

if [[ "${SYN_APPARMOR_OS:-$(uname -s)}" != "Linux" ]] || ! docker_uses_apparmor; then
    info "✅ AppArmor: Docker host does not enforce AppArmor; no profile needed"
    exit 0
fi

if [[ ! -f "$SOURCE" ]]; then
    echo "  ❌ AppArmor: shipped profile not found at $SOURCE (run 'just submodules-init')" >&2
    exit 1
fi

if [[ "$MODE" == "check" ]]; then
    if ! profile_loaded || ! persisted_current; then
        echo "  ❌ AppArmor: the Docker host enforces AppArmor but $PROFILE_NAME is not" >&2
        echo "     loaded and persisted. Codex workspaces will be refused. Run:" >&2
        echo "       just apparmor-setup" >&2
        exit 1
    fi
    # The kernel exposes only a hash of the compiled policy, not of this
    # source, so a loaded name does not prove the loaded rules match the file
    # (someone may have edited or replaced it since the last load).
    info "✅ AppArmor: $PROFILE_NAME loaded and $TARGET matches the shipped profile"
    info "⚠️  cannot verify the LOADED rules match that file; 'just apparmor-setup' reloads it"
    exit 0
fi

if ! command -v apparmor_parser >/dev/null 2>&1; then
    echo "  ❌ AppArmor: apparmor_parser not found (install the 'apparmor' package)" >&2
    exit 1
fi

# Always reload, even when the name is already loaded and the file matches:
# the loaded rules cannot be compared to the file, and `apparmor_parser -r`
# (replace) is idempotent. Skipping it would leave a replaced profile stale.
needs_root() {
    echo "  ❌ AppArmor: '$*' failed. Loading a profile needs root on the Docker host." >&2
    echo "     Re-run interactively (sudo prompts): just apparmor-setup" >&2
    echo "     or as root: sudo bash infra/scripts/apparmor-setup.sh" >&2
    exit 1
}

if ! persisted_current; then
    info "🔐 AppArmor: installing $PROFILE_NAME to $TARGET (needs sudo)"
    $SUDO mkdir -p "$ETC_DIR" || needs_root mkdir -p "$ETC_DIR"
    $SUDO install -m 0644 "$SOURCE" "$TARGET" || needs_root install "$TARGET"
fi
info "🔐 AppArmor: loading $TARGET with apparmor_parser -r (needs sudo)"
$SUDO apparmor_parser -r "$TARGET" || needs_root apparmor_parser -r "$TARGET"

if ! profile_loaded; then
    echo "  ❌ AppArmor: apparmor_parser succeeded but $PROFILE_NAME is not listed in $POLICY_DIR" >&2
    exit 1
fi
info "✅ AppArmor: $PROFILE_NAME loaded now and at every boot"
