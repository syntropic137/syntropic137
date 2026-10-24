# Mutation evidence for #1516

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-response-hop-drops-display.patch` | `_map_phase_to_response` drops `capture_status_display` | `apps/syn-api/tests/test_api_executions.py::test_a_degraded_start_shows_capture_degraded_on_phase_and_execution` |
| `02-start-verdict-not-recorded.patch` | the service reads the start verdict but never records it | `packages/syn-adapters/tests/workspace_backends/agentic/test_session_capture_service.py::TestADegradedStartReadsAsDegraded::test_the_recorded_verdict_names_the_failed_checks`, and the API test above |
| `03-degraded-start-not-composed.patch` | a degraded start is recorded but the capture state stays an unexplained failed/disabled | `packages/syn-adapters/tests/workspace_backends/agentic/test_session_capture_service.py::TestADegradedStartReadsAsDegraded::test_the_recorded_verdict_names_the_failed_checks` |
