# Mutation evidence for #641

Tests:
- `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/dashboard_metrics/test_get_metrics.py`
- `packages/syn-adapters/tests/test_manager_event_routing.py`

Regenerated after the review fix (7a5fddef0): `total_workflows` is now the size of the live-template set in the `global` record, so the earlier marker-record patches no longer apply.

| Patch | Bug re-introduced | Killed locally (failures / 25) |
|---|---|---|
| 01-archive-does-not-remove | archive keeps the template counted (the #641 bug) | 6 |
| 02-add-never-counts | Created/reinstall never adds the template | 11 |
| 03-counter-not-set | a running counter instead of the set: double counts, and an archive of a never-counted template subtracts another | 4 |
| 05-event-map-unrouted | EVENT_HANDLERS does not route archive/update to dashboard_metrics | 2 |
