# Mutation evidence for #1936 (#1716): blocker B1

Evidence only. `ci.yml`'s `mutations-not-merged` job rejects this directory,
so delete `.mutations/` before merge.

Every patch touches production source only and passes `git apply --check`
against this head. Run with `docker=true`. The OOM module drives a real
`WorkspaceDockerProvider`, and the profiles module reaches TimescaleDB through
`test_infrastructure`. Without them, both modules now fail rather than skip.

| Patch | Bug it reintroduces | Source | Killed by |
|---|---|---|---|
| `01-oom-killed-dropped-from-profile.patch` | A killed attempt never reaches the phase profile, so the profile reports no OOM kills | `syn_domain/.../phase_profiles/query_service.py` `_resource_profiles` | `test_a_retry_after_an_oom_kill_does_not_erase_it` (`before.oom.killed == 1`); `test_an_oom_killed_workspace_reaches_the_api_as_one` (`killed == 1`) |
| `02-missing-peak-memory-written-as-zero.patch` | An attempt that measured no peak memory is counted as a 0-byte sample | `syn_domain/.../phase_profiles/query_service.py` `_resource_profiles` | `test_a_retry_after_an_oom_kill_does_not_erase_it` (`after.memory_peak_bytes.n == 1`: exec-01's newest attempt measured nothing) |
| `03-p90-from-wrong-field.patch` | The token p90 the API returns is read from `p95` | `syn_api/types.py` `TokenPercentilesResponse.of` | `test_phase_profiles_are_read_from_recorded_usage` (`plan input_tokens p90 == 10900`; p95 is 11450) |
| `04-oom-flag-not-exposed-by-api.patch` | The response's `oom_killed_phases` is always empty, so no phase reaches the API as `oom_killed: true` | `syn_api/types.py` `PhaseProfilesResponse.from_profiles` | `test_an_oom_killed_workspace_reaches_the_api_as_one` (`(oom,) = build.oom_killed_phases`); `test_a_retry_after_an_oom_kill_does_not_erase_it` |

`test_a_completed_phase_rate_does_not_depend_on_the_look_back` kills none of
these. It is named so that it runs once on the unmutated head, by node id.

## `tests` input (space-separated, `docker=true`)

```
apps/syn-api/tests/integration/test_phase_profiles_reach_the_api.py::test_phase_profiles_are_read_from_recorded_usage apps/syn-api/tests/integration/test_phase_profiles_reach_the_api.py::test_a_completed_phase_rate_does_not_depend_on_the_look_back apps/syn-api/tests/integration/test_phase_profiles_reach_the_api.py::test_a_retry_after_an_oom_kill_does_not_erase_it apps/syn-api/tests/integration/test_oom_killed_phase_reaches_the_api.py::test_an_oom_killed_workspace_reaches_the_api_as_one
```

```
just mutation-evidence 1936 "<the ids above>"
```
