# Mutation evidence for #975 item 1 (PR #2283)

All patches mutate `_session_duration_seconds` in `apps/syn-api/src/syn_api/routes/sessions.py`.
Tests: `apps/syn-api/tests/test_session_duration_survives_missing_enrichment.py` (no Docker needed: `docker=false`).

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| 01-no-lane1-fallback | terminal session without Lane 2 row reports None (the original #975 defect) | test_a_finished_session_with_no_lane2_row_takes_its_duration_from_lane1 |
| 02-drop-completed-guard | missing completed_at measures against the wall clock | test_without_both_timestamps_or_lane2_the_duration_is_unknown[no-completion] |
| 03-timestamps-before-lane2 | Lane 1 timestamps override a Lane 2 duration | test_lane2_duration_wins_when_it_has_one |
| 04-running-reads-lane2 | a running session reports a stale Lane 2 value | test_a_running_session_is_still_measured_against_the_wall_clock |
