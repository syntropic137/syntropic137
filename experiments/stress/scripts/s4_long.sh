#!/usr/bin/env bash
# S4 — longer conversation: prompt that elicits a multi-paragraph reply.
#
# Hypothesis (frozen before run):
#   H4.a  Phase completes (Claude does answer).
#   H4.b  Capture completeness: the captured pane text contains the
#         sentinel literal `[END-OF-LONG-REPLY-SENTINEL]` that the prompt
#         requires the model to emit at the end of the response. If the
#         sentinel is missing, late content was truncated by the tmux
#         scrollback (driver uses default 200x50 pane = ~10k chars
#         visible, and `capture-pane -p` does not include scrollback).
#   H4.c  Captured response is not silently truncated mid-word.
#
# Test approach: we cannot read the captured pane directly through the
# HTTP surface (the workflow returns no artifacts on this path; the
# capture lives in syn-api logs as `pane_chars=N`). So we:
#   1. Submit the long workflow.
#   2. After the phase completes, scrape syn-api logs for the pane_chars
#      and (best-effort) the sentinel.
#   3. Also docker-exec into the workspace before destroy is impossible
#      (race); instead read syn-api logs as the canonical source.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
source experiments/stress/scripts/common.sh

LOG="$LOGS_DIR/s4-transcript.txt"
OUT="$RESULTS_DIR/s4-long.json"

baseline_ids=$(itmux_container_ids)
echo "S4 start: $(now_iso)" | tee "$LOG"

# Register the long workflow.
reg=$(register_yaml experiments/stress/workflows/reply-long.yaml)
echo "register: $reg" | tee -a "$LOG"

t_submit_ms=$(date +%s%3N)
submit=$(execute_workflow reply-long-interactive "S4 long-response probe")
eid=$(printf '%s' "$submit" | json_field execution_id)
echo "submit: $submit" | tee -a "$LOG"

# Start syn-api log capture in the background so we don't miss
# pane_chars when the phase completes.
log_capture="$LOGS_DIR/s4-syn-api.log"  # excluded from git via experiments/stress/.gitignore
docker logs --since 1s -f syn-api > "$log_capture" 2>&1 &
log_pid=$!

# Wait for the workspace container to come up so we can later try to
# capture the pane state ourselves before it disappears.
new_cid=""
for i in $(seq 1 200); do
    ids=$(itmux_container_ids)
    new=$(comm -23 <(printf '%s\n' "$ids") <(printf '%s\n' "$baseline_ids") || true)
    if [ -n "$new" ]; then new_cid=$(printf '%s\n' "$new" | head -n 1); break; fi
    sleep 0.2
done
echo "container: $new_cid" | tee -a "$LOG"

# Try to capture pane content periodically while the phase runs.
pane_dumps_dir="$LOGS_DIR/s4-pane-dumps"
mkdir -p "$pane_dumps_dir"
(
    if [ -n "$new_cid" ]; then
        ctr_name=$(docker inspect "$new_cid" --format '{{.Name}}' 2>/dev/null | sed 's,^/,,')
        for j in $(seq 1 60); do
            docker exec "$ctr_name" tmux capture-pane -p -t 'agents:claude' -S -10000 > "$pane_dumps_dir/dump-$j.txt" 2>/dev/null || true
            sleep 1
        done
    fi
) &
dump_pid=$!

status=$(wait_for_terminal "$eid" 360)
t_done_ms=$(date +%s%3N)
elapsed_ms=$((t_done_ms - t_submit_ms))
echo "  status=$status wall_ms=$elapsed_ms" | tee -a "$LOG"

kill "$dump_pid" 2>/dev/null || true
sleep 2
kill "$log_pid" 2>/dev/null || true

detail=$(get_exec "$eid")
printf '%s\n' "$detail" > "$RESULTS_DIR/s4-detail.json"

# Extract pane_chars from syn-api logs.
pane_chars=$(grep -oE 'pane_chars=[0-9]+' "$log_capture" | head -n 1 | grep -oE '[0-9]+' || true)
finished_line=$(grep -E 'interactive-tmux phase finished' "$log_capture" | tail -n 1 || true)

# Best pane dump (largest) to estimate sentinel presence.
best_dump=""
best_size=0
for d in "$pane_dumps_dir"/dump-*.txt; do
    [ -f "$d" ] || continue
    sz=$(wc -c < "$d")
    if (( sz > best_size )); then
        best_size=$sz
        best_dump=$d
    fi
done
sentinel_present="false"
if [ -n "$best_dump" ] && grep -q "END-OF-LONG-REPLY-SENTINEL" "$best_dump"; then
    sentinel_present="true"
fi

# Also check the last dump (closest to phase end).
last_dump=$(ls -1 "$pane_dumps_dir" 2>/dev/null | sort -V | tail -n 1)
last_sentinel="false"
last_size=0
if [ -n "$last_dump" ]; then
    last_size=$(wc -c < "$pane_dumps_dir/$last_dump")
    if grep -q "END-OF-LONG-REPLY-SENTINEL" "$pane_dumps_dir/$last_dump"; then
        last_sentinel="true"
    fi
fi

python3 - "$OUT" "$eid" "$status" "$elapsed_ms" "$pane_chars" "$sentinel_present" "$best_size" "$last_sentinel" "$last_size" "$finished_line" "$RESULTS_DIR/s4-detail.json" <<'PY'
import json, sys
(out, eid, status, ms, pane, sent, best_size, last_sent, last_size, finished_line, dpath) = sys.argv[1:]
d = json.load(open(dpath))
phase = (d.get("phases") or [{}])[0]
obj = {
  "scenario": "S4-long-conversation",
  "execution_id": eid,
  "workflow_status": status,
  "workflow_error": d.get("error_message"),
  "phase_status": phase.get("status"),
  "phase_duration_seconds": phase.get("duration_seconds"),
  "phase_model": phase.get("model"),
  "wall_ms": int(ms),
  "pane_chars_from_log": int(pane) if pane else None,
  "sentinel_in_largest_dump": sent == "true",
  "largest_dump_bytes": int(best_size),
  "sentinel_in_last_dump": last_sent == "true",
  "last_dump_bytes": int(last_size),
  "finished_log_line": finished_line,
}
json.dump(obj, open(out, "w"), indent=2)
print(json.dumps(obj, indent=2))
PY

echo "S4 done -> $OUT" | tee -a "$LOG"
