# Mutation evidence for #2321 Path B (PR #2374)

Each patch re-introduces one bug in `apps/syn-api/src/syn_api/services/workspace_dir_reclaim.py`.
The test that should kill it:

| Patch | Bug | Killed by |
|---|---|---|
| `01-hook-not-called.patch` | the clock never calls `on_pass` | `apps/syn-api/tests/test_2321_reclaimer_keeps_recorded.py::test_a_dirty_dir_kept_on_every_pass_is_one_event_on_its_execution` |
| `02-execution-id-dropped.patch` | `_PassTally.add` drops the owner's execution id from `RetainedDir` | `apps/syn-api/tests/test_2321_reclaimer_keeps_recorded.py::test_a_dirty_dir_kept_on_every_pass_is_one_event_on_its_execution` |
| `03-observer-failure-propagates.patch` | an observer failure escapes and stops the clock | `apps/syn-api/tests/test_2321_reclaimer_keeps_recorded.py::test_an_observer_that_raises_leaves_the_clock_running_and_the_dir_kept` |
| `04-post-claim-owner-dropped.patch` | a keep made under the claim (re-look failed) loses the owner resolved before it | `apps/syn-api/tests/test_2321_reclaimer_keeps_recorded.py::test_a_keep_made_under_the_claim_names_the_owner_resolved_before_it` |

Run: `just mutation-evidence 2374 "apps/syn-api/tests/test_2321_reclaimer_keeps_recorded.py" false` (no Docker needed).
