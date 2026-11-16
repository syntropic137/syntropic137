# Mutation patches: #1569 part 1 (failure streak)

| Patch | Bug re-introduced | Test meant to kill it |
|---|---|---|
| 01-failure-streak-no-reset.patch | WorkflowCompleted no longer resets the streak | packages/syn-domain/src/syn_domain/contexts/orchestration/slices/failure_streak/test_projection.py::TestFailureStreak::test_a_completion_resets_the_streak |
| 02-failure-streak-double-count.patch | A re-delivered WorkflowFailed counts twice | packages/syn-domain/src/syn_domain/contexts/orchestration/slices/failure_streak/test_projection.py::TestFailureStreak::test_the_same_failure_twice_counts_once |

Both need no Docker: `just mutation-evidence <pr> "<ids>" false`.
