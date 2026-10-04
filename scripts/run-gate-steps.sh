#!/usr/bin/env bash
# Runs `just` recipes in the order given, stops at the FIRST failure, and
# prints one timing line per step plus a total (#1585).
#
#   bash scripts/run-gate-steps.sh <label> <recipe>...
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
for step in "$@"; do
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
