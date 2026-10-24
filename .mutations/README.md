# Mutation evidence for #2095 (session-store detector ignores pytest temp trees)

Every patch is a unified diff against the fixed code and is killed by tests in
`apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py`. Node ids for
`just mutation-evidence`:

    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_session_store_anywhere_inside_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_session_store_at_the_spool_root_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_session_store_inside_a_pytest_temp_tree_is_not_capture
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_pytest_temp_tree_does_not_hide_a_store_beside_it
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_pytest_fixture_store_alone_is_not_retained_as_capture

| patch | bug it re-introduces | killing test |
|---|---|---|
| 01-store-matched-inside-pytest-trees | the store check matches inside `pytest-of-*` trees again (the #2095 leak) | test_a_session_store_inside_a_pytest_temp_tree_is_not_capture, test_a_pytest_fixture_store_alone_is_not_retained_as_capture |
| 02-pytest-trees-pruned-from-the-walk | pytest trees are pruned from the walk, so their bytes go unmeasured | test_a_session_store_inside_a_pytest_temp_tree_is_not_capture |
| 03-exclusion-widened-to-the-whole-tmpdir | the exclusion covers all of `.tmp`, hiding a store beside the pytest tree (fails open) | test_a_pytest_temp_tree_does_not_hide_a_store_beside_it |
| 04-store-only-at-the-top-of-the-dir | the store is looked for only at `<dir>/.agentic-session-store`, missing a spool under a subdirectory (fails open) | test_a_session_store_anywhere_inside_keeps_the_dir, test_a_pytest_temp_tree_does_not_hide_a_store_beside_it |
| 05-session-store-never-retains | `_judge_on_disk` ignores the store, so a real one no longer keeps the dir | test_a_session_store_anywhere_inside_keeps_the_dir, test_a_session_store_at_the_spool_root_keeps_the_dir |

Each was applied and run locally; each failed the named tests, and the tree
reverted clean. The trusted run is `mutation-evidence.yml`, not this note.
