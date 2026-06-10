#!/usr/bin/env bash
# S1 — sequential load: 5 back-to-back reply-ok-interactive executions.
#
# Hypothesis (frozen before run):
#   H1.a  All 5 phases complete (phase.status="completed") in <60s wall-time each.
#   H1.b  Per-run phase wall time is roughly constant (no monotonic creep:
#         e.g. last run within ±50% of first; no thermal/cumulative slowdown).
#   H1.c  Each run destroys its workspace container — no new interactive-tmux
#         container IDs persist after the run, relative to the pre-S1 baseline.
#   H1.d  Workflow-level status MAY be "failed" due to the known artifact-
#         pipeline KeyError ('reply') called out in the integration plan §9.
#         Phase completion + cleanup is the success criterion for S1.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
source experiments/stress/scripts/common.sh

OUT="$RESULTS_DIR/s1-sequential.json"
LOG="$LOGS_DIR/s1-transcript.txt"
RUNS_NDJSON="$RESULTS_DIR/s1-runs.ndjson"
: > "$RUNS_NDJSON"

echo "S1 start: $(now_iso)" | tee "$LOG"
baseline_ids=$(itmux_container_ids)
echo "baseline_itmux_ids:" | tee -a "$LOG"
printf '%s\n' "$baseline_ids" | tee -a "$LOG"
printf '%s' "$baseline_ids" > "$RESULTS_DIR/s1-baseline.txt"

for i in 1 2 3 4 5; do
    echo "--- run $i @ $(now_iso) ---" | tee -a "$LOG"

    t_submit_ms=$(date +%s%3N)
    submit_body=$(execute_workflow reply-ok-interactive "S1 sequential run $i")
    eid=$(printf '%s' "$submit_body" | json_field execution_id)
    echo "submit: $submit_body" | tee -a "$LOG"
    echo "eid=$eid" | tee -a "$LOG"

    final_status=$(wait_for_terminal "$eid" 180)
    t_done_ms=$(date +%s%3N)
    elapsed_ms=$((t_done_ms - t_submit_ms))

    detail=$(get_exec "$eid")
    printf '%s\n' "$detail" > "$RESULTS_DIR/s1-run-$i-detail.json"

    sleep 1
    current_ids=$(itmux_container_ids)
    printf '%s' "$current_ids" > "$RESULTS_DIR/s1-run-$i-post-ids.txt"
    new_leaks=$(comm -23 <(printf '%s\n' "$current_ids") <(printf '%s\n' "$baseline_ids") || true)
    leak_count=$(printf '%s' "$new_leaks" | grep -c . || true)

    python3 - "$i" "$eid" "$final_status" "$elapsed_ms" "$leak_count" "$detail" <<'PY' >> "$RUNS_NDJSON"
import json, sys
run, eid, ws, ms, leaks, detail_s = sys.argv[1:]
d = json.loads(detail_s)
phase = (d.get("phases") or [{}])[0]
print(json.dumps({
  "run": int(run),
  "execution_id": eid,
  "workflow_status": ws,
  "wall_ms": int(ms),
  "new_leak_count": int(leaks),
  "phase_status": phase.get("status"),
  "phase_duration_seconds": phase.get("duration_seconds"),
  "phase_model": phase.get("model"),
  "workflow_error": d.get("error_message"),
  "completed_phases": d.get("phases") and sum(1 for p in d["phases"] if p.get("status") == "completed"),
}))
PY
    tail -n 1 "$RUNS_NDJSON" | tee -a "$LOG"
done

python3 - "$RUNS_NDJSON" "$OUT" <<'PY'
import json, sys
runs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
durs = [r["phase_duration_seconds"] for r in runs if r.get("phase_duration_seconds")]
out = {
  "scenario": "S1-sequential",
  "n_runs": len(runs),
  "phase_completed_count": sum(1 for r in runs if r["phase_status"] == "completed"),
  "workflow_completed_count": sum(1 for r in runs if r["workflow_status"] == "completed"),
  "workflow_failed_count": sum(1 for r in runs if r["workflow_status"] == "failed"),
  "any_new_leaks": any(r["new_leak_count"] > 0 for r in runs),
  "phase_duration_min": min(durs) if durs else None,
  "phase_duration_max": max(durs) if durs else None,
  "phase_duration_avg": (sum(durs)/len(durs)) if durs else None,
  "runs": runs,
}
json.dump(out, open(sys.argv[2], "w"), indent=2)
print(json.dumps(out, indent=2))
PY

echo "S1 done -> $OUT" | tee -a "$LOG"
