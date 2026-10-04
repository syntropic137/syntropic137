#!/usr/bin/env bash
# Runs `just` recipes in the order given, stops at the FIRST failure, and
# prints one timing line per step plus a total (#1585).
#
#   bash scripts/run-gate-steps.sh [--prewarm <recipe>:<step>] <label> <recipe>...
#
# --prewarm starts `just <recipe>` in the background when the gate starts and
# waits on its exit status (`wait`, never a poll) just before <step> runs. It
# exists for the APS Rust build: the cheap steps run while it compiles, so the
# LOC and complexity thresholds are reached minutes earlier on a cold
# workspace. A prewarm that fails stops nothing: <step> does the same work in
# the foreground and reports the error itself. If the gate stops before <step>,
# the prewarm is killed.
#
# Why a runner instead of recipe dependencies: `just` runs dependencies in
# order and stops on failure too, but says nothing about how long each took,
# and agents timed out on a gate whose slow first run nobody could attribute.
# The order is the caller's: cheap static checks first, so a file over the LOC
# limit fails in seconds instead of after a Rust build. This script decides
# nothing about WHICH checks run; the justfile's step lists do, and
# ci/fitness/code_quality/test_ci_and_preflight_agree.py pins them to CI's.
#
# The timing lines are repeated as a summary at the end, because each step's
# own output scrolls them away.
set -uo pipefail

prewarm=""
prewarm_for=""
if [[ "${1:-}" == --prewarm ]]; then
    prewarm="${2%%:*}"
    prewarm_for="${2#*:}"
    shift 2
fi
label="$1"
shift

now() { date +%s.%N; }
since() { awk -v s="$1" -v e="$(now)" 'BEGIN { printf "%.1fs", e - s }'; }

summary=()
report() {
    summary+=("$1")
    echo "$1"
}
print_summary() {
    echo
    printf '%s\n' "${summary[@]}"
}

gate_start="$(now)"
prewarm_pid=""
if [[ -n "$prewarm" ]]; then
    prewarm_log="$(mktemp)"
    prewarm_start="$(now)"
    just "$prewarm" > "$prewarm_log" 2>&1 &
    prewarm_pid=$!
    trap '[[ -n "$prewarm_pid" ]] && kill "$prewarm_pid" 2>/dev/null; rm -f "$prewarm_log"' EXIT
    echo "[$label] $prewarm started in the background for $prewarm_for"
fi

for step in "$@"; do
    if [[ -n "$prewarm_pid" && "$step" == "$prewarm_for" ]]; then
        prewarm_status=0
        wait "$prewarm_pid" || prewarm_status=$?
        prewarm_pid=""
        if [[ "$prewarm_status" == 0 ]]; then
            report "[$label] $prewarm (background) ok $(since "$prewarm_start")"
        else
            cat "$prewarm_log"
            report "[$label] $prewarm (background) FAILED (exit $prewarm_status) $(since "$prewarm_start"); $step retries it"
        fi
    fi
    step_start="$(now)"
    status=0
    just "$step" || status=$?
    if [[ "$status" != 0 ]]; then
        report "[$label] $step FAILED (exit $status) $(since "$step_start")"
        report "[$label] stopped at the first failure; total $(since "$gate_start")"
        print_summary
        exit "$status"
    fi
    report "[$label] $step ok $(since "$step_start")"
done
report "[$label] all $# steps ok; total $(since "$gate_start")"
print_summary
