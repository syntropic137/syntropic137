# Mutation evidence for #641

Tests:
- `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/dashboard_metrics/test_get_metrics.py`
- `packages/syn-adapters/tests/test_manager_event_routing.py`

| Patch | Bug re-introduced | Killed by (locally, in a workspace) |
|---|---|---|
| 01-archive-does-not-decrement | archive leaves total_workflows unchanged (the #641 bug) | test_archived_template_is_not_counted, routing test |
| 02-archive-goes-below-zero | no `max(0, ...)` floor | test_archive_never_drives_count_below_zero |
| 03-every-update-increments | every Updated adds 1, archived or not | test_updating_a_live_template_does_not_count_it_twice, test_rebuild_clears_archived_markers |
| 04-repeat-archive-decrements-again | a repeated archive subtracts again | test_repeated_archive_counts_once |
| 05-event-map-unrouted | EVENT_HANDLERS does not route archive/update to dashboard_metrics | test_dashboard_total_workflows_follows_archive_and_reinstall |
