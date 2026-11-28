# Mutation evidence for #2383 slice 6 (PR #2397)

Each patch re-introduces one bug into `query_service.py`. All are killed by the
TimescaleDB parity suite (needs Docker, so `docker=true`):

```
just mutation-evidence 2397 "packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_canonical_totals_rollup_parity.py"
```

| patch | bug | expected killer |
|---|---|---|
| 01-count-zero-token-turns | sums `observations`, so zero-token turns count as reported | `test_unfiltered_totals_match_field_by_field` (shape-5 sessions carry a zero-token unpriced turn) |
| 02-scoped-reported-turns-unfiltered | the reported branch drops the execution filter on a scoped read | `test_each_workflows_totals_match_field_by_field[wf-a]`/`[wf-b]` (unpriced turns of other workflows leak in) |
| 03-priced-model-turns-counted-unpriced | counts every turn of a session that has an unpriced turn, priced models included | `test_unfiltered_...` and `[wf-a]` (a-sess-0 mixes rated and unrated turns) |
