# Mutation evidence for #2095 (pytest temp trees no longer pin a workspace dir)

Every patch is a unified diff against the fixed code and is killed by tests in
`apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py`. Node ids for
`just mutation-evidence`:

    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_session_store_anywhere_inside_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_session_store_at_the_spool_root_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_session_store_inside_a_pytest_temp_tree_is_not_capture
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_pytest_temp_tree_does_not_hide_a_store_beside_it
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_dir_whose_only_extra_is_a_pytest_temp_tree_is_reclaimed
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_unversioned_work_beside_a_pytest_temp_tree_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_pytest_shaped_tree_outside_the_workspace_tmpdir_is_kept
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_spool_under_a_misplaced_pytest_tree_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_store_in_a_tmpdir_tree_pytest_did_not_shape_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_work_in_a_tmpdir_tree_pytest_did_not_shape_keeps_the_dir
    apps/syn-api/tests/test_pc130_workspace_dir_reclaim.py::test_a_workspace_dir_that_is_a_repository_has_no_pytest_temp_tree

| patch | bug it re-introduces | killing test (one of several) |
|---|---|---|
| 01-store-matched-inside-pytest-trees | the store check matches inside the pytest temp tree again (the #2095 leak) | test_a_session_store_inside_a_pytest_temp_tree_is_not_capture, test_a_dir_whose_only_extra_is_a_pytest_temp_tree_is_reclaimed |
| 02-pytest-trees-pruned-from-the-walk | `pytest-of-*` dirs are pruned from the sizing walk: bytes go unmeasured and stores in them unseen | test_a_session_store_inside_a_pytest_temp_tree_is_not_capture, test_a_spool_under_a_misplaced_pytest_tree_keeps_the_dir |
| 03-exclusion-widened-to-the-whole-tmpdir | the store exclusion covers all of `.tmp`, hiding a store beside the pytest tree (fails open) | test_a_pytest_temp_tree_does_not_hide_a_store_beside_it, test_a_store_in_a_tmpdir_tree_pytest_did_not_shape_keeps_the_dir |
| 04-store-only-at-the-top-of-the-dir | the store is looked for only at `<dir>/.agentic-session-store`, missing a spool under a subdirectory (fails open) | test_a_session_store_anywhere_inside_keeps_the_dir, test_a_spool_under_a_misplaced_pytest_tree_keeps_the_dir |
| 05-session-store-never-retains | `_judge_on_disk` ignores the store, so a real one no longer keeps the dir | test_a_session_store_anywhere_inside_keeps_the_dir, test_a_session_store_at_the_spool_root_keeps_the_dir |
| 06-pytest-temp-tree-not-disposable | the unversioned walk no longer skips the recognised pytest tree, so the dir stays leaked | test_a_dir_whose_only_extra_is_a_pytest_temp_tree_is_reclaimed |
| 07-not-anchored-to-the-workspace-tmpdir | the tree is looked for at the top of the dir, not in its TMPDIR `.tmp` (Codex r1 P1: `ws/pytest-of-x/...` deleted, a spool there hidden) | test_a_pytest_shaped_tree_outside_the_workspace_tmpdir_is_kept, test_a_spool_under_a_misplaced_pytest_tree_keeps_the_dir |
| 08-pytest-shape-not-checked | any `.tmp/pytest-of-*` counts, whatever it holds (name-only provenance) | test_a_store_in_a_tmpdir_tree_pytest_did_not_shape_keeps_the_dir, test_work_in_a_tmpdir_tree_pytest_did_not_shape_keeps_the_dir |
| 09-repository-workspace-not-excluded | a workspace dir that is itself a repository still gets a pytest exemption for its `.tmp` | test_a_workspace_dir_that_is_a_repository_has_no_pytest_temp_tree |

Each was applied and run locally against the 11 tests above; each failed its
named tests, and the tree reverted clean. The trusted run is
`mutation-evidence.yml`, not this note.
