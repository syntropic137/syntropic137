# Mutation evidence for #1715 (PR #2050)

Each patch mutates `_POOLED_RESOURCE_QUERY`, the SQL behind
`PhaseProfileQueryService.run_demand()`. Every one must be killed by:

    apps/syn-api/tests/integration/test_phase_profiles_reach_the_api.py::test_run_demand_pools_every_phase_in_the_window

Docker-backed (TimescaleDB), so run with the default `docker=true`.

| Patch | Bug | Why the test fails |
|---|---|---|
| 01-pooled-lower-bound-exclusive | `time > $1` | sample 12, exactly at `now - window`, drops: 11 samples, p50 0.6 not 0.65 |
| 02-pooled-upper-bound-inclusive | `time <= $2` | the 1,000,000-scale row exactly at `now` joins: p95 memory explodes |
| 03-pooled-no-lower-bound | lower bound removed | the 1,000,000-scale row a second before the window joins |
| 04-pooled-merges-an-executions-phases | `GROUP BY execution_id` | plan and build of one execution merge: 6 samples < MIN_SAMPLES, demand is None |
