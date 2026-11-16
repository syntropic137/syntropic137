# Mutation patches for #2300

Tests: `packages/syn-adapters/tests/test_2300_deregistered_repo_leaves_its_system.py`
(`test_deregistering_an_assigned_repo_removes_it_from_show_status_and_list`,
`test_deregister_after_reassign_leaves_only_the_current_system`).

| Patch | Re-introduces |
|---|---|
| 01-unsubscribe-repo-deregistered | neither adapter subscribes to `organization.RepoDeregistered` (the #2300 bug) |
| 02-no-system-handler-alias | `SystemProjection` has no `on_repo_deregistered`, so the subscribed event reaches no handler |
| 03-repo-list-unsubscribed | only `repo_list` drops the subscription (status and `list --system` stay stale) |
| 04-system-list-unsubscribed | only `system_list` drops the subscription (show repo_count stays stale) |
