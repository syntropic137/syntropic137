# Mutation evidence for PR 5b (evidence gate)

Each patch re-introduces one bug in production code. All six were applied
locally against the named tests and every one was killed (unit tests, no
Docker). The orchestrator runs `just mutation-evidence` for the recorded run.

| Patch | Guard | Killed by |
|---|---|---|
| 01-gate-ignores-the-flag | gate stays off unless enabled | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate.py::TestGateOpens::test_flag_off_never_opens_even_with_a_declaration` |
| 02-settle-twice-allowed | a step settles once, in order | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate_aggregate.py::TestAttemptProtocol::test_settling_twice_is_refused` |
| 03-predetermined-outcome-not-enforced | a predetermined step settles only as decided | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate_aggregate.py::TestAttemptProtocol::test_a_predetermined_step_settles_only_as_decided` |
| 04-removal-never-blocked | no patch removal unless mutation passed | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate.py::TestWhenAStepIsReached::test_removal_waits_for_every_mutation_step_on_its_head_to_pass`, `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate_aggregate.py::TestCleanupBeforeTheFinalPhase::test_a_failed_mutation_blocks_removal_and_the_required_check` |
| 05-dispatch-before-attempt-saved | the attempt is saved before the POST (B3) | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_evidence_step_handler.py::test_the_attempt_is_saved_before_the_dispatch_is_posted` |
| 06-append-replaces | `PhaseOutputCache.append` keeps the phase's own files | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_artifact_collector.py::TestAnEvidenceGateAppendsToItsPhase::test_reports_reach_the_next_workspace_beside_the_phase_output` |

Node ids for mutation-evidence.yml (space-separated):

```
packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_evidence_step_handler.py::test_the_attempt_is_saved_before_the_dispatch_is_posted packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate_aggregate.py::TestAttemptProtocol::test_settling_twice_is_refused packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate.py::TestGateOpens::test_flag_off_never_opens_even_with_a_declaration packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate.py::TestWhenAStepIsReached::test_removal_waits_for_every_mutation_step_on_its_head_to_pass packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate_aggregate.py::TestCleanupBeforeTheFinalPhase::test_a_failed_mutation_blocks_removal_and_the_required_check packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate_aggregate.py::TestAttemptProtocol::test_a_predetermined_step_settles_only_as_decided packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_artifact_collector.py::TestAnEvidenceGateAppendsToItsPhase::test_reports_reach_the_next_workspace_beside_the_phase_output 
```
