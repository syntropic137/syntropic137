#!/usr/bin/env bash
# S3 — lifecycle resilience. Two sub-scenarios:
#
#   S3a: kill the workspace container mid-execution. Expect:
#        - execution terminates (no indefinite hang)
#        - status -> failed with a typed/explanatory error (not silent)
#        - no orphan container after a generous grace period
#
#   S3b: Cancel an in-flight interactive execution via the control plane.
#        - POST /executions/{eid}/cancel returns 2xx
#        - execution reaches a terminal state (cancelled/failed) within
#          a bounded grace period
#        - workspace container is destroyed
#
# Hypothesis (frozen before run):
#   H3.a  Killing the workspace surfaces as a typed failure (the agent
#         execution path raises and the execution is marked failed).
#         No process hangs >60s past the kill.
#   H3.b  Control-plane cancel works on an interactive execution; the
#         engine routes the cancel through the existing CancelExecution
#         path and tears the workspace down.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
source experiments/stress/scripts/common.sh

LOG="$LOGS_DIR/s3-transcript.txt"
OUT="$RESULTS_DIR/s3-resilience.json"

baseline_ids=$(itmux_container_ids)
printf '%s' "$baseline_ids" > "$RESULTS_DIR/s3-baseline.txt"
echo "S3 start: $(now_iso)" | tee "$LOG"
printf 'baseline_itmux_ids:\n%s\n' "$baseline_ids" | tee -a "$LOG"

# Helper: wait until a NEW itmux container (not in baseline_ids) appears.
wait_new_container() {
    local timeout="${1:-20}"
    local start
    start=$(date +%s)
    while :; do
        local now ids new
        ids=$(itmux_container_ids)
        new=$(comm -23 <(printf '%s\n' "$ids") <(printf '%s\n' "$baseline_ids") || true)
        if [ -n "$new" ]; then
            printf '%s\n' "$new" | head -n 1
            return 0
        fi
        now=$(date +%s)
        if (( now - start >= timeout )); then
            return 1
        fi
        sleep 0.2
    done
}

# ----------------------------- S3a: kill -----------------------------
echo "--- S3a kill @ $(now_iso) ---" | tee -a "$LOG"
t_submit_ms=$(date +%s%3N)
submit_a=$(execute_workflow reply-ok-interactive "S3a kill probe")
eid_a=$(printf '%s' "$submit_a" | json_field execution_id)
echo "submit: $submit_a" | tee -a "$LOG"

new_cid=$(wait_new_container 25 || true)
if [ -z "$new_cid" ]; then
    echo "S3a: no new container appeared within 25s — FAIL (provisioning issue?)" | tee -a "$LOG"
    s3a_kill_target=""
else
    s3a_kill_target="$new_cid"
    echo "S3a: killing container $new_cid" | tee -a "$LOG"
    docker kill "$new_cid" >>"$LOG" 2>&1 || true
fi

t_kill_ms=$(date +%s%3N)
status_a=$(wait_for_terminal "$eid_a" 120 || true)
t_terminal_ms=$(date +%s%3N)
kill_to_terminal_ms=$((t_terminal_ms - t_kill_ms))
detail_a=$(get_exec "$eid_a")
printf '%s\n' "$detail_a" > "$RESULTS_DIR/s3a-detail.json"
echo "  status_a=$status_a   kill→terminal=${kill_to_terminal_ms}ms" | tee -a "$LOG"

sleep 2
post_a_ids=$(itmux_container_ids)
new_post_a=$(comm -23 <(printf '%s\n' "$post_a_ids") <(printf '%s\n' "$baseline_ids") || true)
new_post_a_count=$(printf '%s' "$new_post_a" | grep -c . || true)
echo "  post-S3a new containers: $new_post_a_count" | tee -a "$LOG"
printf '%s\n' "$new_post_a" | tee -a "$LOG"

# ----------------------------- S3b: cancel ---------------------------
echo "--- S3b cancel @ $(now_iso) ---" | tee -a "$LOG"
# Re-snapshot baseline (in case S3a left an orphan).
baseline_b=$(itmux_container_ids)

submit_b=$(execute_workflow reply-ok-interactive "S3b cancel probe")
eid_b=$(printf '%s' "$submit_b" | json_field execution_id)
echo "submit: $submit_b" | tee -a "$LOG"

# Wait briefly for the agent execution to be in-flight before cancelling.
new_cid_b=""
start_b=$(date +%s)
while :; do
    ids=$(itmux_container_ids)
    new=$(comm -23 <(printf '%s\n' "$ids") <(printf '%s\n' "$baseline_b") || true)
    if [ -n "$new" ]; then
        new_cid_b=$(printf '%s\n' "$new" | head -n 1)
        break
    fi
    now=$(date +%s)
    if (( now - start_b >= 25 )); then break; fi
    sleep 0.2
done
echo "S3b: detected new container=$new_cid_b" | tee -a "$LOG"

# Sleep a moment so cancel lands during the agent's send/await loop, not before.
sleep 2
t_cancel_req_ms=$(date +%s%3N)
cancel_resp=$(cancel_exec "$eid_b" "S3b stress cancel")
echo "cancel resp: $cancel_resp" | tee -a "$LOG"

status_b=$(wait_for_terminal "$eid_b" 120 || true)
t_term_b_ms=$(date +%s%3N)
cancel_to_terminal_ms=$((t_term_b_ms - t_cancel_req_ms))
detail_b=$(get_exec "$eid_b")
printf '%s\n' "$detail_b" > "$RESULTS_DIR/s3b-detail.json"
echo "  status_b=$status_b   cancel→terminal=${cancel_to_terminal_ms}ms" | tee -a "$LOG"

sleep 2
post_b_ids=$(itmux_container_ids)
new_post_b=$(comm -23 <(printf '%s\n' "$post_b_ids") <(printf '%s\n' "$baseline_b") || true)
new_post_b_count=$(printf '%s' "$new_post_b" | grep -c . || true)
echo "  post-S3b new containers: $new_post_b_count" | tee -a "$LOG"
printf '%s\n' "$new_post_b" | tee -a "$LOG"

python3 - "$OUT" "$eid_a" "$status_a" "$kill_to_terminal_ms" "$new_post_a_count" "$s3a_kill_target" \
                 "$eid_b" "$status_b" "$cancel_to_terminal_ms" "$new_post_b_count" "$cancel_resp" \
                 "$RESULTS_DIR/s3a-detail.json" "$RESULTS_DIR/s3b-detail.json" <<'PY'
import json, sys
(out, eid_a, status_a, kill_ms, post_a, kill_cid,
 eid_b, status_b, cancel_ms, post_b, cancel_resp,
 detail_a_path, detail_b_path) = sys.argv[1:]
detail_a = json.load(open(detail_a_path))
detail_b = json.load(open(detail_b_path))
out_obj = {
  "scenario": "S3-resilience",
  "s3a_kill": {
    "execution_id": eid_a,
    "killed_container_id": kill_cid,
    "final_status": status_a,
    "kill_to_terminal_ms": int(kill_ms),
    "post_test_new_containers": int(post_a),
    "error_message": detail_a.get("error_message"),
    "phase_status": (detail_a.get("phases") or [{}])[0].get("status"),
    "phase_error": (detail_a.get("phases") or [{}])[0].get("error_message"),
  },
  "s3b_cancel": {
    "execution_id": eid_b,
    "cancel_response_raw": cancel_resp[:1000],
    "final_status": status_b,
    "cancel_to_terminal_ms": int(cancel_ms),
    "post_test_new_containers": int(post_b),
    "error_message": detail_b.get("error_message"),
    "phase_status": (detail_b.get("phases") or [{}])[0].get("status"),
    "phase_error": (detail_b.get("phases") or [{}])[0].get("error_message"),
  },
}
json.dump(out_obj, open(out, "w"), indent=2)
print(json.dumps(out_obj, indent=2))
PY

echo "S3 done -> $OUT" | tee -a "$LOG"
