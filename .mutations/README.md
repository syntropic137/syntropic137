# Mutation evidence for #1678

Tests: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_1678_a_slow_status_still_proves_the_work_safe.py`

| Patch | Bug re-introduced | Killed by (locally) |
|---|---|---|
| 01 | `git_status` runs under `LOCAL_TIMEOUT_SECONDS` again | `test_a_status_slower_than_the_old_bound...`, `test_modified_and_untracked...` |
| 02 | the guard's v1 status goes back to plain `git(...)` | same |
| 03 | `moved_gitlinks`' v2 status goes back to plain `git(...)` | `test_modified_and_untracked...` |
| 04 | the status bound becomes effectively unbounded | `test_the_status_bound_is_still_a_bound...[an-hour-keeps-the-directory]` |
