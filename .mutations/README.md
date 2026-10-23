# Mutation evidence for #1812

Each patch puts one defect back into `packages/syn-adapters/src/syn_adapters/workspace_backends/dependency_seed.py`. Each was applied locally and the named tests failed. That run was in an agent workspace, so it is not the trusted evidence `mutation-evidence.yml` produces.

All tests are in `packages/syn-adapters/src/syn_adapters/workspace_backends/test_1714_dependency_seed.py`.

| Patch | Defect | Killing test(s) |
|---|---|---|
| `01-size-written-before-the-publish-decision.patch` | (a) `.size` is written before the rename decides the winner, so a losing publisher overwrites the winner's size | `::test_a_losing_publisher_leaves_the_winners_size` |
| `02-identical-symlink-re-raises.patch` | (b) merging over an existing identical symlink raises `FileExistsError`, and the copy then wipes the uv cache | `::test_an_identical_existing_symlink_merges_cleanly`, `::test_two_repositories_sharing_uv_wheels_keep_both_seeds_whole`, `::test_two_seeds_sharing_a_symlink_both_reach_the_workspace` |
| `03-merge-failure-deletes-the-destination.patch` | (c) a conflicting symlink fails the merge, and `_seed_one` deletes the whole destination, including the earlier seed | `::test_a_conflicting_symlink_is_logged_and_keeps_the_rest_of_the_destination`, `::test_two_seeds_sharing_a_symlink_both_reach_the_workspace` |

Patch 03 reaches the destination wipe through the conflict path. A genuine `OSError` during a copy still removes that tool's cache on purpose ("installs cold rather than from half a seed"), so this PR does not mutate that branch.
