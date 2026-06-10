#!/usr/bin/env bash
# S2 — concurrency: 3 simultaneous reply-ok-interactive executions.
#
# Hypothesis (frozen before run):
#   H2.a  All 3 phases complete. None of them sees a cross-execution
#         capture (i.e. no execution's response references another
#         execution's task string).
#   H2.b  Workspace isolation: each execution provisions its OWN
#         interactive-tmux container; the 3 containers coexist while
#         the executions are mid-flight, and all 3 are destroyed
#         (relative to baseline) after the test ends.
#   H2.c  Contention cost is sublinear: total wall time for the 3
#         concurrent runs is < 2× a single sequential run (we saw
#         ~20s/run in S1, so target < 40s wall total).
#   H2.d  Distinct session_ids and distinct workspace handles in the
#         API responses.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
source experiments/stress/scripts/common.sh

OUT="$RESULTS_DIR/s2-concurrency.json"
LOG="$LOGS_DIR/s2-transcript.txt"

echo "S2 start: $(now_iso)" | tee "$LOG"
baseline_ids=$(itmux_container_ids)
printf '%s' "$baseline_ids" > "$RESULTS_DIR/s2-baseline.txt"
echo "baseline_itmux_ids:" | tee -a "$LOG"
printf '%s\n' "$baseline_ids" | tee -a "$LOG"

t_start_ms=$(date +%s%3N)

# Submit 3 in quick succession (no inter-submit sleep).
for i in 1 2 3; do
    (
        body=$(execute_workflow reply-ok-interactive "S2 concurrent run $i — unique-tag-$i")
        printf '%s' "$body" > "$RESULTS_DIR/s2-submit-$i.json"
    ) &
done
wait

# Read back the submitted eids.
eids=()
for i in 1 2 3; do
    eid=$(python3 -c "import json,sys; print(json.load(open('$RESULTS_DIR/s2-submit-$i.json')).get('execution_id',''))")
    eids+=("$eid")
    echo "submit $i: eid=$eid" | tee -a "$LOG"
done

# Snapshot mid-flight container set (after ~6s, during provisioning peak).
sleep 6
mid_ids=$(itmux_container_ids)
printf '%s' "$mid_ids" > "$RESULTS_DIR/s2-mid-ids.txt"
new_mid=$(comm -23 <(printf '%s\n' "$mid_ids") <(printf '%s\n' "$baseline_ids") || true)
new_mid_count=$(printf '%s' "$new_mid" | grep -c . || true)
echo "mid-flight new containers (t+6s): $new_mid_count" | tee -a "$LOG"
printf '%s\n' "$new_mid" | tee -a "$LOG"

# Wait for all to finish.
for eid in "${eids[@]}"; do
    status=$(wait_for_terminal "$eid" 240)
    echo "  $eid -> $status" | tee -a "$LOG"
done

t_done_ms=$(date +%s%3N)
total_wall_ms=$((t_done_ms - t_start_ms))

sleep 2
post_ids=$(itmux_container_ids)
printf '%s' "$post_ids" > "$RESULTS_DIR/s2-post-ids.txt"
new_post=$(comm -23 <(printf '%s\n' "$post_ids") <(printf '%s\n' "$baseline_ids") || true)
new_post_count=$(printf '%s' "$new_post" | grep -c . || true)

# Gather details + check cross-talk by inspecting per-execution session_id.
detail_files=()
for eid in "${eids[@]}"; do
    detail=$(get_exec "$eid")
    printf '%s\n' "$detail" > "$RESULTS_DIR/s2-detail-$eid.json"
    detail_files+=("$RESULTS_DIR/s2-detail-$eid.json")
done

python3 - "$LOG" "$OUT" "$total_wall_ms" "$new_mid_count" "$new_post_count" "${detail_files[@]}" <<'PY'
import json, sys

log, out, wall_ms, mid_count, post_count, *paths = sys.argv[1:]
runs = []
session_ids = []
for p in paths:
    d = json.load(open(p))
    phase = (d.get("phases") or [{}])[0]
    session_ids.append(phase.get("session_id"))
    runs.append({
      "execution_id": d.get("workflow_execution_id"),
      "workflow_status": d.get("status"),
      "phase_status": phase.get("status"),
      "phase_duration_seconds": phase.get("duration_seconds"),
      "phase_session_id": phase.get("session_id"),
      "workflow_error": d.get("error_message"),
      "phase_started_at": phase.get("started_at"),
      "phase_completed_at": phase.get("completed_at"),
    })
distinct_sessions = len({s for s in session_ids if s})
out_obj = {
  "scenario": "S2-concurrency",
  "n_concurrent": len(runs),
  "total_wall_ms": int(wall_ms),
  "mid_flight_new_containers": int(mid_count),
  "post_flight_new_containers": int(post_count),
  "distinct_session_ids": distinct_sessions,
  "phase_completed_count": sum(1 for r in runs if r["phase_status"] == "completed"),
  "workflow_completed_count": sum(1 for r in runs if r["workflow_status"] == "completed"),
  "workflow_failed_count": sum(1 for r in runs if r["workflow_status"] == "failed"),
  "runs": runs,
}
json.dump(out_obj, open(out, "w"), indent=2)
print(json.dumps(out_obj, indent=2))
PY

echo "S2 done -> $OUT" | tee -a "$LOG"
