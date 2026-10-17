# Mutation evidence for PR 5c (resume inherits an open evidence gate)

Delete before merge. Each patch is one bug in a key guard; the listed node id
is the test meant to kill it.

| Patch | Guard | Killed by |
|---|---|---|
| 01-gate-does-not-inherit-the-gated-phase | `decide_resume` counts P as inherited under an open gate (the #1544 window) | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_resume_evidence_gate.py::TestTheParentAdmitsAGateResume::test_the_resume_point_is_the_held_phase_and_needs_no_acknowledgement` |
| 02-resume-event-drops-the-gate | `ExecutionResumed` carries the open gate | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_resume_evidence_gate.py::TestTheParentAdmitsAGateResume::test_the_resume_point_is_the_held_phase_and_needs_no_acknowledgement` |
| 03-child-start-drops-the-gate | the child's start carries the gate in `resumed_from` | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_resume_evidence_gate.py::TestTheChildTakesTheGateOver::test_the_child_start_carries_the_gate` |
| 04-child-does-not-seed-its-gate | `_inherit` seeds the child's gate record | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_resume_evidence_gate.py::TestTheChildTakesTheGateOver::test_the_childs_last_settle_releases_the_held_phase` |
| 05-reports-not-owned-by-the-gated-phase | settled report and manifest ids join P's artifact ids | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_resume_evidence_gate.py::TestTheParentAdmitsAGateResume::test_the_gated_phase_carries_its_settled_reports` |
| 06-first-todo-is-a-provision | the child's first to-do is `RUN_EVIDENCE_STEP` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execution_todo/test_execution_todo_resume_gate.py::test_the_first_todo_is_the_first_unsettled_step_then_the_held_phase` |
| 07-handler-ignores-the-parents-attempt | the handler takes over the parent's attempt before posting | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_evidence_step_handler_resume.py::test_a_dispatch_the_parent_never_saw_adopted_is_found_by_its_nonce` |
| 08-inherited-run-not-adopted | an inherited run id is adopted directly | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_evidence_step_handler_resume.py::test_the_parents_adopted_run_settles_the_step_with_no_dispatch` |

Node ids for `mutation-evidence.yml` (space separated):

```
packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_resume_evidence_gate.py packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execution_todo/test_execution_todo_resume_gate.py packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_evidence_step_handler_resume.py
```
