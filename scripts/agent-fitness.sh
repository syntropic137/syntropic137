#!/usr/bin/env bash
# The fitness half of `just preflight-agent` (#1498).
#
# Runs the SAME `just fitness-check` CI runs - same aps binary, same thresholds,
# same fitness-exceptions.toml - after making sure this workspace can build that
# binary. APSS publishes no binary assets, so `aps` has to be compiled here, and
# the workspace image ships rustup with no toolchain installed.
#
# Either fitness ran, and its exit code is ours. Or a line starting
# `FITNESS NOT RUN:` says why, and we exit non-zero: 69 (EX_UNAVAILABLE) when
# the binary cannot be had, the prerequisite's own code otherwise. A
# silent skip is how verify phases certified PRs that CI then failed on fitness
# (#1525, #1527, #1529). SYN_ALLOW_FITNESS_NOT_RUN=1 turns that 69 into 0; the
# line is printed either way, and it never skips a run that CAN happen. A
# prerequisite of fitness-check failing also prints the line, but keeps its
# exit code whatever the opt-out says, since it may be a ratchet violation.
#
# Caching is the existing stores', not a new one: the toolchain lives in
# RUSTUP_HOME and the binary in the APSS target dir. Cargo decides freshness,
# as build-aps.sh requires, so a warm run rebuilds nothing.
#
# `--build-only` stops after aps-build: the background prewarm `preflight-agent`
# starts so the Rust build overlaps its cheap steps (#1585). It checks nothing.
set -euo pipefail

readonly NOT_RUN_EXIT=69
build_only=0
[[ "${1:-}" == --build-only ]] && build_only=1

not_run() {
    echo "FITNESS NOT RUN: $1" >&2
    if [[ "${SYN_ALLOW_FITNESS_NOT_RUN:-}" == 1 ]]; then
        echo "  SYN_ALLOW_FITNESS_NOT_RUN=1 is set, so preflight-agent will not fail on this." >&2
        echo "  Nothing here has checked fitness; CI's Architectural Fitness job still will." >&2
        exit 0
    fi
    echo "  Nothing here has checked fitness; CI's Architectural Fitness job still will." >&2
    echo "  Fix the cause, or set SYN_ALLOW_FITNESS_NOT_RUN=1 to accept that explicitly." >&2
    exit "$NOT_RUN_EXIT"
}

if ! cargo --version >/dev/null 2>&1; then
    if ! command -v rustup >/dev/null 2>&1; then
        not_run "no working cargo and no rustup on PATH, so the aps binary cannot be built"
    fi
    # `stable`, because CI's dtolnay/rust-toolchain step asks for the stable
    # channel, not a numbered version. --no-self-update: rustup sits in a
    # read-only /usr/local/bin in the workspace image, and its update probe
    # fails the whole command even after the toolchain installed fine.
    echo "No usable Rust toolchain; installing stable (minimal profile) for aps-build..."
    if ! rustup toolchain install stable --profile minimal --no-self-update; then
        not_run "rustup could not install the stable Rust toolchain (its error is above)"
    fi
    if ! cargo --version >/dev/null 2>&1; then
        not_run "stable is installed but cargo still does not run; see 'rustup show'"
    fi
fi

if ! just aps-build; then
    not_run "aps-build failed, so there is no aps binary to check with (its error is above)"
fi
if [[ "$build_only" == 1 ]]; then
    exit 0
fi

# fitness-check has its own prerequisites (untyped-dicts and test-marker
# ratchets, topology-analyze) that run before the thresholds, so its exit code
# alone cannot say whether fitness ran. The recipe touches this marker right
# before `architecture-fitness validate`; no marker means it never got there.
marker_dir="$(mktemp -d)"
trap 'rm -rf "$marker_dir"' EXIT
export SYN_FITNESS_STARTED_FILE="$marker_dir/started"

status=0
just fitness-check || status=$?
if [[ "$status" != 0 && ! -e "$SYN_FITNESS_STARTED_FILE" ]]; then
    # Not via not_run: a failed ratchet is a real violation, and the opt-out
    # must never turn one green. Loud line, original exit code, either way.
    echo "FITNESS NOT RUN: a fitness-check prerequisite failed (exit $status) before the thresholds were checked (its error is above)" >&2
    echo "  This is a failure to fix, not to waive: SYN_ALLOW_FITNESS_NOT_RUN does not apply." >&2
fi
exit "$status"
