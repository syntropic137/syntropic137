# Mutation evidence for #2112

Each patch disables one guard in `scripts/workflows/check_release_source.py`.
All of them are run against `scripts/workflows/test_check_release_source.py`
(no Docker needed). Every patch was killed locally first: 1-2 tests failed per patch.

| Patch | Guard removed | Killed by |
|---|---|---|
| 01 | cherry-pick patch-id must equal the main commit's | `test_a_cherry_pick_edited_after_the_fact_is_refused` |
| 02 | cherry-pick source must be on origin/main | `test_a_cherry_pick_of_a_commit_not_on_main_is_refused` |
| 03 | release must carry no commit main lacks (forward merge) | `test_main_is_refused_until_a_released_hotfix_is_forward_merged` |
| 04 | changed files limited to the bump files | `test_an_evil_merge_that_adds_a_file_is_refused` |
| 05 | bumped files stay 100644, modified in place | `test_a_bumped_file_made_executable_is_refused` |
| 06 | a bump rewrites lines, never adds or removes them | lifecycle-script and extra-dependency tests |
| 07 | a changed line must be a version field | one test in the line/structure group |
| 08 | the parsed document may differ only at its version key | `test_a_version_rewritten_outside_its_field_is_refused` |
| 09 | the head must be in the base repository | `test_a_fork_branch_named_main_is_refused` |
| 10 | a main head's SHA must be on origin/main | `test_a_main_head_that_is_not_on_main_is_refused` |
