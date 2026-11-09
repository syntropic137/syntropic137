# Mutation evidence for #2200 (guard half)

Tests: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_2200_a_pytest_temp_root_is_not_work.py`
plus `apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py` for the shared rule.

| patch | bug it re-introduces | test meant to kill it |
|---|---|---|
| 01-guard-skips-the-split | the guard never consults the rule (current main) | `test_a_tree_only_pytest_wrote_is_left_and_named` |
| 02-any-child-is-pytests | the shape rule accepts any child | `test_a_file_pytest_would_not_write_there_keeps_the_tree` (and pc130's wrong-shape tests) |
| 03-every-untracked-line-dropped | a looser classifier: any untracked line is not work | `test_a_source_file_beside_it_is_still_work` |
| 04-dropped-silently | the tree is left out without an observation | `test_a_tree_only_pytest_wrote_is_left_and_named` |
