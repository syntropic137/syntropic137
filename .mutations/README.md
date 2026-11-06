# Mutation evidence for #1677

| Patch | Killed by |
|---|---|
| `01-no-post-grant-withdrawal-check.patch` | `apps/syn-api/tests/test_1557_one_execution_budget.py::TestAQueuedResumeCanBeCancelled::test_a_withdrawal_after_the_grant_does_not_run_and_gives_the_slot_back` (and `test_cancel_withdraws_it_on_its_parent_and_it_never_runs`) |
| `02-resume-record-never-settles-withdrawn.patch` | `...::TestAQueuedResumeCanBeCancelled::test_after_a_restart_the_withdrawn_resume_is_never_offered` (and `test_cancel_withdraws_it_on_its_parent_and_it_never_runs`) |
