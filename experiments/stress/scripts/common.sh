#!/usr/bin/env bash
# Shared helpers for the interactive-tmux stress campaign.
#
# These wrap the syn-api HTTP surface and a couple of docker observations
# needed to detect workspace cleanup leaks. Nothing here mutates source
# under apps/ or packages/ — the scenarios only touch experiments/stress/.

set -uo pipefail

API="${SYN_API:-http://localhost:9137}"
RESULTS_DIR="${RESULTS_DIR:-experiments/stress/results}"
LOGS_DIR="${LOGS_DIR:-experiments/stress/evidence}"

mkdir -p "$RESULTS_DIR" "$LOGS_DIR"

now_iso() {
    date -u +'%Y-%m-%dT%H:%M:%S.%3NZ'
}

# Snapshot every running interactive-tmux container ID.
itmux_containers() {
    docker ps --filter "name=interactive-tmux" --format '{{.ID}} {{.Names}} {{.CreatedAt}}'
}

# Snapshot just the IDs (sorted) for diff-friendly comparison.
itmux_container_ids() {
    docker ps --filter "name=interactive-tmux" --format '{{.ID}}' | sort
}

# Register reply-ok-interactive (or any YAML) — idempotent: skip on 409/400.
register_yaml() {
    local file="$1"
    curl -sS -X POST "$API/workflows/from-yaml" \
        -H 'Content-Type: application/x-yaml' \
        --data-binary @"$file"
}

# Start an execution against a workflow id. Returns the JSON body.
execute_workflow() {
    local wid="$1"
    local task="${2:-Reply OK}"
    curl -sS -X POST "$API/workflows/$wid/execute" \
        -H 'Content-Type: application/json' \
        -d "{\"task\":\"$task\"}"
}

# Fetch execution summary by id (the /executions/{id} endpoint).
get_exec() {
    local eid="$1"
    curl -sS "$API/executions/$eid"
}

# Cancel an execution.
cancel_exec() {
    local eid="$1"
    local reason="${2:-stress-test}"
    curl -sS -X POST "$API/executions/$eid/cancel" \
        -H 'Content-Type: application/json' \
        -d "{\"reason\":\"$reason\"}"
}

# Block until an execution status is terminal (completed/failed/cancelled)
# OR the deadline is reached. Echoes the final status, returns 0 if terminal
# was reached, 1 on timeout.
wait_for_terminal() {
    local eid="$1"
    local timeout_s="${2:-180}"
    local start
    start=$(date +%s)
    local status="unknown"
    while :; do
        local body
        body=$(get_exec "$eid")
        status=$(printf '%s' "$body" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("status",""))' 2>/dev/null || echo unknown)
        case "$status" in
            completed|failed|cancelled) echo "$status"; return 0 ;;
        esac
        local now
        now=$(date +%s)
        if (( now - start >= timeout_s )); then
            echo "$status"
            return 1
        fi
        sleep 0.5
    done
}

# Extract a JSON field from a body via python.
json_field() {
    local field="$1"
    python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$field',''))"
}
