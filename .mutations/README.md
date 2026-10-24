# Mutation evidence for #1516

Run with `just mutation-evidence <PR> "apps/syn-api/tests/test_1516_a_degraded_start_reaches_the_api.py packages/syn-adapters/tests/workspace_backends/agentic/test_session_store_env.py" false`.

| Patch | Bug it re-introduces | Killed locally by |
|---|---|---|
| 01-drop-capability-at-record-hop | the verdict is read but not passed to the recorder | test_the_api_names_the_failed_check |
| 02-degraded-start-not-explained | a degraded start reads as the exporter's verdict | test_a_degraded_start_outranks_a_clean_looking_sweep |
| 03-route-drops-failed-checks | the route drops `failed_checks` | test_the_api_names_the_failed_check |
| 04-required-not-reserved | a caller can set AGENTIC_SESSION_STORE_REQUIRED | test_a_caller_cannot_force_the_hard_fail |
| 05-read-error-is-a-run-failure | a broken status exec escapes the reader | test_a_broken_status_read_still_records_the_capture |
